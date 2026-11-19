"""The accessibility tree of the desktop's apps, read over AT-SPI2.

AT-SPI2 is the D-Bus protocol Linux screen readers use. Supporting apps expose
objects with roles, names, states and optional component, text and action
interfaces. Coverage depends on the app and toolkit. This module talks to
that bus directly with jeepney, so it needs no GObject bindings.

The objects live on a separate accessibility bus whose address the session
bus hands out (org.a11y.Bus.GetAddress). Setting org.a11y.Status.IsEnabled
announces that accessibility support is enabled.

Content without accessible objects still needs screenshots and input.

Interfaces and constants follow at-spi2-core's xml/*.xml and
atspi/atspi-constants.h.
"""

from __future__ import annotations

import logging
from typing import Any

from jeepney import DBusAddress, new_method_call
from jeepney.io.blocking import DBusConnection, open_dbus_connection
from jeepney.wrappers import DBusErrorResponse, Properties, unwrap_msg

logger = logging.getLogger(__name__)

ATSPI = "org.a11y.atspi."
REGISTRY = ("org.a11y.atspi.Registry", "/org/a11y/atspi/accessible/root")
A11Y_BUS = DBusAddress("/org/a11y/bus", bus_name="org.a11y.Bus", interface="org.a11y.Bus")
A11Y_STATUS = DBusAddress("/org/a11y/bus", bus_name="org.a11y.Bus", interface="org.a11y.Status")
NULL_PATH = "/org/a11y/atspi/null"
COORD_SCREEN = 0  # ATSPI_COORD_TYPE_SCREEN
CALL_TIMEOUT_S = 3.0
# AtspiStateType in order; bit N of GetState's two 32-bit words is state N.
STATES = (
    "invalid",
    "active",
    "armed",
    "busy",
    "checked",
    "collapsed",
    "defunct",
    "editable",
    "enabled",
    "expandable",
    "expanded",
    "focusable",
    "focused",
    "has_tooltip",
    "horizontal",
    "iconified",
    "modal",
    "multi_line",
    "multiselectable",
    "opaque",
    "pressed",
    "resizable",
    "selectable",
    "selected",
    "sensitive",
    "showing",
    "single_line",
    "stale",
    "transient",
    "vertical",
    "visible",
    "manages_descendants",
    "indeterminate",
    "required",
    "truncated",
    "animated",
    "invalid_entry",
    "supports_autocompletion",
    "selectable_text",
    "is_default",
    "visited",
    "checkable",
    "has_popup",
    "read_only",
)
DEFAULT_MAX_DEPTH = 30
DEFAULT_MAX_NODES = 3000
TEXT_LIMIT = 2000


class AccessibilityError(Exception):
    """The accessibility bus could not be reached, or a call on it failed."""


def _connect() -> DBusConnection:
    try:
        session = open_dbus_connection("SESSION")
    except (DBusErrorResponse, OSError, KeyError, ValueError) as err:
        raise AccessibilityError(f"no session bus: {err}") from err
    try:
        unwrap_msg(
            session.send_and_get_reply(
                Properties(A11Y_STATUS).set("IsEnabled", "b", True), timeout=CALL_TIMEOUT_S
            )
        )
        (address,) = unwrap_msg(
            session.send_and_get_reply(
                new_method_call(A11Y_BUS, "GetAddress"), timeout=CALL_TIMEOUT_S
            )
        )
    except (DBusErrorResponse, TimeoutError, OSError) as err:
        raise AccessibilityError(f"no accessibility bus: {err}") from err
    finally:
        session.close()
    try:
        return open_dbus_connection(address)
    except (DBusErrorResponse, OSError, ValueError) as err:
        raise AccessibilityError(f"cannot open the accessibility bus: {err}") from err


def node_id(ref: tuple[str, str]) -> str:
    return f"{ref[0]}:{ref[1]}"


def parse_id(value: str) -> tuple[str, str]:
    if not isinstance(value, str):
        raise AccessibilityError("accessibility id must be a string")
    bus, sep, path = value.partition(":/")
    if not sep or not bus:
        raise AccessibilityError(f"bad accessibility id {value!r}: expected bus:/path")
    try:
        DBusAddress("/" + path, bus_name=bus)
    except ValueError as err:
        raise AccessibilityError(f"bad accessibility id {value!r}: {err}") from err
    return bus, "/" + path


def decode_states(words: list[int]) -> list[str]:
    states = []
    for word_index, word in enumerate(words[:2]):
        for bit in range(32):
            index = word_index * 32 + bit
            if word & (1 << bit) and index < len(STATES):
                states.append(STATES[index])
    return states


class Tree:
    """One connection to the accessibility bus. Use as a context manager."""

    def __init__(self) -> None:
        self.conn = _connect()

    def __enter__(self) -> Tree:
        return self

    def __exit__(self, *_exc: object) -> None:
        self.conn.close()

    def call(
        self,
        ref: tuple[str, str],
        interface: str,
        method: str,
        signature: str | None = None,
        body: tuple = (),
    ) -> tuple:
        address = DBusAddress(ref[1], bus_name=ref[0], interface=ATSPI + interface)
        try:
            return unwrap_msg(
                self.conn.send_and_get_reply(
                    new_method_call(address, method, signature, body), timeout=CALL_TIMEOUT_S
                )
            )
        except (DBusErrorResponse, OSError) as err:
            raise AccessibilityError(
                f"{interface}.{method} on {node_id(ref)} failed: {err}"
            ) from err

    def prop(self, ref: tuple[str, str], interface: str, name: str) -> Any:
        address = DBusAddress(ref[1], bus_name=ref[0], interface=ATSPI + interface)
        try:
            (value,) = unwrap_msg(
                self.conn.send_and_get_reply(Properties(address).get(name), timeout=CALL_TIMEOUT_S)
            )
        except (DBusErrorResponse, OSError) as err:
            raise AccessibilityError(f"{interface}.{name} on {node_id(ref)} failed: {err}") from err
        return value[1]

    def children(self, ref: tuple[str, str]) -> list[tuple[str, str]]:
        (kids,) = self.call(ref, "Accessible", "GetChildren")
        return [tuple(kid) for kid in kids if kid[1] != NULL_PATH]

    def apps(self) -> list[dict[str, Any]]:
        found = []
        for ref in self.children(REGISTRY):
            try:
                found.append(
                    {
                        "id": node_id(ref),
                        "name": self.prop(ref, "Accessible", "Name"),
                        "children": self.prop(ref, "Accessible", "ChildCount"),
                    }
                )
            except AccessibilityError:
                logger.debug("accessible application disappeared", extra={"node_id": node_id(ref)})
                continue
        return found

    def describe(self, ref: tuple[str, str]) -> dict[str, Any]:
        """Everything about one object that is cheap to read."""
        (role,) = self.call(ref, "Accessible", "GetRoleName")
        (states,) = self.call(ref, "Accessible", "GetState")
        (interfaces,) = self.call(ref, "Accessible", "GetInterfaces")
        node: dict[str, Any] = {
            "id": node_id(ref),
            "role": role,
            "name": self.prop(ref, "Accessible", "Name"),
            "states": decode_states(states),
        }
        description = self.prop(ref, "Accessible", "Description")
        if description:
            node["description"] = description
        if ATSPI + "Component" in interfaces:
            ((x, y, w, h),) = self.call(ref, "Component", "GetExtents", "u", (COORD_SCREEN,))
            node["bounds"] = {"x": x, "y": y, "w": w, "h": h}
        if ATSPI + "Action" in interfaces:
            (actions,) = self.call(ref, "Action", "GetActions")
            node["actions"] = [name for name, _description, _keys in actions]
        if ATSPI + "Text" in interfaces:
            count = self.prop(ref, "Text", "CharacterCount")
            if count:
                (text,) = self.call(ref, "Text", "GetText", "ii", (0, min(count, TEXT_LIMIT)))
                node["text"] = text
        if ATSPI + "Value" in interfaces:
            node["value"] = self.prop(ref, "Value", "CurrentValue")
        if ATSPI + "EditableText" in interfaces:
            node["editable"] = True
        return node

    def walk(
        self, root: tuple[str, str], max_depth: int, max_nodes: int, showing_only: bool
    ) -> tuple[list[dict[str, Any]], bool]:
        """Depth-first list of nodes under root, each with its parent id and
        depth. Returns (nodes, truncated)."""
        nodes: list[dict[str, Any]] = []
        stack: list[tuple[tuple[str, str], str | None, int]] = [(root, None, 0)]
        seen: set[tuple[str, str]] = set()
        while stack:
            ref, parent, depth = stack.pop()
            if ref in seen:
                continue
            seen.add(ref)
            try:
                node = self.describe(ref)
            except AccessibilityError:
                logger.debug("accessible object disappeared", extra={"node_id": node_id(ref)})
                continue
            if showing_only and parent is not None and "showing" not in node["states"]:
                continue
            if len(nodes) >= max_nodes:
                return nodes, True
            node["parent"] = parent
            node["depth"] = depth
            nodes.append(node)
            if depth >= max_depth or "manages_descendants" in node["states"]:
                continue
            try:
                kids = self.children(ref)
            except AccessibilityError:
                logger.debug("accessible children disappeared", extra={"node_id": node_id(ref)})
                continue
            stack.extend((kid, node["id"], depth + 1) for kid in reversed(kids))
        return nodes, False


def _matches(node: dict[str, Any], query: dict[str, Any]) -> bool:
    name = query.get("name")
    if name is not None:
        have = (node.get("name") or "").lower()
        want = str(name).lower()
        if (have != want) if query.get("exact") else (want not in have):
            return False
    role = query.get("role")
    if role is not None and node.get("role") != role:
        return False
    states = query.get("states") or []
    return all(state in node.get("states", []) for state in states)


def _roots(tree: Tree, app: str | None) -> list[tuple[str, str]]:
    apps = tree.apps()
    if app is None:
        return [parse_id(item["id"]) for item in apps]
    chosen = [
        item for item in apps if app.lower() in (item["name"] or "").lower() or item["id"] == app
    ]
    if not chosen:
        raise AccessibilityError(
            f"no accessible app matches {app!r}; apps: {[item['name'] for item in apps]}"
        )
    return [parse_id(item["id"]) for item in chosen]


def dump(
    app: str | None = None,
    max_depth: int = DEFAULT_MAX_DEPTH,
    max_nodes: int = DEFAULT_MAX_NODES,
    showing_only: bool = True,
) -> dict[str, Any]:
    with Tree() as tree:
        nodes: list[dict[str, Any]] = []
        truncated = False
        for root in _roots(tree, app):
            found, cut = tree.walk(root, max_depth, max_nodes - len(nodes), showing_only)
            nodes.extend(found)
            truncated = truncated or cut
            if truncated:
                break
        return {"apps": tree.apps(), "nodes": nodes, "count": len(nodes), "truncated": truncated}


def find(query: dict[str, Any]) -> dict[str, Any]:
    tree = dump(
        query.get("app"),
        int(query.get("max_depth", DEFAULT_MAX_DEPTH)),
        int(query.get("max_nodes", DEFAULT_MAX_NODES)),
        bool(query.get("showing_only", True)),
    )
    matches = [node for node in tree["nodes"] if _matches(node, query)]
    return {"matches": matches, "count": len(matches), "truncated": tree["truncated"]}


def act(
    element_id: str,
    action: str | int | None = None,
    set_text: str | None = None,
    focus: bool = False,
) -> dict[str, Any]:
    """Run one thing on an element: a named or numbered AT-SPI action, grab
    focus, or replace an editable element's text."""
    if sum((action is not None, set_text is not None, focus)) != 1:
        raise AccessibilityError("pass exactly one of invoke, set_text or focus")
    if set_text is not None:
        if "\x00" in set_text:
            raise AccessibilityError("set_text must not contain NUL characters")
        try:
            set_text.encode("utf-8")
        except UnicodeEncodeError as err:
            raise AccessibilityError("set_text must be valid UTF-8 text") from err
    ref = parse_id(element_id)
    with Tree() as tree:
        if focus:
            (ok,) = tree.call(ref, "Component", "GrabFocus")
            return {"id": element_id, "focused": bool(ok)}
        if set_text is not None:
            (ok,) = tree.call(ref, "EditableText", "SetTextContents", "s", (set_text,))
            return {"id": element_id, "text_set": bool(ok)}
        (actions,) = tree.call(ref, "Action", "GetActions")
        names = [name for name, _description, _keys in actions]
        if isinstance(action, int):
            index = action
        elif action in names:
            index = names.index(action)
        else:
            raise AccessibilityError(f"{element_id} has no action {action!r}; it has {names}")
        if not 0 <= index < len(names):
            raise AccessibilityError(f"action index {index} out of range; {element_id} has {names}")
        (ok,) = tree.call(ref, "Action", "DoAction", "i", (index,))
        return {"id": element_id, "action": names[index], "done": bool(ok)}
