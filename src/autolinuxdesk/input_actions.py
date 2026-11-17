"""Actions for humanized mouse, keyboard and wheel input.

Coordinates are relative to the active Surface. The default surface is the
whole X screen; a plugin can install one whose origin is a window's content
area, such as a browser viewport.

OS-level input blocks for as long as a human would take, so it runs in a
worker thread and the event loop keeps serving health checks, screenshots
and MCP while it plays. Actions are still serialized by the request lock,
so only one thread drives the X server at a time.
"""

from __future__ import annotations

import asyncio
import dataclasses
import math
from collections.abc import Awaitable, Callable
from typing import Any

from autolinuxdesk import human_keyboard, human_mouse, human_scroll
from autolinuxdesk.human_keyboard import TypingProfile
from autolinuxdesk.human_mouse import MouseProfile
from autolinuxdesk.logger import get_logger
from autolinuxdesk.surface import Surface
from autolinuxdesk.system import InputError, System

log = get_logger(__name__)


class InputActionError(Exception):
    """An input action was rejected or could not complete."""


ActionHandler = Callable[[dict, Surface, System], Awaitable[dict]]

_KEY_HOME = "home"
_WHEEL_DOWN = -1
_WHEEL_UP = 1

_SCROLL_AMOUNT_DEFAULT = -3
_SCROLL_MIN_CLICKS_DEFAULT = 2
_SCROLL_MAX_CLICKS_DEFAULT = 6
_SCROLL_CLICKS_LIMIT = 50
_SCROLL_DELAY_DEFAULT_S = 0.5
_SCROLL_MAX_GESTURES_DEFAULT = 500
_SCROLL_MAX_GESTURES_LIMIT = 10_000
_SCROLL_STALLS_TO_STOP = 2
_SCROLL_DRIFT_P = 0.4

_HUMAN_PAUSE_DEFAULT_S = 1.0
_HUMAN_PAUSE_DURATION_BOUNDS_S = (0.1, 300.0)
_HUMAN_PAUSE_DRIFT_INTERVAL_BOUNDS_S = (1.0, 120.0)
_HUMAN_PAUSE_DRIFT_DISTANCE_BOUNDS_PX = (0.0, 500.0)
_HUMAN_PAUSE_DRIFT_DISTANCE_DEFAULT_PX = 60.0
_HUMAN_PAUSE_TARGET_BOUNDS_PX = (4.0, 10_000.0)
_HUMAN_PAUSE_TARGET_DEFAULT_PX = 80.0
_HUMAN_PAUSE_COORDINATE_BOUNDS_PX = (-1_000_000.0, 1_000_000.0)

# Accepted ranges for per-request tuning overrides.
_SPEED_BOUNDS = (0.1, 10.0)
_CURVATURE_BOUNDS = (0.0, 5.0)
_TREMOR_BOUNDS_PX = (0.0, 5.0)
_CLICK_HOLD_BOUNDS_S = (0.01, 5.0)
_CLICK_DELAY_BOUNDS_S = (0.0, 10.0)
_KEY_HOLD_BOUNDS_S = (0.01, 2.0)
_ROLLOVER_BOUNDS = (0.0, 1.0)
_TYPO_RATE_BOUNDS = (0.0, 0.2)
_NOTCH_GAP_BOUNDS_S = (0.015, 5.0)
_PROBABILITY_BOUNDS = (0.0, 1.0)
_SCROLL_TOP_TIMEOUT_S = 3.0
_SCROLL_TOP_POLL_S = 0.1
_SCROLL_TOP_FLICK_NOTCHES = (8, 14)
_SCROLL_TOP_MAX_GESTURES = 200
# Where to put a pointer that is outside the surface before wheel scrolling.
_POINTER_HOME_FRAC = (0.3, 0.7)
_VIEWPORT_MARGIN_PX = 10


def _number(cmd: dict, name: str, required: bool = False) -> float | None:
    value = cmd.get(name)
    if value is None:
        if required:
            raise InputActionError(f"{name} is required")
        return None
    # Numeric strings were accepted before validation existed; keep them.
    if isinstance(value, str):
        try:
            value = float(value)
        except ValueError as e:
            raise InputActionError(f"{name} must be a number") from e
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InputActionError(f"{name} must be a number")
    if not math.isfinite(value):
        raise InputActionError(f"{name} must be finite")
    return float(value)


def _integer(cmd: dict, name: str, default: int) -> int:
    value = _number(cmd, name)
    if value is None:
        return default
    if not value.is_integer():
        raise InputActionError(f"{name} must be an integer")
    return int(value)


def _positive(cmd: dict, name: str) -> float | None:
    value = _number(cmd, name)
    if value is not None and value <= 0:
        raise InputActionError(f"{name} must be greater than 0")
    return value


def _flag(cmd: dict, name: str, default: bool) -> bool:
    value = cmd.get(name, default)
    if not isinstance(value, bool):
        raise InputActionError(f"{name} must be true or false")
    return value


def _xy(cmd: dict, required: bool) -> tuple[float | None, float | None]:
    x = _number(cmd, "x", required)
    y = _number(cmd, "y", required)
    if (x is None) != (y is None):
        raise InputActionError("x and y must be given together")
    return x, y


def _point(x: float | int, y: float | int) -> dict:
    return {"x": x, "y": y}


def _bounded(cmd: dict, name: str, bounds: tuple[float, float]) -> float | None:
    """Optional number that must fall inside bounds (inclusive)."""
    value = _number(cmd, name)
    lo, hi = bounds
    if value is not None and not lo <= value <= hi:
        raise InputActionError(f"{name} must be between {lo} and {hi}")
    return value


def _strict_bounded(
    cmd: dict,
    name: str,
    bounds: tuple[float, float],
    default: float | None = None,
) -> float | None:
    """Bound a new numeric API field without legacy numeric-string coercion."""
    if name not in cmd:
        return default
    value = cmd[name]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InputActionError(f"{name} must be a number")
    if not math.isfinite(value):
        raise InputActionError(f"{name} must be finite")
    lo, hi = bounds
    if not lo <= value <= hi:
        raise InputActionError(f"{name} must be between {lo} and {hi}")
    return float(value)


def _target(cmd: dict) -> tuple[float | None, float | None, float | None]:
    """Optional duration, width and height shared by pointer actions."""
    return _positive(cmd, "duration"), _positive(cmd, "w"), _positive(cmd, "h")


def _mouse_profile(cmd: dict, system: System) -> MouseProfile | None:
    """The session's mouse traits with any per-request overrides applied."""
    speed = _bounded(cmd, "speed", _SPEED_BOUNDS)
    curvature = _bounded(cmd, "curvature", _CURVATURE_BOUNDS)
    tremor = _bounded(cmd, "tremor", _TREMOR_BOUNDS_PX)
    click_hold = _bounded(cmd, "click_hold", _CLICK_HOLD_BOUNDS_S)
    click_delay = _bounded(cmd, "click_delay", _CLICK_DELAY_BOUNDS_S)
    overrides: dict[str, float] = {}
    if speed is not None:
        overrides["speed"] = system.mouse_profile.speed * speed
    if curvature is not None:
        overrides["curvature"] = curvature
    if tremor is not None:
        overrides["tremor_px"] = tremor
    if click_hold is not None:
        overrides["hold_median_s"] = click_hold
    if click_delay is not None:
        overrides["press_median_s"] = click_delay
    if not overrides:
        return None
    return dataclasses.replace(system.mouse_profile, **overrides)


async def mouse_move(cmd: dict, surface: Surface, system: System) -> dict:
    x, y = _xy(cmd, required=True)
    duration, width, height = _target(cmd)
    profile = _mouse_profile(cmd, system)
    await surface.refresh_offset(system)
    landed = await asyncio.to_thread(system.move_mouse, x, y, duration, width, height, profile)
    return {"moved_to": _point(cmd["x"], cmd["y"]), "landed_at": _point(*landed)}


async def mouse_click(cmd: dict, surface: Surface, system: System) -> dict:
    x, y = _xy(cmd, required=False)
    duration, width, height = _target(cmd)
    profile = _mouse_profile(cmd, system)
    await surface.refresh_offset(system)
    clicked = await asyncio.to_thread(system.click, x, y, duration, width, height, profile)
    if x is None:
        return {"clicked_at": "current", "landed_at": _point(*clicked)}
    return {"clicked_at": _point(cmd["x"], cmd["y"]), "landed_at": _point(*clicked)}


async def system_click(cmd: dict, surface: Surface, system: System) -> dict:
    x, y = _xy(cmd, required=True)
    duration, width, height = _target(cmd)
    profile = _mouse_profile(cmd, system)
    await surface.refresh_offset(system)
    clicked = await asyncio.to_thread(system.click, x, y, duration, width, height, profile)
    return {"system_clicked": _point(cmd["x"], cmd["y"]), "landed_at": _point(*clicked)}


async def system_hover(cmd: dict, surface: Surface, system: System) -> dict:
    return await mouse_move(cmd, surface, system)


async def system_double_click(cmd: dict, surface: Surface, system: System) -> dict:
    x, y = _xy(cmd, required=True)
    duration, width, height = _target(cmd)
    profile = _mouse_profile(cmd, system)
    await surface.refresh_offset(system)
    clicked = await asyncio.to_thread(
        system.double_click,
        x,
        y,
        duration,
        width,
        height,
        profile,
    )
    return {"system_double_clicked": _point(cmd["x"], cmd["y"]), "landed_at": _point(*clicked)}


async def system_right_click(cmd: dict, surface: Surface, system: System) -> dict:
    x, y = _xy(cmd, required=True)
    duration, width, height = _target(cmd)
    profile = _mouse_profile(cmd, system)
    await surface.refresh_offset(system)
    clicked = await asyncio.to_thread(
        system.button_click,
        "right",
        x,
        y,
        duration,
        width,
        height,
        profile,
    )
    return {"system_right_clicked": _point(cmd["x"], cmd["y"]), "landed_at": _point(*clicked)}


async def system_mouse_down(cmd: dict, surface: Surface, system: System) -> dict:
    button = cmd.get("button", "left")
    await surface.refresh_offset(system)
    try:
        x, y = _xy(cmd, required=False)
        if x is not None:
            duration, width, height = _target(cmd)
            profile = _mouse_profile(cmd, system)
            await asyncio.to_thread(
                system.move_mouse,
                x,
                y,
                duration,
                width,
                height,
                profile,
            )
        point = await asyncio.to_thread(system.mouse_down, button)
    except InputError as error:
        raise InputActionError(str(error)) from error
    return {"button": button, "down_at": _point(*point)}


async def system_mouse_up(cmd: dict, surface: Surface, system: System) -> dict:
    button = cmd.get("button", "left")
    await surface.refresh_offset(system)
    try:
        x, y = _xy(cmd, required=False)
        if x is not None:
            await asyncio.to_thread(system.move_mouse, x, y)
        point = await asyncio.to_thread(system.mouse_up, button)
    except InputError as error:
        raise InputActionError(str(error)) from error
    return {"button": button, "up_at": _point(*point)}


async def system_drag(cmd: dict, surface: Surface, system: System) -> dict:
    source_x = _number(cmd, "source_x", required=True)
    source_y = _number(cmd, "source_y", required=True)
    target_x = _number(cmd, "target_x", required=True)
    target_y = _number(cmd, "target_y", required=True)
    profile = _mouse_profile(cmd, system)
    await surface.refresh_offset(system)
    landed = await asyncio.to_thread(
        system.drag,
        source_x,
        source_y,
        target_x,
        target_y,
        profile,
    )
    return {
        "source": _point(source_x, source_y),
        "target": _point(target_x, target_y),
        "landed_at": _point(*landed),
    }


async def scroll(cmd: dict, surface: Surface, system: System) -> dict:
    amount = _integer(cmd, "amount", _SCROLL_AMOUNT_DEFAULT)
    if amount == 0:
        raise InputActionError("amount must be a non-zero integer")
    x, y = _xy(cmd, required=False)
    notch_gap = _bounded(cmd, "notch_gap", _NOTCH_GAP_BOUNDS_S)
    if x is not None:
        await surface.refresh_offset(system)
    await asyncio.to_thread(system.scroll, amount, x, y, notch_gap)
    return {"scrolled": amount}


async def send_key(cmd: dict, surface: Surface, system: System) -> dict:
    key = cmd.get("key", "")
    if not key or not isinstance(key, str):
        raise InputActionError("No key")
    key_hold = _bounded(cmd, "key_hold", _KEY_HOLD_BOUNDS_S)
    instant = _flag(cmd, "instant", False)
    if instant and key_hold is not None:
        raise InputActionError("key_hold cannot be used with instant")
    await asyncio.to_thread(system.send_key, key, key_hold, instant)
    return {"send_key": key}


def _int_in_range(cmd: dict, name: str, default: int, lo: int, hi: int) -> int:
    value = _integer(cmd, name, default)
    if not lo <= value <= hi:
        raise InputActionError(f"{name} must be an integer from {lo} to {hi}")
    return value


async def _pointer_into_viewport(surface: Surface, system: System) -> tuple[int, int, int, int]:
    """Make sure wheel events land on the surface; returns its bounds."""
    size = await surface.size(system)
    bounds = (
        _VIEWPORT_MARGIN_PX,
        _VIEWPORT_MARGIN_PX,
        int(size["w"]) - _VIEWPORT_MARGIN_PX,
        int(size["h"]) - _VIEWPORT_MARGIN_PX,
    )
    px, py = system.pointer_position()
    left, top, right, bottom = bounds
    if left <= px <= right and top <= py <= bottom:
        return bounds
    rng = system.rng
    tx = left + (right - left) * rng.uniform(*_POINTER_HOME_FRAC)
    ty = top + (bottom - top) * rng.uniform(*_POINTER_HOME_FRAC)
    log.debug("pointer outside surface, moving onto it", extra={"x": px, "y": py})
    await asyncio.to_thread(system.move_mouse, tx, ty, None, size["w"] / 2, size["h"] / 2)
    return bounds


def _pause_bounds(
    cmd: dict,
    viewport_bounds: tuple[int, int, int, int],
) -> tuple[
    tuple[int, int, int, int],
    tuple[float, float, float, float] | None,
]:
    has_coordinates = "x" in cmd or "y" in cmd
    if not has_coordinates:
        if "w" in cmd or "h" in cmd:
            raise InputActionError("w and h require x and y")
        return viewport_bounds, None

    x = _strict_bounded(cmd, "x", _HUMAN_PAUSE_COORDINATE_BOUNDS_PX)
    y = _strict_bounded(cmd, "y", _HUMAN_PAUSE_COORDINATE_BOUNDS_PX)
    if x is None or y is None:
        raise InputActionError("x and y must be given together")
    width = _strict_bounded(
        cmd,
        "w",
        _HUMAN_PAUSE_TARGET_BOUNDS_PX,
        _HUMAN_PAUSE_TARGET_DEFAULT_PX,
    )
    height = _strict_bounded(
        cmd,
        "h",
        _HUMAN_PAUSE_TARGET_BOUNDS_PX,
        _HUMAN_PAUSE_TARGET_DEFAULT_PX,
    )
    left, top, right, bottom = viewport_bounds
    safe_left = max(left, math.ceil(x - width / 2.0))
    safe_top = max(top, math.ceil(y - height / 2.0))
    safe_right = min(right, math.floor(x + width / 2.0))
    safe_bottom = min(bottom, math.floor(y + height / 2.0))
    if safe_right - safe_left < _HUMAN_PAUSE_TARGET_BOUNDS_PX[0]:
        raise InputActionError("pause target must intersect the viewport")
    if safe_bottom - safe_top < _HUMAN_PAUSE_TARGET_BOUNDS_PX[0]:
        raise InputActionError("pause target must intersect the viewport")
    safe_width = float(safe_right - safe_left)
    safe_height = float(safe_bottom - safe_top)
    park = (
        safe_left + safe_width / 2.0,
        safe_top + safe_height / 2.0,
        safe_width,
        safe_height,
    )
    return (safe_left, safe_top, safe_right, safe_bottom), park


async def human_pause(cmd: dict, surface: Surface, system: System) -> dict:
    duration = _strict_bounded(
        cmd,
        "duration",
        _HUMAN_PAUSE_DURATION_BOUNDS_S,
        _HUMAN_PAUSE_DEFAULT_S,
    )
    drift_interval = _strict_bounded(
        cmd,
        "drift_interval",
        _HUMAN_PAUSE_DRIFT_INTERVAL_BOUNDS_S,
        human_mouse.IDLE_DRIFT_INTERVAL_MEDIAN_S,
    )
    drift_distance = _strict_bounded(
        cmd,
        "drift_distance",
        _HUMAN_PAUSE_DRIFT_DISTANCE_BOUNDS_PX,
        _HUMAN_PAUSE_DRIFT_DISTANCE_DEFAULT_PX,
    )
    drift = _flag(cmd, "drift", True)
    profile = _mouse_profile(cmd, system)
    await surface.refresh_offset(system)
    viewport_bounds = await _pointer_into_viewport(surface, system)
    bounds, park = _pause_bounds(cmd, viewport_bounds)
    if not drift:
        drift_interval = None
    result = await asyncio.to_thread(
        system.human_pause,
        duration,
        bounds,
        park,
        drift_interval,
        drift_distance,
        profile,
    )
    return {
        "duration": duration,
        "elapsed": result["elapsed"],
        "drifts": result["drifts"],
        "parked": result["parked"],
        "landed_at": _point(*result["landed_at"]),
    }


async def _reading_pause(
    delay: float,
    drift_p: float,
    bounds: tuple[int, int, int, int],
    system: System,
) -> None:
    pause = human_scroll.reading_pause(system.rng, delay)
    if system.rng.random() >= drift_p:
        await asyncio.sleep(pause)
        return
    loop = asyncio.get_running_loop()
    started = loop.time()
    await asyncio.to_thread(system.drift, bounds)
    remaining = pause - (loop.time() - started)
    if remaining > 0:
        await asyncio.sleep(remaining)


async def _scroll_y(surface: Surface) -> float:
    value = await surface.scroll_y()
    if value is None:
        raise InputActionError("the active surface cannot report its scroll position")
    return value


async def _scroll_to_top(surface: Surface, system: System) -> bool:
    is_editing = await surface.editable_focused()
    if not is_editing:
        await asyncio.to_thread(system.send_key, _KEY_HOME)
        return await _wait_for_top(surface)
    # Home would move the caret instead, so flick back up with the wheel.
    for _ in range(_SCROLL_TOP_MAX_GESTURES):
        if await _scroll_y(surface) <= 0:
            return True
        notches = system.rng.randint(*_SCROLL_TOP_FLICK_NOTCHES)
        await asyncio.to_thread(system.scroll_gesture, notches, _WHEEL_UP)
    return await _wait_for_top(surface)


async def _wait_for_top(surface: Surface) -> bool:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + _SCROLL_TOP_TIMEOUT_S
    while loop.time() < deadline:
        if await _scroll_y(surface) <= 0:
            return True
        await asyncio.sleep(_SCROLL_TOP_POLL_S)
    return False


async def scroll_to_bottom_humanized(cmd: dict, surface: Surface, system: System) -> dict:
    min_clicks = _int_in_range(
        cmd, "min_clicks", _SCROLL_MIN_CLICKS_DEFAULT, 1, _SCROLL_CLICKS_LIMIT
    )
    max_clicks = _int_in_range(
        cmd, "max_clicks", _SCROLL_MAX_CLICKS_DEFAULT, 1, _SCROLL_CLICKS_LIMIT
    )
    if min_clicks > max_clicks:
        raise InputActionError("min_clicks must not exceed max_clicks")
    delay = _positive(cmd, "delay") or _SCROLL_DELAY_DEFAULT_S
    max_gestures = _int_in_range(
        cmd, "max_gestures", _SCROLL_MAX_GESTURES_DEFAULT, 1, _SCROLL_MAX_GESTURES_LIMIT
    )
    return_to_top = _flag(cmd, "return_to_top", True)
    notch_gap = _bounded(cmd, "notch_gap", _NOTCH_GAP_BOUNDS_S)
    scroll_back_p = _bounded(cmd, "scroll_back", _PROBABILITY_BOUNDS)
    if scroll_back_p is None:
        scroll_back_p = human_scroll.SCROLL_BACK_P
    drift_p = _bounded(cmd, "drift", _PROBABILITY_BOUNDS)
    if drift_p is None:
        drift_p = _SCROLL_DRIFT_P

    rng = system.rng
    await surface.refresh_offset(system)
    if await surface.scroll_y() is None:
        raise InputActionError("the active surface cannot report its scroll position")
    bounds = await _pointer_into_viewport(surface, system)
    gestures = scroll_backs = stalls = 0
    reached_bottom = False
    while gestures < max_gestures:
        before = await _scroll_y(surface)
        size = human_scroll.gesture_size(rng, bounds=(min_clicks, max_clicks))
        await asyncio.to_thread(system.scroll_gesture, size, _WHEEL_DOWN, notch_gap)
        gestures += 1
        await _reading_pause(delay, drift_p, bounds, system)
        after = await _scroll_y(surface)
        if after <= before:
            # Lazy-loaded pages may grow after a pause; give them one more try.
            stalls += 1
            if stalls >= _SCROLL_STALLS_TO_STOP:
                reached_bottom = True
                break
            continue
        stalls = 0
        wants_back = rng.random() < scroll_back_p
        if wants_back and scroll_backs < human_scroll.SCROLL_BACK_MAX_PER_PAGE:
            notches = human_scroll.scroll_back_notches(rng)
            await asyncio.to_thread(system.scroll_gesture, notches, _WHEEL_UP, notch_gap)
            await asyncio.sleep(human_scroll.scroll_back_pause(rng, delay))
            scroll_backs += 1

    returned_to_top = False
    if return_to_top:
        returned_to_top = await _scroll_to_top(surface, system)
    log.info(
        "humanized scroll finished",
        extra={
            "gestures": gestures,
            "scroll_backs": scroll_backs,
            "reached_bottom": reached_bottom,
            "returned_to_top": returned_to_top,
        },
    )
    return {
        "scrolled": "bottom_humanized",
        "gestures": gestures,
        "scroll_backs": scroll_backs,
        "reached_bottom": reached_bottom,
        "returned_to_top": returned_to_top,
    }


def _text_param(cmd: dict) -> str:
    text = cmd.get("text", "")
    if not text or not isinstance(text, str):
        raise InputActionError("No text")
    return text


def _typing_profile(cmd: dict, system: System) -> TypingProfile | None:
    """The session's typist with any per-request overrides applied.

    interval picks the typist speed first; key_hold and rollover then
    override that speed's defaults.
    """
    interval = _positive(cmd, "interval")
    key_hold = _bounded(cmd, "key_hold", _KEY_HOLD_BOUNDS_S)
    rollover = _bounded(cmd, "rollover", _ROLLOVER_BOUNDS)
    if interval is None and key_hold is None and rollover is None:
        return None
    profile = system.typing_profile
    if interval is not None:
        profile = profile.with_median_gap(interval)
    overrides: dict[str, float] = {}
    if key_hold is not None:
        overrides["hold_median_s"] = key_hold
    if rollover is not None:
        overrides["rollover_keep_p"] = rollover
    return dataclasses.replace(profile, **overrides)


def _requested_typo_rate(cmd: dict) -> float:
    """Typo rate asked for: typo_rate if given, else the default when typos is on."""
    typo_rate = _bounded(cmd, "typo_rate", _TYPO_RATE_BOUNDS)
    wants_typos = _flag(cmd, "typos", bool(typo_rate))
    if typo_rate is None:
        return human_keyboard.DEFAULT_TYPO_RATE if wants_typos else 0.0
    if typo_rate > 0 and not wants_typos:
        raise InputActionError("typo_rate needs typos to be true")
    return typo_rate if wants_typos else 0.0


async def system_type(cmd: dict, surface: Surface, system: System) -> dict:
    text = _text_param(cmd)
    profile = _typing_profile(cmd, system)
    requested_rate = _requested_typo_rate(cmd)
    guard = await surface.typing_guard(text) if requested_rate > 0 else None
    allowed = requested_rate > 0 and (guard is None or guard.is_allowed)
    typo_rate = requested_rate if allowed else 0.0
    try:
        await asyncio.to_thread(system.system_type, text, None, typo_rate, profile)
        if typo_rate and guard is not None:
            await guard.verify(text)
    except InputError as e:
        raise InputActionError(str(e)) from e
    finally:
        if guard is not None:
            await guard.dispose()
    result: dict = {"typed_len": len(text), "typos": allowed}
    if guard is not None and not guard.is_allowed:
        result["typos_disabled_reason"] = guard.reason
    return result


# Pauses around a paste: moving the hand from the mouse to the keyboard, and
# the beat between ctrl+a, backspace and ctrl+v.
_PASTE_REACH_MEDIAN_S = 0.35
_PASTE_REACH_SIGMA = 0.4
_PASTE_REACH_RANGE_S = (0.15, 1.2)
_PASTE_GAP_MEDIAN_S = 0.22
_PASTE_GAP_SIGMA = 0.45
_PASTE_GAP_RANGE_S = (0.07, 0.9)
_KEY_SELECT_ALL = "ctrl+a"
_KEY_CLEAR = "backspace"
_KEY_PASTE = "ctrl+v"

SetClipboard = Callable[[str], Awaitable[Any]]


async def paste_text(
    cmd: dict, surface: Surface, system: System, set_clipboard: SetClipboard
) -> dict:
    """Enter text the way people do: clipboard, then ctrl+a, backspace, ctrl+v.

    With x and y, clicks the field first with human motion. Each key goes
    through send_key with human timing, with irregular pauses between them.
    replace=false skips ctrl+a and backspace and pastes at the caret.
    """
    text = _text_param(cmd)
    replace = _flag(cmd, "replace", True)
    x, y = _xy(cmd, required=False)
    rng = system.rng
    clicked = None
    if x is not None:
        clicked = await system_click(cmd, surface, system)
    await set_clipboard(text)
    if clicked is not None:
        await asyncio.sleep(
            human_mouse.lognormal(
                rng, _PASTE_REACH_MEDIAN_S, _PASTE_REACH_SIGMA, _PASTE_REACH_RANGE_S
            )
        )
    keys = [_KEY_SELECT_ALL, _KEY_CLEAR, _KEY_PASTE] if replace else [_KEY_PASTE]
    try:
        for index, key in enumerate(keys):
            if index:
                await asyncio.sleep(
                    human_mouse.lognormal(
                        rng, _PASTE_GAP_MEDIAN_S, _PASTE_GAP_SIGMA, _PASTE_GAP_RANGE_S
                    )
                )
            await asyncio.to_thread(system.send_key, key)
    except InputError as error:
        raise InputActionError(str(error)) from error
    result: dict[str, Any] = {"pasted_len": len(text), "replaced": replace}
    if clicked is not None:
        result["clicked_at"] = clicked["system_clicked"]
        result["landed_at"] = clicked["landed_at"]
    return result


ACTIONS: dict[str, ActionHandler] = {
    "mouse_move": mouse_move,
    "mouse_click": mouse_click,
    "system_click": system_click,
    "system_hover": system_hover,
    "system_double_click": system_double_click,
    "system_right_click": system_right_click,
    "system_mouse_down": system_mouse_down,
    "system_mouse_up": system_mouse_up,
    "system_drag": system_drag,
    "scroll": scroll,
    "human_pause": human_pause,
    "system_type": system_type,
    "send_key": send_key,
}

# Needs a surface that reports its scroll position, so the base does not
# register it. A plugin with such a surface can.
SCROLL_POSITION_ACTIONS: dict[str, ActionHandler] = {
    "scroll_to_bottom_humanized": scroll_to_bottom_humanized,
}
