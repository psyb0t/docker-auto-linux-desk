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
        """Double-click at screen coordinates with human motion and timing.

        Both clicks land inside the toolkit's double-click time. Takes the
        same optional mouse overrides as system_click.
        """
        return text_result(
            await call(
                "system_double_click",
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
    async def system_right_click(
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
        """Right-click at screen coordinates with human motion and timing.

        Takes the same optional mouse overrides as system_click.
        """
        return text_result(
            await call(
                "system_right_click",
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
    async def system_drag(
        source_x: int,
        source_y: int,
        target_x: int,
        target_y: int,
        speed: float | None = None,
        curvature: float | None = None,
        tremor: float | None = None,
        click_hold: float | None = None,
        click_delay: float | None = None,
    ) -> str:
        """Press at the source point, drag along a human path and release at the target.

        Args:
            source_x: Screen X to press at.
            source_y: Screen Y to press at.
            target_x: Screen X to release at.
            target_y: Screen Y to release at.
            speed: Movement speed multiplier (0.1-10).
            curvature: Main stroke bend multiplier (0-5, 0 = straight).
            tremor: Hand tremor amplitude in px (0-5).
            click_hold: Median seconds the button is held (0.01-5).
            click_delay: Median seconds between arriving and pressing (0-10).
        """
        return text_result(
            await call(
                "system_drag",
                source_x=source_x,
                source_y=source_y,
                target_x=target_x,
                target_y=target_y,
                speed=speed,
                curvature=curvature,
                tremor=tremor,
                click_hold=click_hold,
                click_delay=click_delay,
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
        curvature: float | None = None,
        tremor: float | None = None,
    ) -> str:
        """Move the mouse to screen coordinates with human-like movement (no click).

        Use to hover over things (open menus, show tooltips).

        Args:
            x: Screen X coordinate.
            y: Screen Y coordinate.
            w: Target width; the pointer lands inside the target.
            h: Target height.
            duration: Scale the movement to this many seconds.
            speed: Movement speed multiplier (0.1-10).
            curvature: Main stroke bend multiplier (0-5, 0 = straight).
            tremor: Hand tremor amplitude in px (0-5).
        """
        return text_result(
            await call(
                "mouse_move",
                x=x,
                y=y,
                w=w,
                h=h,
                duration=duration,
                speed=speed,
                curvature=curvature,
                tremor=tremor,
            )
        )

    @tool()
    async def paste_text(
        text: str,
        x: int | None = None,
        y: int | None = None,
        w: int | None = None,
        h: int | None = None,
        replace: bool = True,
    ) -> str:
        """Enter text the way people do: paste it, with human key timing.

        The default way to put text into a field. Puts the text on the
        clipboard, clicks the field when x and y are given, then presses
        ctrl+a, backspace and ctrl+v with human timing and irregular pauses
        between them. Use system_type only for a few characters.

        For GUI text fields, where ctrl+a selects all and ctrl+v pastes.
        Terminals use other keys; type there with system_type or run the
        command with run_command.

        Args:
            text: The text to enter, up to 1 MiB.
            x: Optional screen X of the field to click first.
            y: Optional screen Y of the field to click first.
            w: Field width; the click lands at a human offset inside it.
            h: Field height.
            replace: Select all and clear before pasting (default true).
                False pastes at the caret.
        """
        return text_result(await call("paste_text", text=text, x=x, y=y, w=w, h=h, replace=replace))

    @tool()
    async def system_type(
        text: str,
        interval: float | None = None,
        typos: bool = False,
        typo_rate: float | None = None,
        key_hold: float | None = None,
        rollover: float | None = None,
    ) -> str:
        """Type a few characters into the focused window with human keystrokes.

        For short input only: a word, a short search, a small edit, a
        one-line command, or a field that blocks pasting. People rarely type
        anything longer; they paste it. Use paste_text for everything else:
        it puts the text on the clipboard and presses ctrl+a, backspace and
        ctrl+v with human timing.

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
        """Press a key or combo with human timing.

        Examples: "enter", "tab", "escape", "backspace", "ctrl+a", "ctrl+v",
        "alt+f4", "ctrl+alt+left". To enter text, use paste_text instead of
        chaining clipboard and key presses yourself.

        Args:
            key: Key name or combo using PyAutoGUI key names.
            key_hold: Median seconds the key is held (0.01-2).
            instant: Press and release at once with no human timing. Easy to
                tell apart from a person; leave it false.
        """
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
        drift_interval: float | None = None,
        drift_distance: float | None = None,
        speed: float | None = None,
        curvature: float | None = None,
        tremor: float | None = None,
    ) -> str:
        """Pause for visible reading, review, or composition.

        The pointer stays still most of the time. When drift is enabled, zero
        or a few irregular moves use the same human mouse profile as other OS
        input. Use this only when the visible task naturally needs thought or
        reading time. Do not call it between every action or instead of sleep.

        Args:
            duration: Pause duration in seconds, from 0.1 through 300.
            x: Optional screen X centre of a safe parking region.
            y: Optional screen Y centre of a safe parking region.
            w: Safe region width in pixels, from 4 through 10000.
            h: Safe region height in pixels, from 4 through 10000.
            drift: Allow sparse irregular pointer drift. Default true.
            drift_interval: Median seconds between drift chances, from 1
                through 120. Default 12.
            drift_distance: Maximum drift distance in pixels, from 0 through
                500. Default 60.
            speed: Movement speed multiplier, from 0.1 through 10.
            curvature: Main stroke bend multiplier, from 0 through 5.
            tremor: Hand tremor amplitude in pixels, from 0 through 5.
        """
        return text_result(
            await call(
                "human_pause",
                duration=duration,
                x=x,
                y=y,
                w=w,
                h=h,
                drift=drift,
                drift_interval=drift_interval,
                drift_distance=drift_distance,
                speed=speed,
                curvature=curvature,
                tremor=tremor,
            )
        )

    @tool()
    async def desktop_list_windows() -> str:
        """List top-level windows with id, title, WM_CLASS, pid, geometry and focus."""
        return text_result(await call("desktop_list_windows"))

    @tool()
    async def desktop_keybindings() -> str:
        """List the desktop's complete key map.

        Each entry has the Openbox key, a send_key value to press it, a
        description, a group (Place, State, Focus, Open, Desktop) and the raw
        actions. It covers tiling to halves and quarters, maximize,
        fullscreen, minimize, close, focus by app (ctrl+alt+b browser,
        ctrl+alt+t terminal), by number (ctrl+alt+1..9) and by direction,
        and opening a terminal. No default binding uses the Super key, so the keys
        avoid shortcuts commonly reserved by the local desktop.
        """
        return text_result(await call("desktop_keybindings"))

    @tool()
    async def desktop_accessibility_tree(
        app: str | None = None,
        max_depth: int = 30,
        max_nodes: int = 3000,
        showing_only: bool = True,
    ) -> str:
        """Dump the accessibility tree of the desktop's apps, like uiautomator dump.

        Reads AT-SPI2, the screen-reader protocol. Each node has an id, role,
        name, states, screen bounds (x, y, w, h), its actions, text and value
        where the widget has them, and its parent id and depth. Requires apps
        that export AT-SPI2 accessibility objects. Apps or controls without
        accessibility support need screenshots. app filters by application
        name (substring) or id. showing_only keeps application roots and
        prunes nodes without the showing state and their children.
        truncated is true when max_nodes cut the list.
        """
        return text_result(
            await call(
                "desktop_accessibility_tree",
                app=app,
                max_depth=max_depth,
                max_nodes=max_nodes,
                showing_only=showing_only,
            )
        )

    @tool()
    async def desktop_accessibility_find(
        name: str | None = None,
        role: str | None = None,
        states: list[str] | None = None,
        app: str | None = None,
        exact: bool = False,
        max_depth: int = 30,
        max_nodes: int = 3000,
        showing_only: bool = True,
    ) -> str:
        """Find accessibility nodes by name, role and states.

        name matches case-insensitively, as a substring unless exact is true.
        role is the AT-SPI role name ("push button", "entry", "menu item",
        "check box", "link"). states must all be present ("focusable",
        "enabled", "checked"). Returns the matching nodes with their bounds;
        click a node's bounds with system_click for a human click, or pass its
        id to desktop_accessibility_action.
        """
        return text_result(
            await call(
                "desktop_accessibility_find",
                name=name,
                role=role,
                states=states,
                app=app,
                exact=exact,
                max_depth=max_depth,
                max_nodes=max_nodes,
                showing_only=showing_only,
            )
        )

    @tool()
    async def desktop_accessibility_action(
        id: str,
        invoke: str | int | None = None,
        set_text: str | None = None,
        focus: bool = False,
    ) -> str:
        """Act on an accessibility node by id, without moving the mouse.

        Pass exactly one of invoke, set_text or focus=true.
        invoke runs one of the node's AT-SPI actions by name as the node lists
        it ("Click", "Press", "Activate", "Toggle") or by index.
        set_text replaces an editable node's text. focus
        gives the node keyboard focus. These skip humanized input; use them
        when a visible pointer or typing is not needed.
        """
        return text_result(
            await call(
                "desktop_accessibility_action",
                id=id,
                invoke=invoke,
                set_text=set_text,
                focus=focus,
            )
        )

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
        """Replace the X11 clipboard with UTF-8 text up to 1 MiB.

        To enter text into a field, use paste_text, which sets the clipboard
        and pastes with human timing in one call.
        """
        return text_result(await call("set_clipboard", text=text))

    @tool()
    async def get_clipboard(format: str = "text") -> str:
        """Read text, html, image/png or files from the X11 clipboard."""
        return text_result(await call("get_clipboard", format=format))

    @tool()
    async def set_clipboard_data(
        format: str,
        text: str | None = None,
        content_base64: str | None = None,
        files: list[str] | None = None,
    ) -> str:
        """Set HTML, PNG, or file-list clipboard data.

        Use `text` for `html`, `content_base64` for `image/png`, and `files`
        for `files`. Use set_clipboard for ordinary UTF-8 text.
        """
        return text_result(
            await call(
                "set_clipboard",
                format=format,
                text=text,
                content_base64=content_base64,
                files=files,
            )
        )

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
