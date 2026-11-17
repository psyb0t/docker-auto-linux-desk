"""Window manager key bindings, read from the live Openbox config.

Reading rc.xml at request time keeps the list true to what is installed,
including bindings an image built on this one adds or removes.
"""

from __future__ import annotations

import os
import xml.etree.ElementTree as ET
from typing import Any

NS = {"o": "http://openbox.org/3.4/rc"}
SYSTEM_RC = "/etc/xdg/openbox/rc.xml"

# Openbox modifier letters -> PyAutoGUI key names used by send_key.
_MODIFIERS = {"C": "ctrl", "A": "alt", "S": "shift", "W": "win", "M": "alt", "H": "win"}
# Openbox (X keysym) names whose PyAutoGUI name differs from the lowercase form.
_KEYS = {
    "Return": "enter",
    "Escape": "esc",
    "Print": "printscreen",
    "Prior": "pageup",
    "Next": "pagedown",
    "BackSpace": "backspace",
    "Delete": "delete",
}

_DIRECTIONS = {
    "left": "to the left",
    "right": "to the right",
    "up": "above",
    "down": "below",
}

_DESCRIPTIONS = {
    "Close": "close the focused window",
    "Iconify": "minimize the focused window",
    "Maximize": "maximize the focused window",
    "Unmaximize": "restore the focused window from maximized",
    "UnmaximizeFull": "restore the focused window from maximized",
    "ToggleMaximize": "toggle maximize on the focused window",
    "ToggleFullscreen": "toggle fullscreen on the focused window",
    "ToggleShowDesktop": "hide or show all windows",
    "NextWindow": "switch to the next window",
    "PreviousWindow": "switch to the previous window",
    "DirectionalCycleWindows": "focus the nearest window in a direction",
    "ShowMenu": "open a window manager menu",
    "Lower": "send the focused window to the back",
    "FocusToBottom": "",
    "Unfocus": "",
    "Reconfigure": "reload the window manager config",
}


def rc_path() -> str:
    home = os.environ.get("HOME") or os.path.expanduser("~")
    user_rc = os.path.join(home, ".config", "openbox", "rc.xml")
    return user_rc if os.path.isfile(user_rc) else SYSTEM_RC


def to_send_key(openbox_key: str) -> str:
    """Convert Openbox notation such as W-S-Left to send_key's win+shift+left."""
    parts = openbox_key.split("-")
    *mods, key = parts
    names = [_MODIFIERS.get(mod, mod.lower()) for mod in mods]
    names.append(_KEYS.get(key, key.lower()))
    return "+".join(names)


def _options(action: ET.Element) -> dict[str, str]:
    return {child.tag.split("}", 1)[-1]: (child.text or "").strip() for child in action}


def describe(actions: list[dict[str, Any]]) -> str:
    """Plain description of what a binding's action list does."""
    names = [action["name"] for action in actions]
    options = {k: v for action in actions for k, v in action["options"].items()}
    if names and names[0] == "Execute":
        return f"run {options.get('command', '')}".strip()
    if "MoveResizeTo" in names:
        if options.get("width") == "50%" and options.get("x") == "0":
            return "tile the focused window to the left half"
        if options.get("width") == "50%" and options.get("x") == "50%":
            return "tile the focused window to the right half"
        if options.get("x") == "center":
            return "center the focused window"
        return "move or resize the focused window"
    if "DirectionalCycleWindows" in names and "direction" in options:
        where = _DIRECTIONS.get(options["direction"], options["direction"])
        return f"focus the nearest window {where}"
    if "ShowMenu" in names:
        return f"open the {options.get('menu', 'window manager')} menu"
    parts = [_DESCRIPTIONS.get(name, name) for name in names]
    return "; ".join(part for part in parts if part)


def _walk(element: ET.Element, prefix: list[str]) -> list[dict[str, Any]]:
    bindings = []
    for keybind in element.findall("o:keybind", NS):
        key = keybind.get("key", "")
        chain = [*prefix, key]
        actions = [
            {"name": action.get("name", ""), "options": _options(action)}
            for action in keybind.findall("o:action", NS)
        ]
        if actions:
            bindings.append(
                {
                    "key": " ".join(chain),
                    "send_key": [to_send_key(part) for part in chain],
                    "description": describe(actions),
                    "actions": actions,
                }
            )
        bindings.extend(_walk(keybind, chain))
    return bindings


def list_keybindings(path: str | None = None) -> dict[str, Any]:
    source = path or rc_path()
    root = ET.parse(source).getroot()
    keyboard = root.find("o:keyboard", NS)
    bindings = _walk(keyboard, []) if keyboard is not None else []
    return {"source": source, "keybindings": bindings, "count": len(bindings)}
