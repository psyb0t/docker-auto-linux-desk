---
title: Humanized input
description: How the mouse, click, typing, wheel and pause planners model a person, the defaults they use, and every per-request option.
nav_order: 3
---

# Humanized input

Every mouse movement, click, keystroke and wheel notch is planned from published human motor data, then replayed through XTest with each event on its own schedule. Each container draws one typist and one mouse profile at startup and keeps them, so all input looks like one consistent person. Every option on this page is per request and optional. The [actions reference](api.md#mouse-and-keyboard) lists the actions and their return fields.

## The model

**Mouse.** Each move is a sum of overlapping sigma-lognormal strokes. A curved main stroke lands a little off, a mid-course re-aim sometimes follows, and one or two corrections finish exactly on the target. Movement time follows Fitts's law (longer moves and smaller targets take longer), speed peaks about a third of the way in, roughly a third of moves overshoot and correct, and a sub-pixel hand tremor rides on top. Events go out at a 125 Hz USB-mouse rate. The defaults were fitted to the SapiMouse dataset of 120 people.

**Clicks.** After arriving, the press waits a short human pause (usually about 40 ms, sometimes a few hundred while "checking" the target), holds the button about 85 to 125 ms, and occasionally slips 1 to 2 px while pressed (Balabit dataset). The aim point is scattered inside the target, never its exact centre. Both clicks of a double click fall inside the 400 ms double-click time.

**Typing.** Gaps between key presses are right-skewed (lognormal), shorter for common letter pairs and alternating hands, longer for the same finger and at word starts, with a slow drift in pace. Every key has its own hold, so fast typists press the next key before releasing the last; the same key never overlaps itself. Shift is pressed with the opposite hand well before the capital and held across runs of capitals. Each container picks a typist speed between slow and very fast (Aalto 136M keystrokes study).

**Wheel.** Scrolling happens in gestures of slow controlled notches or fast flicks that speed up and slow down. Two notches are never less than 15 ms apart.

**Pauses.** `human_pause` models time spent reading, reviewing or composing. The pointer stays still most of the time. Optional drifts use the same mouse path planner as other pointer actions, and their sparse, right-skewed timing avoids a periodic jiggle. Use it only when the task naturally includes visible thinking time; it is not a generic delay.

## Pointer options

Accepted by `system_click`, `system_double_click`, `system_right_click`, `mouse_click`, `mouse_move`, `system_hover`, `system_mouse_down` (when it moves), `system_drag`, `paste_text` (for its click) and `human_pause`, where they apply. The click options apply to clicks only.

| Option | Range | Default | Effect |
| --- | --- | --- | --- |
| `w`, `h` | greater than 0 | a small control | Target size in px. The landing point is scattered inside it and movement time follows its size. |
| `duration` | greater than 0 | Fitts's law | Rescale the whole move to this many seconds. Wins over `speed`. |
| `speed` | 0.1 to 10 | 1 (session pace) | Speed multiplier; 2 moves twice as fast. |
| `curvature` | 0 to 5 | 1 | How much the main stroke bends; 0 makes it straight. Corrections keep their own small bend. |
| `tremor` | 0 to 5 px | 0.35 | Hand tremor amplitude. |
| `click_hold` | 0.01 to 5 s | session, about 85 to 125 ms | Median time the button stays down. |
| `click_delay` | 0 to 10 s | human mix | Median pause between arriving and pressing. |

## Pause options

Accepted by `human_pause`. Without a rectangle, drift stays inside the surface (the screen, unless a plugin changed it). With `x` and `y`, both are required and mark the centre of the rectangle.

| Option | Range | Default | Effect |
| --- | --- | --- | --- |
| `duration` | 0.1 to 300 s | 1 s | Time spent in the pause after any initial parking move. |
| `x`, `y` | surface coordinates | none | Centre of the rectangle to park in. |
| `w`, `h` | 4 to 10000 px | 80 px | Rectangle size, intersected with the surface. |
| `drift` | true or false | true | Allow sparse pointer drifts during the pause. |
| `drift_interval` | 1 to 120 s | 12 s | Median interval of the right-skewed drift schedule. |
| `drift_distance` | 0 to 500 px | 60 px | Largest distance of each drift. Zero keeps the pointer still. |
| `speed`, `curvature`, `tremor` | as above | as above | Applied to the parking move and each drift. |

## Typing options

Accepted by `system_type`. `send_key` accepts `key_hold` (median 100 ms by default, held 50 to 250 ms), or `instant: true` to skip human timing entirely; the two cannot be combined.

| Option | Range | Default | Effect |
| --- | --- | --- | --- |
| `interval` | greater than 0 s | session typist speed | Median gap between key presses; also picks the matching typist's spread and key overlap. |
| `key_hold` | 0.01 to 2 s | session, about 75 to 145 ms | Median time each key is held. |
| `rollover` | 0 to 1 | by typist speed | When the next key comes before the last one is released, the chance of keeping that overlap instead of releasing first. |
| `typos` | true or false | false | Make and correct occasional typos. |
| `typo_rate` | 0 to 0.2 | 0.02 when typos are on | Typos per letter. Setting it above 0 turns typos on; `typos: false` with a non-zero `typo_rate` is an error. |

### Typos

Typos are always corrected. A neighbouring key, a swapped pair, or a doubled or missed letter is noticed right away about half the time, otherwise one to three keys later or at the end of the word, then erased with Backspace and retyped, so the final text is exactly what was asked for.

On the plain screen there is no field to inspect, so typos are made wherever the keyboard focus is. A plugin surface can inspect the focused field first and refuse typos where they could be validated, masked or submitted; the response then has `typos: false` and a `typos_disabled_reason`. See [surfaces](plugins.md#surfaces).

## Wheel options

| Option | Actions | Range | Default | Effect |
| --- | --- | --- | --- | --- |
| `notch_gap` | `scroll`, `scroll_to_bottom_humanized` | 0.015 to 5 s | flick or controlled rhythm | Median seconds between wheel notches. |
| `scroll_back` | `scroll_to_bottom_humanized` | 0 to 1 | 0.06 | Chance per gesture of scrolling back up a little, at most twice per page. |
| `drift` | `scroll_to_bottom_humanized` | 0 to 1 | 0.4 | Chance per reading pause of drifting the pointer. |

`scroll_to_bottom_humanized` needs a surface that reports its scroll position, such as a browser page, so this image registers it only through a plugin.

## Validation and threading

Out-of-range values are rejected with an error naming the option before any input is sent. Input options accept numeric strings such as `"250"`; `human_pause` numeric fields require JSON numbers. Boolean options must be JSON booleans.

Input runs in a worker thread, so `/health`, screenshots and MCP stay responsive while a long `system_type` or scroll plays. Actions themselves still run one at a time.
