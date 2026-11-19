"""What the server exposes: actions, MCP tools, routes, screenshots and hooks.

The base registers its own actions here, then each plugin named in
AUTO_LINUX_DESK_PLUGINS gets the same registry in its register() function
and can add to it or replace entries before the server starts.
"""

from __future__ import annotations

import importlib
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from autolinuxdesk.surface import Surface

if TYPE_CHECKING:
    from autolinuxdesk.desk import Desk

ActionHandler = Callable[[dict, "Desk"], Awaitable[dict]]
Hook = Callable[["Desk"], Awaitable[None]]
StateProvider = Callable[["Desk"], Awaitable[dict]]
ScreenshotProvider = Callable[["Desk", dict], Awaitable[bytes]]
HandoffActivity = Callable[["Desk", bool], Awaitable[dict | None]]
RequestGuard = Callable[[str, dict], str | None]

MCP_MODE_FULL = "full"
MCP_MODE_SCRIPT_ONLY = "script_only"
_MCP_MODES = (MCP_MODE_FULL, MCP_MODE_SCRIPT_ONLY)
_SCRIPT_ONLY_TOOLS = frozenset({"run_script"})

DEFAULT_MCP_NAME = "auto-linux-desk"
DEFAULT_MCP_INSTRUCTIONS = (
    "Linux desktop automation in Docker: a virtual X display with a window "
    "manager, humanized OS-level mouse and keyboard input, window control, "
    "app launching, shell commands, the clipboard, screenshots and screen "
    "recording. Coordinates are screen pixels from the top-left corner. "
    "SCREENSHOTS: pass whLargest=512 unless you need fine detail. "
    "Use desktop_list_windows to find windows and their geometry before "
    "clicking into them. KEYBOARD: the desktop has one complete key map for "
    "tiling to halves and quarters, maximize, fullscreen, minimize, close, "
    "focusing a window by app, number or direction, and opening a terminal; "
    "call desktop_keybindings once to get it, then press keys with send_key "
    "instead of moving windows through the API. No default binding uses the Super "
    "key. ACCESSIBILITY: desktop_accessibility_tree and "
    "desktop_accessibility_find list widgets exported by AT-SPI2-enabled "
    "apps with role, name, states and screen bounds, "
    "like uiautomator; use them to find a control before clicking its "
    "bounds. Use screenshots for apps or controls without accessibility support. "
    "TEXT INPUT: people paste far more than they type. Enter text with "
    "paste_text: it puts the text on the clipboard, clicks the field when "
    "given x and y, and presses ctrl+a, backspace and ctrl+v with human "
    "timing. Use system_type only for a few characters: a word, a short "
    "search, a small edit, a one-line command, or a field that blocks "
    "pasting. Never pass instant to send_key. "
    "Use run_script to execute multi-step workflows atomically."
)


class RegistryError(Exception):
    """A registration conflicted with an existing one or was invalid."""


class PluginError(Exception):
    """A plugin could not be imported or failed while registering."""


@dataclass(frozen=True)
class Action:
    name: str
    handler: ActionHandler
    # Allowed while a person has control during a handoff.
    handoff_safe: bool = False


@dataclass(frozen=True)
class Route:
    method: str
    path: str
    handler: Callable[..., Awaitable[Any]]


class Registry:
    def __init__(self) -> None:
        self.actions: dict[str, Action] = {}
        self.mcp_tools: dict[str, Callable[..., Any]] = {}
        self.mcp_name = DEFAULT_MCP_NAME
        self.mcp_instructions = DEFAULT_MCP_INSTRUCTIONS
        self.mcp_mode = MCP_MODE_FULL
        self.routes: list[Route] = []
        self.screenshots: dict[str, ScreenshotProvider] = {}
        self.state_providers: list[StateProvider] = []
        self.health_checks: list[StateProvider] = []
        self.startup_hooks: list[Hook] = []
        self.shutdown_hooks: list[Hook] = []
        self.request_guards: list[RequestGuard] = []
        self.surface: Surface = Surface()
        self.handoff_activity: HandoffActivity | None = None
        self.plugins: list[str] = []
        # Set by the server before plugins load. desk is the shared state;
        # call(action, **params) dispatches under the request lock, for
        # plugin MCP tools.
        self.desk: Desk | None = None
        self.call: Callable[..., Awaitable[dict]] | None = None

    # Actions

    def register_action(
        self,
        name: str,
        handler: ActionHandler,
        *,
        handoff_safe: bool = False,
        replace: bool = False,
    ) -> None:
        if not name or not isinstance(name, str):
            raise RegistryError("action name must be a non-empty string")
        if name in self.actions and not replace:
            raise RegistryError(f"action {name!r} is already registered")
        self.actions[name] = Action(name, handler, handoff_safe)

    def action(
        self, name: str, *, handoff_safe: bool = False, replace: bool = False
    ) -> Callable[[ActionHandler], ActionHandler]:
        """Decorator form of register_action."""

        def decorate(handler: ActionHandler) -> ActionHandler:
            self.register_action(name, handler, handoff_safe=handoff_safe, replace=replace)
            return handler

        return decorate

    def remove_action(self, name: str) -> None:
        self.actions.pop(name, None)

    # MCP

    def register_mcp_tool(
        self,
        fn: Callable[..., Any],
        *,
        name: str | None = None,
        replace: bool = False,
    ) -> None:
        tool_name = name or fn.__name__
        if tool_name in self.mcp_tools and not replace:
            raise RegistryError(f"MCP tool {tool_name!r} is already registered")
        self.mcp_tools[tool_name] = fn

    def mcp_tool(
        self, name: str | None = None, *, replace: bool = False
    ) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
        """Decorator form of register_mcp_tool."""

        def decorate(fn: Callable[..., Any]) -> Callable[..., Any]:
            self.register_mcp_tool(fn, name=name, replace=replace)
            return fn

        return decorate

    def remove_mcp_tool(self, name: str) -> None:
        self.mcp_tools.pop(name, None)

    def set_mcp_identity(self, name: str, instructions: str) -> None:
        self.mcp_name = name
        self.mcp_instructions = instructions

    def set_mcp_mode(self, mode: str) -> None:
        if mode not in _MCP_MODES:
            raise RegistryError(f"MCP mode must be one of {', '.join(_MCP_MODES)}")
        self.mcp_mode = mode

    def active_mcp_tools(self) -> dict[str, Callable[..., Any]]:
        if self.mcp_mode == MCP_MODE_SCRIPT_ONLY:
            return {name: fn for name, fn in self.mcp_tools.items() if name in _SCRIPT_ONLY_TOOLS}
        return dict(self.mcp_tools)

    # HTTP

    def register_route(
        self, method: str, path: str, handler: Callable[..., Awaitable[Any]]
    ) -> None:
        self.routes.append(Route(method.upper(), path, handler))

    def register_screenshot(
        self, name: str, provider: ScreenshotProvider, *, replace: bool = False
    ) -> None:
        """Serve GET /screenshot/<name> from provider(desk, query_params) -> PNG bytes.

        query_params is the request's Starlette QueryParams: get() for one value,
        getlist() for a repeated parameter.
        """
        if name in self.screenshots and not replace:
            raise RegistryError(f"screenshot {name!r} is already registered")
        self.screenshots[name] = provider

    def register_request_guard(self, guard: RequestGuard) -> None:
        """guard(action, cmd) returns an error to refuse a POST / request, or None."""
        self.request_guards.append(guard)

    # State, health and lifecycle

    def register_state(self, provider: StateProvider) -> None:
        """provider(desk) returns a dict merged into GET /state."""
        self.state_providers.append(provider)

    def register_health(self, check: StateProvider) -> None:
        """check(desk) returns {"ok": bool, ...}; any false makes /health 503."""
        self.health_checks.append(check)

    def on_startup(self, hook: Hook) -> None:
        self.startup_hooks.append(hook)

    def on_shutdown(self, hook: Hook) -> None:
        self.shutdown_hooks.append(hook)

    def set_surface(self, surface: Surface) -> None:
        self.surface = surface

    def set_handoff_activity(self, provider: HandoffActivity) -> None:
        """provider(desk, stop) counts human input during a handoff."""
        self.handoff_activity = provider

    # Plugins

    def load_plugins(self, spec: str) -> None:
        """Import each comma-separated module and call its register(registry)."""
        for module_name in (part.strip() for part in spec.split(",")):
            if not module_name:
                continue
            try:
                module = importlib.import_module(module_name)
            except Exception as error:
                raise PluginError(f"plugin {module_name!r} failed to import: {error}") from error
            register = getattr(module, "register", None)
            if not callable(register):
                raise PluginError(f"plugin {module_name!r} has no register(registry)")
            try:
                register(self)
            except Exception as error:
                raise PluginError(f"plugin {module_name!r} failed to register: {error}") from error
            self.plugins.append(module_name)
