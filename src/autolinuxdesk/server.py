"""HTTP API, MCP endpoint and script mode.

Endpoints:
    POST /                  - run one action, returns JSON
    GET  /screenshot/<name> - PNG; "desktop" is built in, plugins add more
    GET  /state             - JSON state, merged from plugins
    GET  /events            - server-sent events
    GET  /health            - "ok", or 503 when a plugin health check fails
    POST /mcp               - MCP Streamable HTTP
"""

from __future__ import annotations

import asyncio
import hmac
import json
import re
import sys
import uuid
from typing import Any

import uvicorn
from fastapi import FastAPI, Request
from fastmcp import FastMCP
from starlette.responses import JSONResponse, PlainTextResponse, Response, StreamingResponse

from autolinuxdesk import actions, mcp_tools
from autolinuxdesk.clipboard import redact_clipboard_params
from autolinuxdesk.desk import Desk, Settings
from autolinuxdesk.events import EventError
from autolinuxdesk.logger import (
    configure_output,
    get_logger,
    new_trace_id,
    request_id_var,
    trace_id_var,
)
from autolinuxdesk.recorder import cleanup_orphan_tmp_files
from autolinuxdesk.registry import Registry
from autolinuxdesk.responses import (
    BINARY_KEY,
    CONTENT_TYPE_IMAGE_PNG,
    ActionError,
    fail,
    make_response,
    resize_png,
)
from autolinuxdesk.script_runner import load_script, run_script

log = get_logger(__name__)

# X-Request-Id shape allowlist: it becomes a log field, so keep it short and plain.
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_UNAUTHORIZED = {"success": False, "error": "Unauthorized"}


def _safe_request_id(incoming: str) -> str:
    if incoming and _REQUEST_ID_RE.match(incoming):
        return incoming
    return uuid.uuid4().hex


def _log_request(action: str, params: dict) -> None:
    if params:
        log.info(
            "request",
            extra={"action": action, "params": redact_clipboard_params(action, params)},
        )
    else:
        log.info("request", extra={"action": action})


async def _desktop_screenshot(desk: Desk, params: dict) -> bytes:
    return resize_png(await actions.capture_desktop_png(), params)


def build_desk(settings: Settings | None = None) -> Desk:
    """Create the shared state, register the base and load plugins."""
    settings = settings or Settings.from_environment()
    registry = Registry()
    desk = Desk(registry, settings)
    registry.desk = desk
    registry.call = mcp_tools.make_caller(desk)
    actions.register(registry)
    mcp_tools.register(registry, desk)
    registry.register_screenshot("desktop", _desktop_screenshot)
    registry.load_plugins(settings.plugins)
    return desk


def build_mcp(registry: Registry) -> FastMCP:
    mcp = FastMCP(registry.mcp_name, instructions=registry.mcp_instructions)
    for name, fn in registry.active_mcp_tools().items():
        mcp.tool(fn, name=name)
    return mcp


def build_app(desk: Desk) -> FastAPI:  # noqa: C901 - route table
    registry = desk.registry
    settings = desk.settings
    mcp_app = build_mcp(registry).http_app(transport="streamable-http", path="/")
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=mcp_app.lifespan)

    @app.middleware("http")
    async def auth_middleware(request: Request, call_next: Any) -> Any:
        """Require the Bearer token on everything but /health when AUTH_TOKEN is set."""
        if settings.auth_token and request.url.path != "/health":
            if "auth_token" in request.query_params:
                return JSONResponse(_UNAUTHORIZED, status_code=401)
            auth = request.headers.get("Authorization", "")
            expected = f"Bearer {settings.auth_token}"
            if not hmac.compare_digest(auth.encode(), expected.encode()):
                return JSONResponse(_UNAUTHORIZED, status_code=401)
        return await call_next(request)

    # Starlette runs middlewares in reverse registration order, so this one
    # is outermost and even 401 responses carry trace and request IDs.
    @app.middleware("http")
    async def trace_middleware(request: Request, call_next: Any) -> Any:
        trace_id = new_trace_id()
        request_id = _safe_request_id(request.headers.get("X-Request-Id", ""))
        trace_token = trace_id_var.set(trace_id)
        rid_token = request_id_var.set(request_id)
        try:
            response = await call_next(request)
        finally:
            trace_id_var.reset(trace_token)
            request_id_var.reset(rid_token)
        response.headers["X-Request-Id"] = request_id
        response.headers["X-Trace-Id"] = trace_id
        return response

    @app.post("/")
    async def handle_command(request: Request) -> JSONResponse:
        try:
            cmd = await request.json()
        except Exception as error:
            log.error("invalid request JSON", extra={"error": str(error)})
            return JSONResponse(fail(f"Invalid JSON: {error}"))
        if not isinstance(cmd, dict):
            return JSONResponse(fail("request body must be a JSON object"))
        action = cmd.get("action", "")
        for guard in registry.request_guards:
            refusal = guard(action, cmd)
            if refusal:
                return JSONResponse(fail(refusal))
        _log_request(action, {key: value for key, value in cmd.items() if key != "action"})
        async with desk.lock:
            try:
                result = await desk.dispatch(cmd)
            except Exception as error:
                log.exception("action failed", extra={"action": action})
                return JSONResponse(fail(str(error)))
        result.pop(BINARY_KEY, None)
        return JSONResponse(result)

    @app.get("/screenshot/{name}")
    async def handle_screenshot(name: str, request: Request) -> Response:
        provider = registry.screenshots.get(name)
        if provider is None:
            return PlainTextResponse(f"unknown screenshot: {name}", status_code=404)
        try:
            data = await provider(desk, dict(request.query_params))
        except ActionError as error:
            return PlainTextResponse(str(error), status_code=400)
        except Exception as error:
            log.exception("screenshot failed", extra={"screenshot": name})
            return PlainTextResponse(str(error), status_code=500)
        return Response(content=data, media_type=CONTENT_TYPE_IMAGE_PNG)

    @app.get("/state")
    async def handle_state() -> JSONResponse:
        state: dict[str, Any] = {
            "status": "ready",
            "surface": desk.surface.describe(),
            "window_offset": desk.system.window_offset,
            "resolution": desk.system.get_resolution(),
            "handoff_active": desk.handoff.active,
            "plugins": registry.plugins,
        }
        for provider in registry.state_providers:
            state.update(await provider(desk))
        return JSONResponse(state)

    @app.get("/events")
    async def handle_events(request: Request) -> Response:
        """Stream process-local events as server-sent events."""
        try:
            after_id = int(request.query_params.get("after_id", "0"))
            event_types = set(request.query_params.getlist("type")) or None
            desk.events.get(after_id=after_id, event_types=event_types, limit=1)
        except (EventError, TypeError, ValueError) as error:
            return JSONResponse(make_response(False, error=str(error)), status_code=400)

        async def stream() -> Any:
            cursor = after_id
            while not await request.is_disconnected():
                events = await desk.events.wait(
                    after_id=cursor, event_types=event_types, timeout=15
                )
                if not events:
                    yield ": keepalive\n\n"
                    continue
                for event in events:
                    cursor = max(cursor, event["id"])
                    payload = json.dumps(event, separators=(",", ":"))
                    yield f"id: {event['id']}\nevent: {event['type']}\ndata: {payload}\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/health")
    async def handle_health() -> Response:
        failures = []
        for check in registry.health_checks:
            result = await check(desk)
            if not result.get("ok", False):
                failures.append(result)
        if failures:
            return JSONResponse({"ok": False, "failures": failures}, status_code=503)
        return PlainTextResponse("ok")

    for route in registry.routes:
        app.add_api_route(route.path, route.handler, methods=[route.method])

    app.mount("/mcp", mcp_app)
    return app


async def _start(desk: Desk) -> None:
    cleanup_orphan_tmp_files()
    desk.system.init()
    await desk.run_hooks(desk.registry.startup_hooks, "startup")


async def _stop(desk: Desk) -> None:
    desk.recorder.abort()
    desk.processes.shutdown()
    await desk.run_hooks(desk.registry.shutdown_hooks, "shutdown")


async def run_script_mode(desk: Desk, script_path: str) -> int:
    """Run a YAML script, print its JSON result to stdout and return the exit code."""
    real_stdout = sys.stdout
    # Library chatter and logs go to stderr so stdout stays one JSON document.
    sys.stdout = sys.stderr
    configure_output(sys.stderr)
    try:
        script_data = load_script(script_path)
    except Exception as error:
        log.info(f"Failed to load script: {error}")
        return 1
    await _start(desk)
    try:
        result = await run_script(script_data, desk.dispatch, real_stdout)
    finally:
        await _stop(desk)
    return 0 if result["success"] else 1


async def serve(desk: Desk) -> None:
    settings = desk.settings
    if settings.exec_enabled and not settings.auth_token:
        log.warning(
            "run_command and launch_app are enabled without AUTH_TOKEN; anyone who "
            "can reach the API port can run commands in this container"
        )
    await _start(desk)
    app = build_app(desk)
    server = uvicorn.Server(
        uvicorn.Config(
            app,
            host=settings.http_host,
            port=settings.http_port,
            log_level="warning",
            lifespan="on",
        )
    )
    if settings.auth_token:
        log.info("API key auth enabled")
    log.info(f"API listening on {settings.http_host}:{settings.http_port}")
    try:
        await server.serve()
    finally:
        await _stop(desk)


def script_path_from_argv(argv: list[str]) -> str | None:
    if len(argv) >= 2 and argv[0] == "--script":
        return argv[1]
    return None


def main(argv: list[str] | None = None) -> None:
    args = sys.argv[1:] if argv is None else argv
    desk = build_desk()
    script_path = script_path_from_argv(args)
    if script_path:
        sys.exit(asyncio.run(run_script_mode(desk, script_path)))
    asyncio.run(serve(desk))
    log.info("Done")
