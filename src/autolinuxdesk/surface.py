"""The coordinate space that humanized input targets.

Input actions take coordinates relative to the active surface. The default
surface is the whole X screen, so its origin is the screen's top-left corner.
A plugin can install a surface whose origin is somewhere else, such as a
browser viewport, and teach it to report scroll position and focused fields.
"""

from __future__ import annotations

from typing import Any, Protocol

from autolinuxdesk.system import System


class TypoGuard(Protocol):
    """Decides whether typing typos is safe and checks the result afterwards."""

    reason: str | None

    @property
    def is_allowed(self) -> bool: ...

    async def verify(self, text: str) -> None: ...

    async def dispose(self) -> None: ...


class Surface:
    """The whole X screen. Subclass and override to target something else."""

    name = "screen"

    async def refresh_offset(self, system: System) -> None:
        """Update system.window_offset to where the surface origin sits on screen.

        Called before every pointer move. The screen surface leaves the
        offset alone, so it stays at whatever the last surface set, which is
        (0, 0) unless a plugin changed it.
        """
        return None

    async def size(self, system: System) -> dict[str, int]:
        """Width and height of the surface in pixels."""
        resolution = system.get_resolution()
        return {"w": resolution["width"], "h": resolution["height"]}

    async def scroll_y(self) -> float | None:
        """Vertical scroll position, or None when the surface has none."""
        return None

    async def editable_focused(self) -> bool:
        """Whether a text field has keyboard focus, where that is knowable."""
        return False

    async def typing_guard(self, text: str) -> TypoGuard | None:
        """Inspect the focused field before typing with typos.

        None means nothing can be inspected, and typos are allowed. A guard
        whose is_allowed is false turns typos off for this text and reports
        its reason.
        """
        return None

    def describe(self) -> dict[str, Any]:
        """Short description for /state."""
        return {"name": self.name}
