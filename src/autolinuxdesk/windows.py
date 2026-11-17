"""Top-level X11 windows through wmctrl and xdotool."""

from __future__ import annotations

import re
import subprocess
from typing import Any

from autolinuxdesk.logger import get_logger

log = get_logger(__name__)

_TOOL_TIMEOUT_S = 10
_WINDOW_ID_RE = re.compile(r"^(0x[0-9a-fA-F]{1,8}|[0-9]{1,10})$")
_STATES = {
    "maximize": ("add", "maximized_vert,maximized_horz"),
    "unmaximize": ("remove", "maximized_vert,maximized_horz"),
    "fullscreen": ("add", "fullscreen"),
    "unfullscreen": ("remove", "fullscreen"),
    "minimize": ("add", "hidden"),
    "unminimize": ("remove", "hidden"),
    "above": ("add", "above"),
    "unabove": ("remove", "above"),
}


class WindowError(Exception):
    """A window request was invalid or the window tool failed."""


def _run(argv: list[str]) -> str:
    try:
        result = subprocess.run(  # noqa: S603 - fixed tool, argv list
            argv,
            capture_output=True,
            text=True,
            timeout=_TOOL_TIMEOUT_S,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise WindowError(f"{argv[0]} failed: {error}") from error
    if result.returncode != 0:
        raise WindowError(f"{argv[0]} failed: {result.stderr.strip() or result.returncode}")
    return result.stdout


def _normalize_id(raw: str) -> str:
    return f"0x{int(raw, 0):08x}"


def active_window_id() -> str | None:
    try:
        output = _run(["xdotool", "getactivewindow"]).strip()
    except WindowError:
        return None
    return _normalize_id(output) if output.isdigit() else None


def list_windows() -> list[dict[str, Any]]:
    """Managed windows with geometry, owning pid, WM_CLASS and title."""
    active = active_window_id()
    windows = []
    for line in _run(["wmctrl", "-l", "-p", "-G", "-x"]).splitlines():
        parts = line.split(None, 9)
        if len(parts) < 9:
            continue
        window_id, desktop, pid, x, y, width, height, wm_class = parts[:8]
        # Column 9 is the client host; the title follows it and may be empty.
        title = parts[9] if len(parts) > 9 else ""
        normalized = _normalize_id(window_id)
        windows.append(
            {
                "id": normalized,
                "desktop": int(desktop),
                "pid": int(pid) or None,
                "x": int(x),
                "y": int(y),
                "width": int(width),
                "height": int(height),
                "wm_class": wm_class,
                "title": title,
                "active": normalized == active,
            }
        )
    return windows


def resolve_window(cmd: dict) -> dict[str, Any]:
    """Find one window by exactly one of id, title (substring), wm_class or pid."""
    selectors = [key for key in ("id", "title", "wm_class", "pid") if cmd.get(key) is not None]
    if len(selectors) != 1:
        raise WindowError("give exactly one of id, title, wm_class or pid")
    key = selectors[0]
    value = cmd[key]
    windows = list_windows()
    if key == "id":
        if not isinstance(value, str) or not _WINDOW_ID_RE.match(value):
            raise WindowError("id must be a window id such as 0x01e00003")
        wanted = _normalize_id(value)
        matches = [window for window in windows if window["id"] == wanted]
    elif key == "pid":
        if isinstance(value, bool) or not isinstance(value, int):
            raise WindowError("pid must be an integer")
        matches = [window for window in windows if window["pid"] == value]
    else:
        if not isinstance(value, str) or not value:
            raise WindowError(f"{key} must be a non-empty string")
        needle = value.lower()
        matches = [window for window in windows if needle in window[key].lower()]
    if not matches:
        raise WindowError(f"no window matches {key}={value!r}")
    return matches[0]


def focus(window: dict[str, Any]) -> None:
    _run(["wmctrl", "-i", "-a", window["id"]])


def close(window: dict[str, Any]) -> None:
    _run(["wmctrl", "-i", "-c", window["id"]])


def _geometry_value(cmd: dict, name: str) -> int:
    value = cmd.get(name)
    if value is None:
        return -1
    if isinstance(value, bool) or not isinstance(value, int):
        raise WindowError(f"{name} must be an integer")
    if name in ("width", "height") and value < 1:
        raise WindowError(f"{name} must be at least 1")
    return value


def move_resize(window: dict[str, Any], cmd: dict) -> None:
    geometry = [_geometry_value(cmd, name) for name in ("x", "y", "width", "height")]
    if geometry == [-1, -1, -1, -1]:
        raise WindowError("give at least one of x, y, width or height")
    # A maximized window ignores geometry changes until it is restored.
    _run(["wmctrl", "-i", "-r", window["id"], "-b", "remove,maximized_vert,maximized_horz"])
    _run(["wmctrl", "-i", "-r", window["id"], "-e", "0," + ",".join(map(str, geometry))])


def set_state(window: dict[str, Any], state: Any) -> None:
    if state not in _STATES:
        raise WindowError(f"state must be one of {', '.join(_STATES)}")
    verb, properties = _STATES[state]
    if state == "minimize":
        _run(["xdotool", "windowminimize", str(int(window["id"], 16))])
        return
    _run(["wmctrl", "-i", "-r", window["id"], "-b", f"{verb},{properties}"])


STATES = tuple(_STATES)
