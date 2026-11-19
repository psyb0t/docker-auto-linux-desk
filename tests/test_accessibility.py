"""Unit tests for the AT-SPI2 accessibility reader that need no bus."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from unittest.mock import Mock, patch

from jeepney import HeaderFields, new_error, new_method_return

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autolinuxdesk import accessibility, actions  # noqa: E402
from autolinuxdesk.desk import Desk  # noqa: E402
from autolinuxdesk.registry import Registry  # noqa: E402


def test_state_bits_decode_to_atspi_names() -> None:
    focused = accessibility.STATES.index("focused")
    showing = accessibility.STATES.index("showing")
    checkable = accessibility.STATES.index("checkable")
    words = [(1 << focused) | (1 << showing), 1 << (checkable - 32)]
    assert accessibility.decode_states(words) == ["focused", "showing", "checkable"]
    assert accessibility.decode_states([0, 0]) == []


def test_ids_round_trip_and_bad_ids_are_refused() -> None:
    ref = (":1.42", "/org/a11y/atspi/accessible/7")
    assert accessibility.parse_id(accessibility.node_id(ref)) == ref
    for bad in ("", "no-path", ":1.2", "bad:/x", ":1.2:/bad-path", ":1.2:/x/", None, 3):
        try:
            accessibility.parse_id(bad)
        except accessibility.AccessibilityError:
            continue
        raise AssertionError(bad)


def _bus(nodes: dict) -> Mock:
    """Reply to actual D-Bus messages without a running desktop."""
    conn = Mock()

    def reply(message, *, timeout):
        assert timeout == accessibility.CALL_TIMEOUT_S
        fields = message.header.fields
        node = nodes[fields[HeaderFields.path]]
        method = fields[HeaderFields.member]
        signatures = {
            "Get": "ss",
            "GetExtents": "u",
            "GetText": "ii",
            "DoAction": "i",
            "SetTextContents": "s",
        }
        assert fields.get(HeaderFields.signature) == signatures.get(method)
        if method == "Get":
            _interface, name = message.body
            values = {
                "Name": ("s", node.get("name", "")),
                "Description": ("s", ""),
                "ChildCount": ("i", len(node.get("children", []))),
                "CharacterCount": ("i", len(node.get("text", ""))),
                "CurrentValue": ("d", 0.5),
            }
            return new_method_return(message, "v", (values[name],))
        if method == "GetText":
            return new_method_return(message, "s", (node["text"][: message.body[1]],))
        values = {
            "GetChildren": ("a(so)", node.get("children", [])),
            "GetRoleName": ("s", node.get("role", "application")),
            "GetState": ("au", [1 << 25, 0]),
            "GetInterfaces": ("as", node.get("interfaces", [])),
            "GetExtents": ("(iiii)", (10, 20, 100, 30)),
            "GetActions": ("a(sss)", [("Click", "Clicks", "")]),
            "DoAction": ("b", True),
            "SetTextContents": ("b", True),
            "GrabFocus": ("b", True),
        }
        signature, value = values[method]
        return new_method_return(message, signature, (value,))

    conn.send_and_get_reply.side_effect = reply
    return conn


def test_walk_handles_cycles_and_reports_only_real_node_limit_cuts() -> None:
    root = (":1.2", "/root")
    child = (":1.2", "/child")
    nodes = {
        "/root": {"children": [child]},
        "/child": {"children": [root]},
        accessibility.REGISTRY[1]: {"children": [root]},
    }
    conn = _bus(nodes)
    with patch.object(accessibility, "_connect", return_value=conn):
        with accessibility.Tree() as tree:
            found, cut = tree.walk(root, max_depth=30, max_nodes=2, showing_only=True)
            assert [node["id"] for node in found] == [
                accessibility.node_id(root),
                accessibility.node_id(child),
            ]
            assert not cut
            found, cut = tree.walk(root, max_depth=30, max_nodes=1, showing_only=True)
            assert len(found) == 1
            assert cut
        result = accessibility.dump(max_nodes=2)
    assert result["count"] == 2
    assert not result["truncated"]
    assert conn.close.called


def test_describe_reads_supported_interfaces_and_bounds() -> None:
    conn = _bus(
        {
            "/field": {
                "name": "Input",
                "role": "text",
                "text": "x" * (accessibility.TEXT_LIMIT + 1),
                "interfaces": [
                    accessibility.ATSPI + name
                    for name in ("Component", "Action", "Text", "EditableText", "Value")
                ],
            }
        }
    )
    with patch.object(accessibility, "_connect", return_value=conn):
        with accessibility.Tree() as tree:
            node = tree.describe((":1.2", "/field"))
    assert node["name"] == "Input"
    assert node["bounds"] == {"x": 10, "y": 20, "w": 100, "h": 30}
    assert node["text"] == "x" * accessibility.TEXT_LIMIT
    assert node["actions"] == ["Click"]
    assert node["editable"] is True
    assert node["value"] == 0.5


def test_disconnected_bus_calls_raise_accessibility_errors() -> None:
    conn = Mock()
    conn.send_and_get_reply.side_effect = ConnectionResetError("closed")
    with patch.object(accessibility, "_connect", return_value=conn):
        with accessibility.Tree() as tree:
            for operation in (
                lambda: tree.call((":1.2", "/field"), "Accessible", "GetState"),
                lambda: tree.prop((":1.2", "/field"), "Accessible", "Name"),
            ):
                try:
                    operation()
                except accessibility.AccessibilityError:
                    continue
                raise AssertionError("bus failure escaped")


def test_connect_checks_enable_reply_and_closes_session_on_failure() -> None:
    session = Mock()
    session.send_and_get_reply.side_effect = lambda message, **_kwargs: new_error(
        message, "org.freedesktop.DBus.Error.AccessDenied", "s", ("refused",)
    )
    with patch.object(accessibility, "open_dbus_connection", return_value=session):
        try:
            accessibility._connect()
        except accessibility.AccessibilityError as error:
            assert "no accessibility bus" in str(error)
        else:
            raise AssertionError("enabling accessibility failed silently")
    session.close.assert_called_once()
    assert session.send_and_get_reply.call_count == 1


def test_act_accepts_empty_text_and_zero_index_and_requires_one_operation() -> None:
    conn = _bus({"/field": {}})
    with patch.object(accessibility, "_connect", return_value=conn):
        assert accessibility.act(":1.2:/field", action=0)["action"] == "Click"
        assert conn.send_and_get_reply.call_args.args[0].body == (0,)
        assert accessibility.act(":1.2:/field", set_text="")["text_set"]
        assert conn.send_and_get_reply.call_args.args[0].body == ("",)
        assert accessibility.act(":1.2:/field", focus=True)["focused"]
        for kwargs in ({}, {"action": 0, "set_text": ""}, {"set_text": "", "focus": True}):
            try:
                accessibility.act(":1.2:/field", **kwargs)
            except accessibility.AccessibilityError:
                continue
            raise AssertionError(kwargs)


def test_act_rejects_unknown_names_and_out_of_range_indices() -> None:
    conn = _bus({"/button": {}})
    with patch.object(accessibility, "_connect", return_value=conn):
        for action in ("Missing", -1, 1):
            try:
                accessibility.act(":1.2:/button", action=action)
            except accessibility.AccessibilityError:
                continue
            raise AssertionError(action)
    assert all(
        call.args[0].header.fields[HeaderFields.member] == "GetActions"
        for call in conn.send_and_get_reply.call_args_list
    )


def test_set_text_rejects_invalid_dbus_strings_before_connecting() -> None:
    with patch.object(
        accessibility, "_connect", side_effect=AssertionError("unexpected bus access")
    ):
        for text in ("before\x00after", "\ud800", "\udfff"):
            try:
                accessibility.act(":1.2:/field", set_text=text)
            except accessibility.AccessibilityError as error:
                assert "set_text" in str(error)
                continue
            raise AssertionError("invalid D-Bus string accepted")

    conn = _bus({"/field": {}})
    text = "Caf\u00e9 \u65e5\u672c\u8a9e \U0001f642"
    with patch.object(accessibility, "_connect", return_value=conn):
        assert accessibility.act(":1.2:/field", set_text=text)["text_set"]
    assert conn.send_and_get_reply.call_args.args[0].body == (text,)


def test_matching_by_name_role_and_states() -> None:
    node = {
        "name": "Open Demo Account",
        "role": "push button",
        "states": ["enabled", "showing", "focusable"],
    }
    assert accessibility._matches(node, {"name": "demo"})
    assert not accessibility._matches(node, {"name": "demo", "exact": True})
    assert accessibility._matches(node, {"name": "open demo account", "exact": True})
    assert accessibility._matches(node, {"role": "push button", "states": ["enabled", "focusable"]})
    assert not accessibility._matches(node, {"role": "entry"})
    assert not accessibility._matches(node, {"states": ["checked"]})


def test_the_actions_refuse_bad_input_before_touching_the_bus() -> None:
    def run(handler, cmd: dict) -> dict:
        return asyncio.run(handler(cmd, None))

    assert not run(actions.desktop_accessibility_find, {})["success"]
    assert not run(actions.desktop_accessibility_action, {})["success"]
    assert not run(
        actions.desktop_accessibility_action, {"id": ":1.2:/x", "invoke": "Click", "focus": True}
    )["success"]
    assert not run(actions.desktop_accessibility_tree, {"max_depth": 0})["success"]
    assert not run(actions.desktop_accessibility_tree, {"max_nodes": "many"})["success"]
    # The request's own "action" key names the handler; it must not count as a choice.
    reply = run(
        actions.desktop_accessibility_action,
        {"action": "desktop_accessibility_action", "id": ":1.2:/x", "set_text": "x"},
    )
    assert "pass one of" not in (reply.get("error") or ""), reply


def test_handlers_reject_malformed_types_without_bus_access() -> None:
    tree_cases = ({"app": 3}, {"showing_only": "false"}, {"max_nodes": True}, {"max_depth": 1.5})
    find_cases = (
        {"name": 3},
        {"role": []},
        {"states": "showing"},
        {"states": [1]},
        {"name": "x", "exact": "false"},
        {"name": "x", "app": {}},
    )
    act_cases = (
        {},
        {"invoke": None},
        {"invoke": True},
        {"invoke": 1.5},
        {"invoke": []},
        {"set_text": 3},
        {"set_text": False},
        {"focus": "true"},
        {"focus": False},
        {"invoke": 0, "set_text": ""},
    )
    with patch.object(
        accessibility, "_connect", side_effect=AssertionError("unexpected bus access")
    ):
        for handler, cases in (
            (actions.desktop_accessibility_tree, tree_cases),
            (actions.desktop_accessibility_find, find_cases),
            (
                actions.desktop_accessibility_action,
                ({"id": ":1.2:/field", **case} for case in act_cases),
            ),
        ):
            for cmd in cases:
                reply = asyncio.run(handler(cmd, None))
                assert reply["success"] is False, (cmd, reply)


def test_action_handler_accepts_zero_index_and_empty_text() -> None:
    with patch.object(accessibility, "act", return_value={"done": True}) as act:
        for operation in ({"invoke": 0}, {"set_text": ""}, {"focus": True}):
            reply = asyncio.run(
                actions.desktop_accessibility_action(
                    {"action": "desktop_accessibility_action", "id": ":1.2:/field", **operation},
                    None,
                )
            )
            assert reply["success"], reply
        assert act.call_count == 3


def test_reads_run_during_a_handoff_and_the_action_does_not() -> None:
    async def check() -> None:
        registry = Registry()
        actions.register(registry)
        desk = Desk(registry)
        assert (await desk.dispatch({"action": "begin_handoff"}))["success"]
        tree_data = {"apps": [], "nodes": [], "count": 0, "truncated": False}
        find_data = {"matches": [], "count": 0, "truncated": False}
        with (
            patch.object(accessibility, "dump", return_value=tree_data) as dump,
            patch.object(accessibility, "find", return_value=find_data) as find,
            patch.object(accessibility, "act") as act,
        ):
            reply = await desk.dispatch({"action": "desktop_accessibility_tree"})
            assert reply["success"] and reply["data"] == tree_data
            reply = await desk.dispatch({"action": "desktop_accessibility_find", "name": "OK"})
            assert reply["success"] and reply["data"] == find_data
            reply = await desk.dispatch(
                {"action": "desktop_accessibility_action", "id": ":1.2:/field", "focus": True}
            )
            assert reply["success"] is False
            assert reply["error"] == "human handoff is active"
            dump.assert_called_once()
            find.assert_called_once()
            act.assert_not_called()

    asyncio.run(check())


def main() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
    print(json.dumps({"result": "accessibility tests passed", "tests": len(tests)}))


if __name__ == "__main__":
    main()
