"""The actions the base image registers."""

from __future__ import annotations

import asyncio
import io
import os
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from collections.abc import Callable

import yaml

from autolinuxdesk import accessibility, input_actions, keybindings, processes, windows
from autolinuxdesk.clipboard import ClipboardError
from autolinuxdesk.desk import Desk
from autolinuxdesk.events import EventError
from autolinuxdesk.logger import get_logger
from autolinuxdesk.recorder import RecorderError
from autolinuxdesk.registry import Registry
from autolinuxdesk.responses import (
    BINARY_KEY,
    ActionError,
    fail,
    ok,
    resize_png,
)
from autolinuxdesk.script_runner import ScriptValidationError, run_script, validate_script

log = get_logger(__name__)

EXEC_DISABLED_ERROR = "shell and program execution is disabled (DESK_EXEC_ENABLED=false)"
_SLEEP_MAX_S = 3600.0
_SCROT_TIMEOUT_S = 30


def _event_types(cmd: dict) -> set[str] | None:
    raw_types = cmd.get("types")
    if raw_types is None:
        return None
    if not isinstance(raw_types, list) or not all(
        isinstance(item, str) and item for item in raw_types
    ):
        raise EventError("types must be a list of non-empty strings")
    return set(raw_types)


async def ping(cmd: dict, desk: Desk) -> dict:
    return ok({"message": "pong"})


async def list_actions(cmd: dict, desk: Desk) -> dict:
    return ok({"actions": sorted(desk.registry.actions)})


async def close(cmd: dict, desk: Desk) -> dict:
    log.info("Shutting down...")
    asyncio.get_running_loop().call_soon(lambda: sys.exit(0))
    return ok({"message": "closing"})


async def sleep(cmd: dict, desk: Desk) -> dict:
    duration = cmd.get("duration", 1)
    try:
        seconds = float(duration)
    except (TypeError, ValueError) as error:
        raise ActionError("duration must be a number") from error
    if not 0 <= seconds <= _SLEEP_MAX_S:
        raise ActionError(f"duration must be between 0 and {_SLEEP_MAX_S:g}")
    await asyncio.sleep(seconds)
    return ok({"slept": duration})


async def get_events(cmd: dict, desk: Desk) -> dict:
    try:
        events = desk.events.get(
            after_id=int(cmd.get("after_id", 0)),
            event_types=_event_types(cmd),
            limit=int(cmd.get("limit", 100)),
        )
    except (EventError, TypeError, ValueError) as error:
        return fail(str(error))
    return ok({"events": events, "count": len(events)})


async def wait_for_event(cmd: dict, desk: Desk) -> dict:
    try:
        events = await desk.events.wait(
            after_id=int(cmd.get("after_id", 0)),
            event_types=_event_types(cmd),
            timeout=float(cmd.get("timeout", 30)),
        )
    except (EventError, TypeError, ValueError) as error:
        return fail(str(error))
    return ok({"events": events, "count": len(events)})


async def _handoff_activity(desk: Desk, stop: bool) -> dict | None:
    provider = desk.registry.handoff_activity
    if provider is None:
        return None
    return await provider(desk, stop)


async def begin_handoff(cmd: dict, desk: Desk) -> dict:
    if desk.handoff.active:
        return fail("human handoff is already active")
    await _handoff_activity(desk, False)
    desk.handoff.active = True
    desk.handoff.started_at = time.time()
    desk.events.publish("handoff_started", {})
    return ok({"active": True, "started_at": desk.handoff.started_at})


async def handoff_status(cmd: dict, desk: Desk) -> dict:
    activity = await _handoff_activity(desk, False) if desk.handoff.active else None
    return ok(
        {
            "active": desk.handoff.active,
            "started_at": desk.handoff.started_at,
            "activity": activity,
        }
    )


async def end_handoff(cmd: dict, desk: Desk) -> dict:
    if not desk.handoff.active:
        return fail("human handoff is not active")
    duration = time.time() - (desk.handoff.started_at or time.time())
    activity = await _handoff_activity(desk, True)
    desk.handoff.active = False
    desk.handoff.started_at = None
    desk.events.publish("handoff_ended", {"duration": duration, "activity": activity})
    return ok({"active": False, "duration": duration, "activity": activity})


async def set_clipboard(cmd: dict, desk: Desk) -> dict:
    clipboard_format = cmd.get("format", "text")
    try:
        if clipboard_format == "text":
            if "text" not in cmd:
                return fail("text required")
            return ok(await desk.clipboard.set_text(cmd.get("text")))
        if clipboard_format == "image/png":
            value = cmd.get("content_base64")
        elif clipboard_format == "files":
            value = cmd.get("files")
        else:
            value = cmd.get("text")
        return ok(await desk.clipboard.set(clipboard_format, value))
    except ClipboardError as error:
        return fail(str(error))


async def get_clipboard(cmd: dict, desk: Desk) -> dict:
    try:
        clipboard_format = cmd.get("format", "text")
        if clipboard_format == "text":
            return ok(await desk.clipboard.get_text())
        return ok(await desk.clipboard.get(clipboard_format))
    except ClipboardError as error:
        return fail(str(error))


async def start_recording(cmd: dict, desk: Desk) -> dict:
    mode = cmd.get("mode", "window")
    fps = int(cmd.get("fps", 15))
    show_cursor = bool(cmd.get("show_cursor", True))
    # viewport crops to the active surface at its current screen position;
    # window and desktop capture the whole screen from (0, 0).
    offset_x = offset_y = 0
    if mode == "viewport":
        await desk.surface.refresh_offset(desk.system)
        offset_x = int(desk.system.window_offset.get("x", 0))
        offset_y = int(desk.system.window_offset.get("y", 0))
    try:
        info = desk.recorder.start(
            mode=mode,
            fps=fps,
            offset_x=offset_x,
            offset_y=offset_y,
            show_cursor=show_cursor,
        )
    except RecorderError as error:
        return fail(str(error))
    return ok(info)


async def stop_recording(cmd: dict, desk: Desk) -> dict:
    slug = cmd.get("slug", "")
    if not slug:
        return fail("slug required")
    try:
        info = desk.recorder.stop(slug=slug)
    except RecorderError as error:
        return fail(str(error))
    return ok(info)


async def recording_status(cmd: dict, desk: Desk) -> dict:
    return ok(desk.recorder.status())


async def run_script_action(cmd: dict, desk: Desk) -> dict:
    steps = cmd.get("steps")
    yaml_content = cmd.get("yaml")
    if yaml_content:
        if not isinstance(yaml_content, str):
            return fail("yaml must be a string")
        try:
            script_data = yaml.safe_load(yaml_content)
        except yaml.YAMLError:
            return fail("invalid YAML")
    elif steps:
        script_data = {
            "name": cmd.get("name", "api_script"),
            "on_error": cmd.get("on_error", "stop"),
            "steps": steps,
        }
    else:
        return fail("steps or yaml required")
    try:
        validate_script(script_data)
    except ScriptValidationError as error:
        return fail(str(error))
    result = await run_script(script_data, desk.dispatch, stdout=io.StringIO())
    result.pop(BINARY_KEY, None)
    return ok(result)


async def get_resolution(cmd: dict, desk: Desk) -> dict:
    return ok(desk.system.get_resolution())


async def capture_desktop_png() -> bytes:
    """Full virtual screen as PNG bytes, through scrot."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
        tmp_path = tmp.name
    try:
        process = await asyncio.create_subprocess_exec(
            "scrot",
            "-o",
            tmp_path,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
        _, stderr = await asyncio.wait_for(process.communicate(), _SCROT_TIMEOUT_S)
        if process.returncode != 0:
            raise ActionError(f"scrot failed: {stderr.decode(errors='replace').strip()}")
        with open(tmp_path, "rb") as handle:
            return handle.read()
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


async def desktop_screenshot(cmd: dict, desk: Desk) -> dict:
    data = resize_png(await capture_desktop_png(), cmd)
    path = cmd.get("path", "")
    if path:
        if not isinstance(path, str):
            raise ActionError("path must be a string")
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(data)
    response = ok({"type": "desktop", "size": len(data)})
    if path:
        response["data"]["path"] = path
    response[BINARY_KEY] = data
    return response


def _window_action(
    operation: Callable[[dict, dict], dict | None],
) -> Callable[[dict, Desk], object]:
    async def handler(cmd: dict, desk: Desk) -> dict:
        try:
            window = await asyncio.to_thread(windows.resolve_window, cmd)
            extra = await asyncio.to_thread(operation, window, cmd)
        except windows.WindowError as error:
            return fail(str(error))
        return ok({"window": window, **(extra or {})})

    return handler


async def desktop_keybindings(cmd: dict, desk: Desk) -> dict:
    try:
        return ok(await asyncio.to_thread(keybindings.list_keybindings))
    except (OSError, ET.ParseError) as error:
        return fail(f"window manager config unreadable: {error}")


def _int(cmd: dict, key: str, default: int) -> int:
    value = cmd.get(key, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise accessibility.AccessibilityError(f"{key} must be a positive integer")
    return value


def _accessibility_query(cmd: dict) -> None:
    for key in ("app", "name", "role"):
        if cmd.get(key) is not None and not isinstance(cmd[key], str):
            raise accessibility.AccessibilityError(f"{key} must be a string")
    for key in ("showing_only", "exact"):
        if key in cmd and not isinstance(cmd[key], bool):
            raise accessibility.AccessibilityError(f"{key} must be true or false")
    states = cmd.get("states")
    if states is not None and (
        not isinstance(states, list)
        or not all(isinstance(state, str) and state in accessibility.STATES for state in states)
    ):
        raise accessibility.AccessibilityError("states must be a list of AT-SPI state names")


async def desktop_accessibility_tree(cmd: dict, desk: Desk) -> dict:
    try:
        _accessibility_query(cmd)
        return ok(
            await asyncio.to_thread(
                accessibility.dump,
                cmd.get("app"),
                _int(cmd, "max_depth", accessibility.DEFAULT_MAX_DEPTH),
                _int(cmd, "max_nodes", accessibility.DEFAULT_MAX_NODES),
                cmd.get("showing_only", True),
            )
        )
    except accessibility.AccessibilityError as error:
        return fail(str(error))


async def desktop_accessibility_find(cmd: dict, desk: Desk) -> dict:
    if not any(cmd.get(key) is not None for key in ("name", "role", "states")):
        return fail("desktop_accessibility_find needs name, role or states")
    try:
        _accessibility_query(cmd)
        _int(cmd, "max_depth", accessibility.DEFAULT_MAX_DEPTH)
        _int(cmd, "max_nodes", accessibility.DEFAULT_MAX_NODES)
        return ok(await asyncio.to_thread(accessibility.find, cmd))
    except accessibility.AccessibilityError as error:
        return fail(str(error))


async def desktop_accessibility_action(cmd: dict, desk: Desk) -> dict:
    element_id = cmd.get("id")
    if not isinstance(element_id, str) or not element_id:
        return fail(
            "desktop_accessibility_action needs the element id from desktop_accessibility_tree or _find"
        )
    # "invoke", not "action": the request's own "action" field names this handler.
    invoke = cmd.get("invoke")
    set_text = cmd.get("set_text")
    focus = cmd.get("focus", False)
    if invoke is not None and (isinstance(invoke, bool) or not isinstance(invoke, (str, int))):
        return fail("invoke must be an action name or integer index")
    if set_text is not None and not isinstance(set_text, str):
        return fail("set_text must be a string")
    if not isinstance(focus, bool):
        return fail("focus must be true or false")
    if sum((invoke is not None, set_text is not None, focus)) != 1:
        return fail("pass one of invoke, set_text or focus")
    try:
        return ok(
            await asyncio.to_thread(
                accessibility.act,
                element_id,
                invoke,
                set_text,
                focus,
            )
        )
    except accessibility.AccessibilityError as error:
        return fail(str(error))


async def desktop_list_windows(cmd: dict, desk: Desk) -> dict:
    try:
        found = await asyncio.to_thread(windows.list_windows)
    except windows.WindowError as error:
        return fail(str(error))
    return ok({"windows": found, "count": len(found)})


def _focus(window: dict, cmd: dict) -> None:
    windows.focus(window)


def _move_resize(window: dict, cmd: dict) -> dict:
    windows.move_resize(window, cmd)
    return {"requested": {k: cmd.get(k) for k in ("x", "y", "width", "height")}}


def _set_state(window: dict, cmd: dict) -> dict:
    windows.set_state(window, cmd.get("state"))
    return {"state": cmd.get("state")}


def _close(window: dict, cmd: dict) -> None:
    windows.close(window)


def _require_exec(desk: Desk) -> None:
    if not desk.settings.exec_enabled:
        raise ActionError(EXEC_DISABLED_ERROR)


async def launch_app(cmd: dict, desk: Desk) -> dict:
    _require_exec(desk)
    try:
        return ok(desk.processes.launch(cmd))
    except processes.ProcessError as error:
        return fail(str(error))


async def list_launched(cmd: dict, desk: Desk) -> dict:
    with_output = cmd.get("output", False)
    if not isinstance(with_output, bool):
        return fail("output must be true or false")
    if cmd.get("forget_finished", False) is True:
        desk.processes.forget_finished()
    found = desk.processes.list(with_output)
    return ok({"launched": found, "count": len(found)})


async def kill_launched(cmd: dict, desk: Desk) -> dict:
    try:
        info = await asyncio.to_thread(
            desk.processes.kill, cmd.get("id"), cmd.get("signal", "TERM")
        )
    except processes.ProcessError as error:
        return fail(str(error))
    return ok(info)


async def run_command(cmd: dict, desk: Desk) -> dict:
    _require_exec(desk)
    try:
        result = await processes.run_command(cmd)
    except processes.ProcessError as error:
        return fail(str(error))
    if result["timed_out"]:
        return fail("command timed out", result)
    return ok(result)


def input_action(handler: input_actions.ActionHandler) -> Callable[[dict, Desk], object]:
    """Adapt an input_actions handler to the registry signature."""

    async def run(cmd: dict, desk: Desk) -> dict:
        try:
            return ok(await handler(cmd, desk.surface, desk.system))
        except input_actions.InputActionError as error:
            return fail(str(error))

    return run


async def paste_text(cmd: dict, desk: Desk) -> dict:
    async def set_clipboard(text: str) -> object:
        try:
            return await desk.clipboard.set_text(text)
        except ClipboardError as error:
            raise input_actions.InputActionError(str(error)) from error

    try:
        return ok(await input_actions.paste_text(cmd, desk.surface, desk.system, set_clipboard))
    except input_actions.InputActionError as error:
        return fail(str(error))


_HANDOFF_SAFE = {
    "ping": ping,
    "list_actions": list_actions,
    "sleep": sleep,
    "get_events": get_events,
    "wait_for_event": wait_for_event,
    "handoff_status": handoff_status,
    "end_handoff": end_handoff,
    "recording_status": recording_status,
    "get_resolution": get_resolution,
    "desktop_screenshot": desktop_screenshot,
    "desktop_list_windows": desktop_list_windows,
    "desktop_keybindings": desktop_keybindings,
    "desktop_accessibility_tree": desktop_accessibility_tree,
    "desktop_accessibility_find": desktop_accessibility_find,
    "list_launched": list_launched,
}

_OTHER = {
    "close": close,
    "begin_handoff": begin_handoff,
    "set_clipboard": set_clipboard,
    "get_clipboard": get_clipboard,
    "start_recording": start_recording,
    "stop_recording": stop_recording,
    "run_script": run_script_action,
    "desktop_focus_window": _window_action(_focus),
    "desktop_move_resize_window": _window_action(_move_resize),
    "desktop_set_window_state": _window_action(_set_state),
    "desktop_close_window": _window_action(_close),
    "launch_app": launch_app,
    "kill_launched": kill_launched,
    "run_command": run_command,
    "paste_text": paste_text,
    "desktop_accessibility_action": desktop_accessibility_action,
}


def register(registry: Registry) -> None:
    for name, handler in _HANDOFF_SAFE.items():
        registry.register_action(name, handler, handoff_safe=True)
    for name, handler in _OTHER.items():
        registry.register_action(name, handler)
    for name, handler in input_actions.ACTIONS.items():
        registry.register_action(name, input_action(handler))
