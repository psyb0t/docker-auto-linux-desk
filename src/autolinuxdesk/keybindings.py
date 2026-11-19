"""Window manager key bindings, read from the live Openbox config.

Reading rc.xml at request time keeps the list true to what is installed,
including bindings an image built on this one adds or removes.
"""

from __future__ import annotations

import json
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


def _keymap_descriptions(source: str) -> dict[str, dict[str, str]]:
    """Description and group per send_key, from the keymap.json that
    configure-openbox.py writes next to rc.xml. Empty when there is none,
    for example in an image that writes rc.xml another way."""
    path = os.path.join(os.path.dirname(source), "keymap.json")
    try:
        with open(path, encoding="utf-8") as handle:
            bindings = json.load(handle).get("bindings", [])
    except (OSError, ValueError):
        return {}
    return {
        "+".join(part.strip().lower() for part in binding.get("key", "").split("+")): {
            "description": binding.get("description", ""),
            "group": binding.get("group", ""),
        }
        for binding in bindings
    }


def _same_keys(send_key: str) -> str:
    """send_key with its modifiers in one order, so keymap and rc.xml match."""
    *mods, key = send_key.split("+")
    if key == "escape":
        key = "esc"
    order = ["ctrl", "alt", "shift", "win"]
    return "+".join(
        [*sorted(mods, key=lambda mod: order.index(mod) if mod in order else len(order)), key]
    )


def list_keybindings(path: str | None = None) -> dict[str, Any]:
    source = path or rc_path()
    root = ET.parse(source).getroot()
    keyboard = root.find("o:keyboard", NS)
    bindings = _walk(keyboard, []) if keyboard is not None else []
    named = {_same_keys(key): value for key, value in _keymap_descriptions(source).items()}
    for binding in bindings:
        found = (
            named.get(_same_keys(binding["send_key"][-1]))
            if len(binding["send_key"]) == 1
            else None
        )
        if found:
            binding["description"] = found["description"] or binding["description"]
            binding["group"] = found["group"]
    return {"source": source, "keybindings": bindings, "count": len(bindings)}
