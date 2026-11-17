"""Write the desktop user's Openbox rc.xml from the stock Debian one.

Usage: python3 configure-openbox.py <stock rc.xml> <output rc.xml>

- One desktop. Openbox defaults to four, and wheel input over an uncovered
  screen edge otherwise switches desktops.
- Drops key bindings that do nothing useful in this image: desktop
  switching (there is one desktop), a KDE file manager that is not
  installed, and screenshots written to the working directory.
- Adds bindings for a terminal, half-screen tiling and window states, so a
  controller can drive the desktop with the keyboard.

The desktop_keybindings action reads the result back at runtime.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET

NS = "http://openbox.org/3.4/rc"
ET.register_namespace("", NS)

DROP_ACTIONS = {"GoToDesktop", "SendToDesktop"}
DROP_KEYS = {"W-e", "Print", "A-Print"}

TERMINAL = "x-terminal-emulator"

# key -> list of (action name, {option: value})
ADD: dict[str, list[tuple[str, dict[str, str]]]] = {
    "C-A-t": [("Execute", {"command": TERMINAL})],
    "W-Return": [("Execute", {"command": TERMINAL})],
    "W-Left": [
        ("UnmaximizeFull", {}),
        ("MoveResizeTo", {"x": "0", "y": "0", "width": "50%", "height": "100%"}),
    ],
    "W-Right": [
        ("UnmaximizeFull", {}),
        ("MoveResizeTo", {"x": "50%", "y": "0", "width": "50%", "height": "100%"}),
    ],
    "W-Up": [("Maximize", {})],
    "W-Down": [("Unmaximize", {})],
    "W-f": [("ToggleFullscreen", {})],
    "W-h": [("Iconify", {})],
    "W-c": [("MoveResizeTo", {"x": "center", "y": "center"})],
}


def q(tag: str) -> str:
    return f"{{{NS}}}{tag}"


def keep(keybind: ET.Element) -> bool:
    if keybind.get("key") in DROP_KEYS:
        return False
    names = {action.get("name") for action in keybind.findall(q("action"))}
    return not names & DROP_ACTIONS


def main(source: str, target: str) -> None:
    tree = ET.parse(source)
    root = tree.getroot()

    number = root.find(f"{q('desktops')}/{q('number')}")
    if number is None:
        raise SystemExit("rc.xml has no desktops/number")
    number.text = "1"

    keyboard = root.find(q("keyboard"))
    if keyboard is None:
        raise SystemExit("rc.xml has no keyboard section")
    for keybind in keyboard.findall(q("keybind")):
        if not keep(keybind) or keybind.get("key") in ADD:
            keyboard.remove(keybind)
    for key, actions in ADD.items():
        keybind = ET.SubElement(keyboard, q("keybind"), {"key": key})
        for name, options in actions:
            action = ET.SubElement(keybind, q("action"), {"name": name})
            for option, value in options.items():
                ET.SubElement(action, q(option)).text = value

    tree.write(target, encoding="utf-8", xml_declaration=True)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
