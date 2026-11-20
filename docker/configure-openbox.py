"""Write the desktop user's Openbox rc.xml from the stock one and a key map.

Usage:
  python3 configure-openbox.py [--theme NAME] <stock rc.xml> <keymap.json> <output rc.xml>
  python3 configure-openbox.py --markdown <keymap.json>

- One desktop. Openbox defaults to four, and wheel input over an uncovered
  screen edge otherwise switches desktops.
- The keyboard section is replaced whole by the key map: every stock key
  binding is dropped and each map entry becomes one binding, so the map is
  the complete list of what the desktop's keys do. The map is copied next to
  the output as keymap.json, where desktop_keybindings reads the
  descriptions.
- --theme sets the Openbox theme (title bars and menus) by the name of a
  directory under /usr/share/themes; without it the stock theme stays.
- --markdown prints the key map as the table docs/keyboard.md carries.

The entrypoint runs this again at start when KEYBINDINGS_FILE names another
map or DESK_DARK_MODE picks the dark theme, and desktop_keybindings reads the
result back at runtime.
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

NS = "http://openbox.org/3.4/rc"
ET.register_namespace("", NS)

# send_key names -> X keysym names Openbox expects.
MODIFIERS = {"ctrl": "C", "alt": "A", "shift": "S", "win": "W"}
MODIFIER_ORDER = ["ctrl", "alt", "shift", "win"]
KEYS = {
    "left": "Left",
    "right": "Right",
    "up": "Up",
    "down": "Down",
    "enter": "Return",
    "escape": "Escape",
    "esc": "Escape",
    "tab": "Tab",
    "space": "space",
    "backspace": "BackSpace",
    "delete": "Delete",
    "home": "Home",
    "end": "End",
    "pageup": "Prior",
    "pagedown": "Next",
    "printscreen": "Print",
}
XML_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]*\Z")


def q(tag: str) -> str:
    return f"{{{NS}}}{tag}"


def openbox_key(send_key: str) -> str:
    """send_key notation (ctrl+alt+shift+left) to Openbox notation (C-A-S-Left)."""
    if not isinstance(send_key, str):
        raise SystemExit("every binding key must be a string")
    parts = [part.strip().lower() for part in send_key.split("+")]
    *mods, key = parts
    unknown = [mod for mod in mods if mod not in MODIFIERS]
    if unknown or not key or len(set(mods)) != len(mods):
        raise SystemExit(f"bad key {send_key!r}: modifiers must be {MODIFIER_ORDER}")
    mods.sort(key=MODIFIER_ORDER.index)
    name = KEYS.get(key) or (
        key.upper() if len(key) > 1 and key[0] == "f" and key[1:].isdigit() else key
    )
    return "-".join([*(MODIFIERS[mod] for mod in mods), name])


def load_keymap(path: str) -> list[dict]:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise SystemExit(f"cannot read key map: {error}") from error
    if not isinstance(data, dict) or not isinstance(data.get("bindings"), list):
        raise SystemExit("key map must be an object with a bindings list")
    bindings = data["bindings"]
    seen: set[str] = set()
    for binding in bindings:
        if not isinstance(binding, dict):
            raise SystemExit("every binding must be an object")
        key = openbox_key(binding.get("key"))
        if key in seen:
            raise SystemExit(f"key bound twice: {binding['key']}")
        seen.add(key)
        description = binding.get("description")
        actions = binding.get("actions")
        if (
            not isinstance(description, str)
            or not description.strip()
            or not isinstance(actions, list)
            or not actions
        ):
            raise SystemExit(f"{binding['key']}: every binding needs a description and actions")
        if not isinstance(binding.get("group", ""), str):
            raise SystemExit(f"{binding['key']}: group must be a string")
        for action in actions:
            if (
                not isinstance(action, dict)
                or not isinstance(action.get("name"), str)
                or not action["name"].strip()
            ):
                raise SystemExit(f"{binding['key']}: every action needs a name")
            options = action.get("options", {})
            if not isinstance(options, dict):
                raise SystemExit(f"{binding['key']}: action options must be an object")
            if any(
                not XML_NAME.fullmatch(name) or not isinstance(value, str)
                for name, value in options.items()
            ):
                raise SystemExit(f"{binding['key']}: options need XML names and string values")
    return bindings


def write_rc(source: str, keymap: str, target: str, theme: str | None = None) -> None:
    bindings = load_keymap(keymap)
    tree = ET.parse(source)
    root = tree.getroot()

    if theme is not None:
        if not XML_NAME.fullmatch(theme):
            raise SystemExit(f"theme name is not valid: {theme!r}")
        name = root.find(f"{q('theme')}/{q('name')}")
        if name is None:
            raise SystemExit("rc.xml has no theme/name")
        name.text = theme

    number = root.find(f"{q('desktops')}/{q('number')}")
    if number is None:
        raise SystemExit("rc.xml has no desktops/number")
    number.text = "1"

    keyboard = root.find(q("keyboard"))
    if keyboard is None:
        raise SystemExit("rc.xml has no keyboard section")
    keyboard.clear()
    for binding in bindings:
        keybind = ET.SubElement(keyboard, q("keybind"), {"key": openbox_key(binding["key"])})
        for item in binding["actions"]:
            action = ET.SubElement(keybind, q("action"), {"name": item["name"]})
            for option, value in (item.get("options") or {}).items():
                ET.SubElement(action, q(option)).text = value

    tree.write(target, encoding="utf-8", xml_declaration=True)
    copy = Path(target).with_name("keymap.json")
    if Path(keymap).resolve() != copy.resolve():
        shutil.copyfile(keymap, copy)


def markdown(keymap: str) -> str:
    rows = ["| `send_key` | Group | Does |", "| --- | --- | --- |"]
    for binding in load_keymap(keymap):
        description = binding["description"][0].upper() + binding["description"][1:]
        rows.append(f"| `{binding['key']}` | {binding.get('group', '')} | {description} |")
    return "\n".join(rows) + "\n"


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--markdown":
        sys.stdout.write(markdown(sys.argv[2]))
    elif len(sys.argv) == 4:
        write_rc(*sys.argv[1:])
    elif len(sys.argv) == 6 and sys.argv[1] == "--theme":
        write_rc(*sys.argv[3:], theme=sys.argv[2])
    else:
        raise SystemExit(__doc__)
