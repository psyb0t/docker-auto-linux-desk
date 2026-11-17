"""Process-wide state and action dispatch."""

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass, field

from autolinuxdesk.clipboard import Clipboard
from autolinuxdesk.events import EventBus
from autolinuxdesk.logger import get_logger
from autolinuxdesk.processes import ProcessManager
from autolinuxdesk.recorder import Recorder
from autolinuxdesk.registry import Registry
from autolinuxdesk.responses import ActionError, fail
from autolinuxdesk.surface import Surface
from autolinuxdesk.system import System

log = get_logger(__name__)

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


def env_flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in _TRUE:
        return True
    if raw in _FALSE:
        return False
    raise ValueError(f"{name} must be true or false")


@dataclass(frozen=True)
class Settings:
    http_host: str = "0.0.0.0"
    http_port: int = 8080
    auth_token: str | None = None
    exec_enabled: bool = True
    plugins: str = ""

    @classmethod
    def from_environment(cls) -> Settings:
        return cls(
            http_host=os.environ.get("HTTP_LISTEN_HOST", "0.0.0.0"),
            http_port=int(os.environ.get("HTTP_LISTEN_PORT", "8080")),
            auth_token=os.environ.get("AUTH_TOKEN", "").strip() or None,
            exec_enabled=env_flag("DESK_EXEC_ENABLED", True),
            plugins=os.environ.get("AUTO_LINUX_DESK_PLUGINS", ""),
        )


@dataclass
class HandoffState:
    active: bool = False
    started_at: float | None = None


@dataclass
class Desk:
    registry: Registry
    settings: Settings = field(default_factory=Settings)
    system: System = field(default_factory=System)
    recorder: Recorder = field(default_factory=Recorder)
    clipboard: Clipboard = field(default_factory=Clipboard)
    events: EventBus = field(default_factory=EventBus)
    processes: ProcessManager = field(default_factory=ProcessManager)
    handoff: HandoffState = field(default_factory=HandoffState)
    # Serializes every action from HTTP and MCP, so only one drives the X server.
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    # Plugins keep their own state here.
    extensions: dict = field(default_factory=dict)

    @property
    def surface(self) -> Surface:
        return self.registry.surface

    async def dispatch(self, cmd: dict) -> dict:
        """Run one action and publish bounded failure metadata. Does not take the lock."""
        action = cmd.get("action", "")
        try:
            result = await self._dispatch_inner(cmd)
        except Exception as error:
            self.events.publish(
                "action_failure",
                {"action": action, "error_type": type(error).__name__},
            )
            raise
        if not result.get("success", False):
            self.events.publish("action_failure", {"action": action})
        return result

    async def _dispatch_inner(self, cmd: dict) -> dict:
        action = cmd.get("action", "")
        if not isinstance(action, str):
            return fail("action must be a string")
        entry = self.registry.actions.get(action)
        if entry is None:
            return fail(f"Unknown action: {action}")
        if self.handoff.active and not entry.handoff_safe:
            return fail("human handoff is active")
        try:
            return await entry.handler(cmd, self)
        except ActionError as error:
            return fail(str(error), error.data)

    async def run_hooks(self, hooks: list, label: str) -> None:
        for hook in hooks:
            started = time.monotonic()
            await hook(self)
            log.debug(
                "hook finished",
                extra={"hook": label, "duration": round(time.monotonic() - started, 3)},
            )
