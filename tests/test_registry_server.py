"""Unit tests for the registry, plugin loading, dispatch and the HTTP server."""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "tests" / "apps"))

from fastapi.testclient import TestClient  # noqa: E402

from autolinuxdesk import actions, server  # noqa: E402
from autolinuxdesk.desk import Desk, Settings, env_flag  # noqa: E402
from autolinuxdesk.registry import (  # noqa: E402
    MCP_MODE_SCRIPT_ONLY,
    PluginError,
    Registry,
    RegistryError,
)
from autolinuxdesk.responses import ok  # noqa: E402

_TOKEN = "unit-test-token-not-a-secret"


async def _noop(cmd: dict, desk: Desk) -> dict:
    return ok({"ran": True})


def _expect(error_type: type[Exception], fn: object, *args: object) -> str:
    try:
        fn(*args)
    except error_type as error:
        return str(error)
    raise AssertionError(f"expected {error_type.__name__}")


def test_duplicate_action_is_refused_unless_replaced() -> None:
    registry = Registry()
    registry.register_action("x", _noop)
    assert "already registered" in _expect(RegistryError, registry.register_action, "x", _noop)
    registry.register_action("x", _noop, handoff_safe=True, replace=True)
    assert registry.actions["x"].handoff_safe
    registry.remove_action("x")
    assert "x" not in registry.actions


def test_duplicate_mcp_tool_is_refused_and_script_only_mode_filters() -> None:
    registry = Registry()

    async def run_script() -> str:
        return ""

    async def other() -> str:
        return ""

    registry.register_mcp_tool(run_script)
    registry.register_mcp_tool(other)
    _expect(RegistryError, registry.register_mcp_tool, other)
    assert set(registry.active_mcp_tools()) == {"run_script", "other"}
    registry.set_mcp_mode(MCP_MODE_SCRIPT_ONLY)
    assert set(registry.active_mcp_tools()) == {"run_script"}
    _expect(RegistryError, registry.set_mcp_mode, "bogus")


def test_plugin_failures_stop_loading_with_a_clear_error() -> None:
    registry = Registry()
    assert "failed to import" in _expect(
        PluginError, registry.load_plugins, "no_such_plugin_module"
    )
    assert "failed to register" in _expect(PluginError, registry.load_plugins, "broken_plugin")
    assert "has no register" in _expect(PluginError, registry.load_plugins, "json")
    registry.load_plugins(" , ")
    assert registry.plugins == []


def test_env_flag() -> None:
    import os

    os.environ["ALD_TEST_FLAG"] = "off"
    assert env_flag("ALD_TEST_FLAG", True) is False
    os.environ["ALD_TEST_FLAG"] = "YES"
    assert env_flag("ALD_TEST_FLAG", False) is True
    os.environ["ALD_TEST_FLAG"] = ""
    assert env_flag("ALD_TEST_FLAG", True) is True
    os.environ["ALD_TEST_FLAG"] = "maybe"
    _expect(ValueError, env_flag, "ALD_TEST_FLAG", True)
    del os.environ["ALD_TEST_FLAG"]


def _desk(**settings: object) -> Desk:
    return server.build_desk(Settings(**settings))


def test_dispatch_unknown_action_handoff_gate_and_failure_events() -> None:
    desk = _desk()

    async def scenario() -> None:
        result = await desk.dispatch({"action": "nope"})
        assert result["error"] == "Unknown action: nope"
        assert desk.events.get()[-1]["type"] == "action_failure"
        assert (await desk.dispatch({"action": "begin_handoff"}))["success"]
        blocked = await desk.dispatch({"action": "run_command", "command": "true"})
        assert blocked["error"] == "human handoff is active"
        assert (await desk.dispatch({"action": "ping"}))["success"]
        ended = await desk.dispatch({"action": "end_handoff"})
        assert ended["success"] and ended["data"]["activity"] is None
        assert (await desk.dispatch({"action": 5}))["error"] == "action must be a string"

    asyncio.run(scenario())


def test_exec_switch_refuses_run_command_and_launch_app() -> None:
    desk = _desk(exec_enabled=False)

    async def scenario() -> None:
        for cmd in (
            {"action": "run_command", "command": "true"},
            {"action": "launch_app", "command": ["true"]},
        ):
            result = await desk.dispatch(cmd)
            assert result["error"] == actions.EXEC_DISABLED_ERROR, result

    asyncio.run(scenario())


def test_run_script_dispatches_registered_actions() -> None:
    desk = _desk()
    result = asyncio.run(
        desk.dispatch(
            {
                "action": "run_script",
                "steps": [
                    {"action": "run_command", "command": "echo hi", "output_id": "out"},
                    {
                        "if": {
                            "condition": {
                                "type": "output",
                                "output_id": "out",
                                "path": ["exit_code"],
                                "equals": 0,
                            },
                            "then": [{"action": "sleep", "duration": 0}],
                        }
                    },
                ],
            }
        )
    )
    assert result["success"], result
    assert result["data"]["outputs"]["out"]["stdout"] == "hi\n"


def test_http_auth_and_plugin_surface() -> None:
    desk = _desk(auth_token=_TOKEN, plugins="sample_plugin")
    client = TestClient(server.build_app(desk))
    assert client.get("/health").text == "ok"
    assert client.post("/", json={"action": "ping"}).status_code == 401
    assert client.get(f"/state?auth_token={_TOKEN}").status_code == 401
    headers = {"Authorization": f"Bearer {_TOKEN}"}
    response = client.post("/", json={"action": "ping"}, headers=headers)
    assert response.json()["data"] == {"message": "pong", "plugin": True}
    assert response.headers["X-Request-Id"]
    echoed = client.post("/", json={"action": "sample_echo", "value": 7}, headers=headers)
    assert echoed.json()["data"] == {"echo": 7}
    state = client.get("/state", headers=headers).json()
    assert state["sample"] == "on" and state["plugins"] == ["sample_plugin"]
    assert client.get("/screenshot/sample", headers=headers).content == b"\x89PNG-sample"
    assert client.get("/screenshot/nope", headers=headers).status_code == 404
    assert client.get("/sample/hello", headers=headers).text == "hello from plugin"
    assert "sample_tool" in desk.registry.mcp_tools
    bad = client.post("/", content="{", headers=headers).json()
    assert bad["success"] is False and bad["error"].startswith("Invalid JSON")
    assert client.post("/", json=[1], headers=headers).json()["success"] is False


def test_request_guard_health_check_and_state_merge() -> None:
    desk = _desk()
    desk.registry.register_request_guard(
        lambda action, cmd: "only ping" if action != "ping" else None
    )

    async def failing(desk: Desk) -> dict:
        return {"ok": False, "component": "sample"}

    desk.registry.register_health(failing)
    client = TestClient(server.build_app(desk))
    assert client.post("/", json={"action": "sleep"}).json()["error"] == "only ping"
    assert client.post("/", json={"action": "ping"}).json()["success"]
    health = client.get("/health")
    assert health.status_code == 503
    assert json.loads(health.text)["failures"] == [{"ok": False, "component": "sample"}]


def test_script_path_from_argv() -> None:
    assert server.script_path_from_argv(["--script", "/tmp/x.yaml"]) == "/tmp/x.yaml"
    assert server.script_path_from_argv([]) is None


def main() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
    print(json.dumps({"result": "registry and server tests passed", "tests": len(tests)}))


if __name__ == "__main__":
    main()
