"""MCP tools for the base actions.

Each tool calls the same dispatcher as POST / under the same request lock.
Plugins can replace or remove any of these by name through the registry
before the server starts.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from fastmcp.tools import ToolResult
from fastmcp.utilities.types import Image
from mcp.types import TextContent

from autolinuxdesk.clipboard import redact_clipboard_params
from autolinuxdesk.desk import Desk
from autolinuxdesk.logger import get_logger
from autolinuxdesk.registry import Registry
from autolinuxdesk.responses import BINARY_KEY

log = get_logger(__name__)


def make_caller(desk: Desk) -> Callable[..., Any]:
    """Return call(action, **params) that dispatches under the request lock."""

    async def call(action: str, **params: Any) -> dict:
        filtered = {key: value for key, value in params.items() if value is not None}
        logged = redact_clipboard_params(action, filtered)
        log.info(">> %s %s", action, logged if logged else "")
        async with desk.lock:
            result = await desk.dispatch({"action": action, **filtered})
        if result.get("success", False):
            log.info("<< %s OK", action)
        else:
            log.warning("<< %s FAIL: %s", action, result.get("error", "?"))
        return result

    return call


def text_result(result: dict) -> str:
    """JSON text for an MCP response, without binary payloads."""
    return json.dumps(
        {key: value for key, value in result.items() if key != BINARY_KEY}, default=str
    )


def image_or_text(result: dict) -> ToolResult:
    binary = result.pop(BINARY_KEY, None)
    if binary:
        return ToolResult(content=[Image(data=binary, format="png")])
    return ToolResult(content=[TextContent(type="text", text=text_result(result))])


def register(registry: Registry, desk: Desk) -> None:  # noqa: C901 - one tool per action
    call = make_caller(desk)
    tool = registry.mcp_tool

    @tool()
    async def run_script(
        steps: list[dict],
        name: str = "mcp_script",
        on_error: str = "stop",
    ) -> str:
        """Run multiple actions as one atomic script.

        All steps execute in order under a single request lock. Each step is
        a dict with "action" and its parameters; any action this server
        offers can be a step. Add "output_id" to collect a step's result in
        the response outputs. Control nodes: {"if": {"condition": ...,
        "then": [...], "else": [...]}}, {"repeat": {"count": 1, "steps":
        [...]}} and {"while": {"condition": ..., "max_iterations": 1,
        "steps": [...]}}. Conditions: output (output_id, path, equals or
        exists), all, any and not. Page conditions (element, text, url,
        javascript) need a plugin that provides an eval action.

        on_error: "stop" (default) halts on the first failure, "continue"
        keeps going.
        """
        return text_result(await call("run_script", steps=steps, name=name, on_error=on_error))

    @tool()
    async def screenshot(
        width: int | None = None,
        height: int | None = None,
        whLargest: int | None = None,
    ) -> ToolResult:
        """Take a PNG screenshot of the whole virtual screen.

        Always pass whLargest=512 unless you need fine detail.

        Args:
            width: Resize to this width (keeps aspect ratio if height omitted).
            height: Resize to this height (keeps aspect ratio if width omitted).
            whLargest: Resize so the largest side is this many pixels.
        """
        return image_or_text(
            await call("desktop_screenshot", width=width, height=height, whLargest=whLargest)
        )

    @tool()
    async def get_resolution() -> str:
        """Return the virtual screen width and height in pixels."""
        return text_result(await call("get_resolution"))

    @tool()
    async def system_click(
        x: int,
        y: int,
        w: int | None = None,
        h: int | None = None,
        duration: float | None = None,
        speed: float | None = None,
        curvature: float | None = None,
        tremor: float | None = None,
        click_hold: float | None = None,
        click_delay: float | None = None,
    ) -> str:
        """Move the real mouse with human motion to screen coordinates and click.

        Args:
            x: Screen X coordinate of the target centre.
            y: Screen Y coordinate of the target centre.
            w: Target width. The click lands at a human offset inside it.
            h: Target height.
            duration: Scale the movement to this many seconds.
            speed: Movement speed multiplier (0.1-10).
            curvature: Main stroke bend multiplier (0-5, 0 = straight).
            tremor: Hand tremor amplitude in px (0-5).
            click_hold: Median seconds the button is held (0.01-5).
            click_delay: Median seconds between arriving and pressing (0-10).
        """
        return text_result(
            await call(
                "system_click",
                x=x,
                y=y,
                w=w,
                h=h,
                duration=duration,
                speed=speed,
                curvature=curvature,
                tremor=tremor,
                click_hold=click_hold,
                click_delay=click_delay,
            )
        )

    @tool()
    async def system_double_click(
        x: int, y: int, w: int | None = None, h: int | None = None
    ) -> str:
        """Double-click at screen coordinates with human motion and timing."""
        return text_result(await call("system_double_click", x=x, y=y, w=w, h=h))

    @tool()
    async def system_right_click(x: int, y: int, w: int | None = None, h: int | None = None) -> str:
        """Right-click at screen coordinates with human motion and timing."""
        return text_result(await call("system_right_click", x=x, y=y, w=w, h=h))

    @tool()
    async def system_drag(source_x: int, source_y: int, target_x: int, target_y: int) -> str:
        """Press at the source point, drag along a human path and release at the target."""
        return text_result(
            await call(
                "system_drag",
                source_x=source_x,
                source_y=source_y,
                target_x=target_x,
                target_y=target_y,
            )
        )

    @tool()
    async def mouse_move(
        x: int,
        y: int,
        w: int | None = None,
        h: int | None = None,
        duration: float | None = None,
        speed: float | None = None,
    ) -> str:
        """Move the mouse to screen coordinates with human motion, without clicking."""
        return text_result(
            await call("mouse_move", x=x, y=y, w=w, h=h, duration=duration, speed=speed)
        )

    @tool()
    async def system_type(
        text: str,
        interval: float | None = None,
        typos: bool = False,
        typo_rate: float | None = None,
        key_hold: float | None = None,
        rollover: float | None = None,
    ) -> str:
        """Type text into the focused window with real keystrokes and human timing.

        Focus the target first, for example with system_click. Characters
        outside the US layout are typed too.

        Args:
            text: The text to type.
            interval: Median gap between key presses in seconds.
            typos: Make and correct occasional typos.
            typo_rate: Typos per letter (0-0.2, default 0.02 when typos is on).
            key_hold: Median seconds each key is held (0.01-2).
            rollover: Chance of keeping a key overlap (0-1).
        """
        return text_result(
            await call(
                "system_type",
                text=text,
                interval=interval,
                typos=typos or bool(typo_rate),
                typo_rate=typo_rate,
                key_hold=key_hold,
                rollover=rollover,
            )
        )

    @tool()
    async def send_key(key: str, key_hold: float | None = None, instant: bool = False) -> str:
        """Send a key or combo such as "enter", "ctrl+a" or "alt+f4" (PyAutoGUI names)."""
        return text_result(await call("send_key", key=key, key_hold=key_hold, instant=instant))

    @tool()
    async def scroll(
        amount: int = -3,
        x: int | None = None,
        y: int | None = None,
        notch_gap: float | None = None,
    ) -> str:
        """Scroll the mouse wheel. Negative amount scrolls down, positive up.

        Args:
            amount: Wheel notches, non-zero.
            x: Optional screen X to move the pointer to first.
            y: Optional screen Y to move the pointer to first.
            notch_gap: Median seconds between notches (0.015-5).
        """
        return text_result(await call("scroll", amount=amount, x=x, y=y, notch_gap=notch_gap))

    @tool()
    async def human_pause(
        duration: float = 1.0,
        x: int | None = None,
        y: int | None = None,
        w: int | None = None,
        h: int | None = None,
        drift: bool = True,
    ) -> str:
        """Pause for visible reading or thinking time, with sparse pointer drift.

        Use only when the task naturally needs that time, not between every action.

        Args:
            duration: Seconds, 0.1 through 300.
            x: Optional screen X centre of a region to keep the pointer in.
            y: Optional screen Y centre of that region.
            w: Region width, 4 through 10000.
            h: Region height, 4 through 10000.
            drift: Allow small irregular pointer moves. Default true.
        """
        return text_result(
            await call("human_pause", duration=duration, x=x, y=y, w=w, h=h, drift=drift)
        )

    @tool()
    async def desktop_list_windows() -> str:
        """List top-level windows with id, title, WM_CLASS, pid, geometry and focus."""
        return text_result(await call("desktop_list_windows"))

    @tool()
    async def desktop_keybindings() -> str:
        """List the window manager's keyboard shortcuts.

        Each entry has the Openbox key, a send_key value to press it (a list
        with one entry per press for chained bindings), a description and
        the raw actions. Covers opening a terminal, tiling windows to a
        screen half, maximize, fullscreen, minimize, closing and switching
        windows.
        """
        return text_result(await call("desktop_keybindings"))

    @tool()
    async def desktop_focus_window(
        id: str | None = None,
        title: str | None = None,
        wm_class: str | None = None,
        pid: int | None = None,
    ) -> str:
        """Raise and focus one window, chosen by exactly one of id, title, wm_class or pid.

        title and wm_class match case-insensitive substrings; the first match wins.
        """
        return text_result(
            await call("desktop_focus_window", id=id, title=title, wm_class=wm_class, pid=pid)
        )

    @tool()
    async def desktop_move_resize_window(
        id: str | None = None,
        title: str | None = None,
        wm_class: str | None = None,
        pid: int | None = None,
        x: int | None = None,
        y: int | None = None,
        width: int | None = None,
        height: int | None = None,
    ) -> str:
        """Move or resize one window. Omitted geometry values stay as they are."""
        return text_result(
            await call(
                "desktop_move_resize_window",
                id=id,
                title=title,
                wm_class=wm_class,
                pid=pid,
                x=x,
                y=y,
                width=width,
                height=height,
            )
        )

    @tool()
    async def desktop_set_window_state(
        state: str,
        id: str | None = None,
        title: str | None = None,
        wm_class: str | None = None,
        pid: int | None = None,
    ) -> str:
        """Maximize, minimize, fullscreen or pin one window above others, or undo that.

        state: maximize, unmaximize, fullscreen, unfullscreen, minimize,
        unminimize, above or unabove.
        """
        return text_result(
            await call(
                "desktop_set_window_state",
                state=state,
                id=id,
                title=title,
                wm_class=wm_class,
                pid=pid,
            )
        )

    @tool()
    async def desktop_close_window(
        id: str | None = None,
        title: str | None = None,
        wm_class: str | None = None,
        pid: int | None = None,
    ) -> str:
        """Ask one window to close, as its close button would."""
        return text_result(
            await call("desktop_close_window", id=id, title=title, wm_class=wm_class, pid=pid)
        )

    @tool()
    async def launch_app(
        command: list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
    ) -> str:
        """Start a program detached on the virtual display and return its id and pid.

        Args:
            command: Program and arguments, e.g. ["xterm"] or ["gedit", "/tmp/a.txt"].
            cwd: Working directory.
            env: Extra environment variables.
        """
        return text_result(await call("launch_app", command=command, cwd=cwd, env=env))

    @tool()
    async def list_launched(output: bool = False) -> str:
        """List programs started with launch_app; output=true adds each log tail."""
        return text_result(await call("list_launched", output=output))

    @tool()
    async def kill_launched(id: int, signal: str = "TERM") -> str:
        """Stop a program started with launch_app. signal: TERM, INT or KILL."""
        return text_result(await call("kill_launched", id=id, signal=signal))

    @tool()
    async def run_command(
        command: str | list[str],
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        stdin: str | None = None,
        timeout_s: float = 30,
    ) -> str:
        """Run a shell command as the container user and return exit code and output.

        A string runs under bash -c; a list runs the program directly.
        stdout and stderr are capped at 1 MiB each. The command and every
        process it started are killed at the timeout.

        Args:
            command: Shell string or argv list.
            cwd: Working directory.
            env: Extra environment variables.
            stdin: Text written to the command's standard input.
            timeout_s: Seconds before the command is killed, up to 600.
        """
        return text_result(
            await call(
                "run_command",
                command=command,
                cwd=cwd,
                env=env,
                stdin=stdin,
                timeout_s=timeout_s,
            )
        )

    @tool()
    async def set_clipboard(text: str) -> str:
        """Replace the X11 clipboard with UTF-8 text up to 1 MiB."""
        return text_result(await call("set_clipboard", text=text))

    @tool()
    async def get_clipboard(format: str = "text") -> str:
        """Read text, html, image/png or files from the X11 clipboard."""
        return text_result(await call("get_clipboard", format=format))

    @tool()
    async def get_events(
        after_id: int = 0, types: list[str] | None = None, limit: int = 100
    ) -> str:
        """Read buffered events after an event ID."""
        return text_result(await call("get_events", after_id=after_id, types=types, limit=limit))

    @tool()
    async def wait_for_event(
        after_id: int = 0, types: list[str] | None = None, timeout: float = 30
    ) -> str:
        """Wait for a matching event without polling."""
        return text_result(
            await call("wait_for_event", after_id=after_id, types=types, timeout=timeout)
        )

    @tool()
    async def begin_handoff() -> str:
        """Pause mutating automation while a person controls the desktop over VNC."""
        return text_result(await call("begin_handoff"))

    @tool()
    async def handoff_status() -> str:
        """Return whether a human handoff is active."""
        return text_result(await call("handoff_status"))

    @tool()
    async def end_handoff() -> str:
        """Return control to automation after a human handoff."""
        return text_result(await call("end_handoff"))

    @tool()
    async def desk_action(action: str, params: dict | None = None) -> str:
        """Run any action by name, including ones without a dedicated tool.

        Useful for recording (start_recording, stop_recording,
        recording_status), pointer control (system_hover, system_mouse_down,
        system_mouse_up, mouse_click), list_actions, ping and sleep.

        Args:
            action: The action name.
            params: Optional dict of action parameters.
        """
        return text_result(await call(action, **(params or {})))
