"""Plugin used by the unit and integration tests."""

from __future__ import annotations

from starlette.responses import PlainTextResponse

from autolinuxdesk.responses import ok


async def _echo(cmd: dict, desk: object) -> dict:
    return ok({"echo": cmd.get("value")})


async def _ping(cmd: dict, desk: object) -> dict:
    return ok({"message": "pong", "plugin": True})


async def _state(desk: object) -> dict:
    return {"sample": "on"}


async def _shot(desk: object, params: object) -> bytes:
    frames = params.getlist("frame")
    return b"\x89PNG-sample" + ",".join(frames).encode()


async def _hello() -> PlainTextResponse:
    return PlainTextResponse("hello from plugin")


def register(registry: object) -> None:
    registry.register_action("sample_echo", _echo)
    registry.register_action("ping", _ping, handoff_safe=True, replace=True)
    registry.register_state(_state)
    registry.register_screenshot("sample", _shot)
    registry.register_route("GET", "/sample/hello", _hello)

    async def sample_tool(value: str) -> str:
        """Echo a value through the sample plugin."""
        return str(await registry.call("sample_echo", value=value))

    registry.register_mcp_tool(sample_tool)
