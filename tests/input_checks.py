"""Judge what an X client observed during humanized (or robotic) input.

Usage:
    input_checks.py <mouse|typing|scroll|pause> <events.jsonl>
        --expect <human|robot> [--targets FILE] [--notches N] [--duration N]

events.jsonl is the log written by tests/apps/event_logger.py. Times come
from the X server timestamps ("xt", milliseconds) the logger records.
--targets is a JSON list of [cx, cy, w, h] screen boxes, one per click in
order, for the mouse mode. With --expect human every check must pass. With
--expect robot enough checks must fail that the session is caught. Prints
one line per check and exits non-zero on a wrong verdict.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections.abc import Callable
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from input_metrics import skewness, stroke_features  # noqa: E402

_EXPECT_HUMAN = "human"
_EXPECT_ROBOT = "robot"
_MODE_MOUSE = "mouse"
_MODE_TYPING = "typing"
_MODE_SCROLL = "scroll"
_MODE_PAUSE = "pause"
# Own checks that must fail for a robotic control session to count as caught.
_ROBOT_MIN_FAILED = {
    _MODE_MOUSE: 2,
    _MODE_TYPING: 2,
    _MODE_SCROLL: 1,
    _MODE_PAUSE: 2,
}
_MS_PER_S = 1000.0
_STROKE_IDLE_GAP_S = 0.3

_LEFT_BUTTON = 1
_WHEEL_BUTTONS = frozenset({4, 5, 6, 7})
_PRESS_TYPES = frozenset({"down", "double"})
# Planned holds are 45-260 ms; event timestamps add a few ms of jitter.
_CLICK_HOLD_RANGE_MS = (30.0, 300.0)
_CLICK_HOLD_MEDIAN_RANGE_MS = (65.0, 160.0)
_APPROACH_MIN_MOVES = 5
_CENTRE_TOLERANCE_PX = 1.0
_MIN_STROKES = 8
_TIME_TO_PEAK_RANGE = (0.1, 0.5)
_STRAIGHTNESS_RANGE = (0.6, 0.995)
_PERFECTLY_STRAIGHT = 0.995
_PERFECTLY_STRAIGHT_MAX_SHARE = 0.5
_MULTI_PEAK_MIN_SHARE = 0.2
# A humanized session overshoots on about a quarter of its strokes and a
# straight-line mover on none; one overshoot is the floor.
_OVERSHOOT_MIN_STROKES = 1
_MOVE_GAP_MEDIAN_RANGE_MS = (4.0, 30.0)

_KEY_HOLD_MIN_MS = 25.0
_KEY_HOLD_MEDIAN_RANGE_MS = (60.0, 170.0)
_KEY_GAP_MIN_CV = 0.3
_SHIFT_LEAD_MIN_MS = 20.0
_SHIFT_KEYSYMS = frozenset({"Shift_L", "Shift_R"})

_WHEEL_MIN_GAP_MS = 10.0

_PAUSE_BURST_GAP_MS = 300.0
_PAUSE_MIN_BURSTS = 2
_PAUSE_MAX_BURSTS_PER_SECOND = 0.75
_PAUSE_MIN_EVENTS_PER_BURST = 3
_PAUSE_MAX_ACTIVE_SHARE = 0.35

Check = tuple[str, bool, str]


def load_events(path: Path) -> list[dict]:
    events = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    return [e for e in events if "xt" in e]


def _in_range(value: float, bounds: tuple[float, float]) -> bool:
    return bounds[0] <= value <= bounds[1]


def _left_clicks(events: list[dict]) -> list[tuple[dict, dict]]:
    """(press, release) pairs of the left button, in order."""
    pairs = []
    press = None
    for e in events:
        if e.get("button") != _LEFT_BUTTON:
            continue
        if e["type"] in _PRESS_TYPES:
            press = e
        elif e["type"] == "up" and press is not None:
            pairs.append((press, e))
            press = None
    return pairs


def _strokes(events: list[dict]) -> list[dict]:
    """Movement features for each approach to a left press.

    An approach is the last run of moves before the press, after the
    previous release and after any idle gap, as in the human-data analysis.
    """
    features = []
    segment: list[tuple[float, float, float]] = []
    for e in events:
        if e["type"] == "up":
            segment = []
            continue
        if e["type"] == "move":
            point = (e["xt"] / _MS_PER_S, e["x"], e["y"])
            if segment and point[0] - segment[-1][0] > _STROKE_IDLE_GAP_S:
                segment = []
            segment.append(point)
            continue
        if e["type"] not in _PRESS_TYPES or e.get("button") != _LEFT_BUTTON:
            continue
        feature = stroke_features(segment) if segment else None
        if feature:
            features.append(feature)
        segment = []
    return features


def mouse_checks(events: list[dict], targets: list[list[float]]) -> list[Check]:
    clicks = _left_clicks(events)
    checks: list[Check] = [
        ("clicks recorded", len(clicks) >= _MIN_STROKES, f"clicks={len(clicks)}"),
        (
            "one click per target",
            len(clicks) == len(targets),
            f"clicks={len(clicks)} targets={len(targets)}",
        ),
    ]
    if not clicks:
        return checks

    holds = [up["xt"] - down["xt"] for down, up in clicks]
    checks.append(
        (
            "click hold in human range",
            all(_in_range(h, _CLICK_HOLD_RANGE_MS) for h in holds)
            and _in_range(statistics.median(holds), _CLICK_HOLD_MEDIAN_RANGE_MS),
            f"min={min(holds):.1f}ms median={statistics.median(holds):.1f}ms max={max(holds):.1f}ms",
        )
    )

    moves = [e for e in events if e["type"] == "move"]
    starved = 0
    previous_release = -1.0
    for down, up in clicks:
        approach = [m for m in moves if previous_release < m["xt"] <= down["xt"]]
        starved += len(approach) < _APPROACH_MIN_MOVES
        previous_release = up["xt"]
    checks.append(
        ("pointer moves before every click", starved == 0, f"clicks_without_approach={starved}")
    )

    centred = inside = 0
    for (down, _), (cx, cy, w, h) in zip(clicks, targets):
        centred += abs(down["x"] - cx) < _CENTRE_TOLERANCE_PX and (
            abs(down["y"] - cy) < _CENTRE_TOLERANCE_PX
        )
        inside += abs(down["x"] - cx) <= w / 2.0 and abs(down["y"] - cy) <= h / 2.0
    checks.append(("no dead-centre clicks", centred == 0, f"dead_centre={centred}"))
    checks.append(
        ("clicks land on target", inside == len(clicks), f"inside={inside}/{len(clicks)}")
    )

    gaps = [b["xt"] - a["xt"] for a, b in zip(moves, moves[1:]) if b["xt"] > a["xt"]]
    if gaps:
        checks.append(
            (
                "pointer motion cadence",
                _in_range(statistics.median(gaps), _MOVE_GAP_MEDIAN_RANGE_MS),
                f"median_gap={statistics.median(gaps):.1f}ms",
            )
        )

    strokes = _strokes(events)
    checks.append(("approach strokes", len(strokes) >= _MIN_STROKES, f"strokes={len(strokes)}"))
    if len(strokes) < _MIN_STROKES:
        return checks
    time_to_peak = statistics.median(s["time_to_peak"] for s in strokes)
    straightness = statistics.median(s["straightness"] for s in strokes)
    perfectly_straight = sum(s["straightness"] > _PERFECTLY_STRAIGHT for s in strokes) / len(
        strokes
    )
    multi_peak = sum(s["peaks"] >= 2 for s in strokes) / len(strokes)
    overshoots = sum(s["overshoot"] for s in strokes)
    checks += [
        (
            "bell-shaped speed profile",
            _in_range(time_to_peak, _TIME_TO_PEAK_RANGE),
            f"time_to_peak={time_to_peak:.3f}",
        ),
        (
            "curved paths",
            _in_range(straightness, _STRAIGHTNESS_RANGE),
            f"straightness={straightness:.3f}",
        ),
        (
            "few perfectly straight paths",
            perfectly_straight <= _PERFECTLY_STRAIGHT_MAX_SHARE,
            f"share={perfectly_straight:.2f}",
        ),
        (
            "corrective submovements",
            multi_peak >= _MULTI_PEAK_MIN_SHARE,
            f"multi_peak_share={multi_peak:.2f}",
        ),
        (
            "overshoot and correct",
            overshoots >= _OVERSHOOT_MIN_STROKES,
            f"overshoot_share={overshoots / len(strokes):.2f} strokes={overshoots}",
        ),
    ]
    return checks


def key_holds(events: list[dict]) -> tuple[list[float], int, int, int]:
    """Hold times in ms, plus counts of auto-repeats, orphan releases and stuck keys."""
    open_downs: dict[int, float] = {}
    holds: list[float] = []
    repeats = unmatched = 0
    for e in events:
        if e["type"] == "key":
            repeats += e["keycode"] in open_downs
            open_downs[e["keycode"]] = e["xt"]
        elif e["type"] == "keyup":
            if e["keycode"] not in open_downs:
                unmatched += 1
                continue
            holds.append(e["xt"] - open_downs.pop(e["keycode"]))
    return holds, repeats, unmatched, len(open_downs)


def typing_checks(events: list[dict]) -> list[Check]:
    events = [e for e in events if e["type"] in ("key", "keyup")]
    holds, repeats, unmatched, stuck = key_holds(events)
    checks: list[Check] = [
        ("no auto-repeat", repeats == 0, f"repeats={repeats}"),
        (
            "every key released",
            unmatched == 0 and stuck == 0,
            f"unmatched={unmatched} stuck={stuck}",
        ),
    ]
    if not holds:
        checks.append(("key holds recorded", False, "holds=0"))
        return checks
    checks.append(
        (
            "key holds in human range",
            min(holds) >= _KEY_HOLD_MIN_MS
            and _in_range(statistics.median(holds), _KEY_HOLD_MEDIAN_RANGE_MS),
            f"min={min(holds):.1f}ms median={statistics.median(holds):.1f}ms",
        )
    )

    presses = [e for e in events if e["type"] == "key" and e["keysym"] not in _SHIFT_KEYSYMS]
    gaps = [b["xt"] - a["xt"] for a, b in zip(presses, presses[1:])]
    if len(gaps) >= 3:
        cv = statistics.pstdev(gaps) / statistics.fmean(gaps)
        checks.append(
            (
                "irregular key rhythm",
                cv >= _KEY_GAP_MIN_CV and skewness(gaps) > 0,
                f"cv={cv:.2f} skew={skewness(gaps):.2f}",
            )
        )

    late_shift = capitals = 0
    shift_down_at: float | None = None
    is_first_capital = False
    for e in events:
        if e["keysym"] in _SHIFT_KEYSYMS:
            is_down = e["type"] == "key"
            shift_down_at = e["xt"] if is_down else None
            is_first_capital = is_down
            continue
        char = e.get("char") or ""
        if e["type"] != "key" or len(char) != 1 or not char.isupper():
            continue
        capitals += 1
        if shift_down_at is None:
            late_shift += 1
            continue
        # Later capitals in a run share the Shift already held.
        if is_first_capital and e["xt"] - shift_down_at < _SHIFT_LEAD_MIN_MS:
            late_shift += 1
        is_first_capital = False
    checks.append(
        (
            "shift pressed well before capitals",
            capitals > 0 and late_shift == 0,
            f"capitals={capitals} late={late_shift}",
        )
    )
    return checks


def scroll_checks(events: list[dict], notches: int | None) -> list[Check]:
    wheel = [e for e in events if e.get("button") in _WHEEL_BUTTONS]
    presses = [e for e in wheel if e["type"] == "down"]
    checks: list[Check] = []
    if notches is not None:
        checks.append(
            (
                "one wheel event per notch",
                len(presses) == notches,
                f"wheel_events={len(presses)} notches={notches}",
            )
        )
    if not presses:
        return [*checks, ("wheel events recorded", False, "wheel=0")]
    # X reports a notch as a press and release of a wheel button.
    paired = all(
        a["type"] == "down" and b["type"] == "up" and a["button"] == b["button"]
        for a, b in zip(wheel[::2], wheel[1::2])
    )
    checks.append(
        (
            "every wheel event is a single notch",
            paired and len(wheel) == 2 * len(presses),
            f"events={len(wheel)} presses={len(presses)}",
        )
    )
    gaps = [b["xt"] - a["xt"] for a, b in zip(presses, presses[1:])]
    if gaps:
        checks.append(
            ("notches spaced out", min(gaps) >= _WHEEL_MIN_GAP_MS, f"min_gap={min(gaps):.1f}ms")
        )
    return checks


def pause_checks(events: list[dict], duration: float | None) -> list[Check]:
    moves = [e for e in events if e["type"] == "move"]
    if duration is None or duration <= 0:
        return [("duration supplied", False, f"duration={duration}")]
    if not moves:
        return [("pointer movement recorded", False, "moves=0")]

    bursts: list[list[dict]] = [[moves[0]]]
    for move in moves[1:]:
        if move["xt"] - bursts[-1][-1]["xt"] > _PAUSE_BURST_GAP_MS:
            bursts.append([])
        bursts[-1].append(move)
    maximum_bursts = max(_PAUSE_MIN_BURSTS, round(duration * _PAUSE_MAX_BURSTS_PER_SECOND))
    median_events = statistics.median(len(burst) for burst in bursts)
    active_ms = sum(burst[-1]["xt"] - burst[0]["xt"] for burst in bursts)
    active_share = active_ms / (duration * _MS_PER_S)
    return [
        (
            "sparse movement bursts",
            _PAUSE_MIN_BURSTS <= len(bursts) <= maximum_bursts,
            f"bursts={len(bursts)} allowed={_PAUSE_MIN_BURSTS}-{maximum_bursts}",
        ),
        (
            "moves use trajectories",
            median_events >= _PAUSE_MIN_EVENTS_PER_BURST,
            f"median_events_per_burst={median_events:.1f}",
        ),
        (
            "stillness dominates",
            active_share <= _PAUSE_MAX_ACTIVE_SHARE,
            f"active_share={active_share:.3f}",
        ),
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("mode", choices=(_MODE_MOUSE, _MODE_TYPING, _MODE_SCROLL, _MODE_PAUSE))
    parser.add_argument("events", type=Path)
    parser.add_argument("--expect", choices=(_EXPECT_HUMAN, _EXPECT_ROBOT), required=True)
    parser.add_argument("--targets", type=Path)
    # A single scroll request of N notches.
    parser.add_argument("--notches", type=int)
    parser.add_argument("--duration", type=float)
    args = parser.parse_args()

    events = load_events(args.events)
    targets = json.loads(args.targets.read_text()) if args.targets else []
    builders: dict[str, Callable[[], list[Check]]] = {
        _MODE_MOUSE: lambda: mouse_checks(events, targets),
        _MODE_TYPING: lambda: typing_checks(events),
        _MODE_SCROLL: lambda: scroll_checks(events, args.notches),
        _MODE_PAUSE: lambda: pause_checks(events, args.duration),
    }
    checks = builders[args.mode]()
    for name, ok, detail in checks:
        print(f"  {'pass' if ok else 'FAIL'}: {name} ({detail})")

    failed = sum(1 for _, ok, _ in checks if not ok)
    if args.expect == _EXPECT_HUMAN:
        return 0 if failed == 0 else 1
    print(f"  robot control: checks_failed={failed}")
    return 0 if failed >= _ROBOT_MIN_FAILED[args.mode] else 1


if __name__ == "__main__":
    sys.exit(main())
