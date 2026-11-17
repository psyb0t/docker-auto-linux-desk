---
title: Actions reference
description: Every endpoint and action with parameters, defaults, limits and return fields, from input and windows to commands, clipboard, recording and events.
nav_order: 2
---

# Actions reference

## Endpoints

| Endpoint | Method | What it does |
| --- | --- | --- |
| `/` | POST | Run one action. The body is a JSON object with `action` and its parameters. |
| `/screenshot/desktop` | GET | The whole screen as PNG. See [screenshot sizes](#screenshot-sizes). |
| `/screenshot/<name>` | GET | A screenshot a plugin registered. An unknown name returns 404. |
| `/state` | GET | JSON with `status`, `surface`, `window_offset`, `resolution`, `handoff_active`, `plugins`, and whatever plugins add. |
| `/events` | GET | Server-sent events. Query `after_id` and repeated `type`. |
| `/health` | GET | `ok`, or 503 with `{"ok": false, "failures": [...]}` when a plugin health check fails. Never needs the token. |
| `/mcp/` | POST | MCP Streamable HTTP; see [MCP and agents](mcp.md). |

With `AUTH_TOKEN` set, every endpoint except `/health` needs `Authorization: Bearer <token>` and answers 401 with `{"success": false, "error": "Unauthorized"}` without it. A request that puts `auth_token` in the query string is refused.

Requests run one at a time, from HTTP and MCP alike, so only one action drives the X server at once.

Every response carries `X-Request-Id` and `X-Trace-Id` headers. Send your own `X-Request-Id` (1 to 64 characters of `A-Za-z0-9._-`) to find the request in the JSON logs; anything else is replaced with a random ID.

### Screenshot sizes

`GET /screenshot/desktop` and the `desktop_screenshot` action take the same size parameters. Without any of them the PNG is full size.

| Parameter | Effect |
| --- | --- |
| `whLargest` | Scale so the longer side is this many pixels, keeping the aspect ratio. Wins over `width` and `height`. |
| `width` or `height` alone | Scale to that size, keeping the aspect ratio. |
| `width` and `height` | Scale to exactly that size, which stretches the image if the ratio differs. |

Each value is an integer from 1 to 20000 and can also enlarge the image. Any other value returns 400 over `GET` and a failed response from the action.

### Events stream

`GET /events` streams events as they happen, each as `id`, `event` (the type) and `data` (the event as JSON). With no events it sends a `: keepalive` comment every 15 seconds. `after_id` resumes after an event you already have. See [events and handoff](#events-and-handoff) for the event shape.

## Responses

```json
{
  "success": true,
  "timestamp": 1794929420.83,
  "data": {
    "exit_code": 0,
    "stdout": "hi\n"
  }
}
```

A failure has `"success": false` and an `error` string. Some failures also carry `data`, such as the output of a command that timed out. Invalid JSON, a body that is not an object, a non-string `action` and an unknown action all fail this way with HTTP 200.

## Coordinates

Input coordinates are screen pixels from the top-left corner. `desktop_list_windows` returns each window's geometry in the same space, so a point inside a window is its `x` and `y` plus an offset. Derived images can change the coordinate origin; see [plugins](plugins.md#surfaces).

## Mouse and keyboard

All input goes through XTest with human timing: curved paths with overshoot and tremor, Fitts's-law durations, lognormal click holds, key-pair dependent typing rhythm with overlapping keys, and spaced wheel notches. Each container samples one typist and one mouse profile at startup and keeps them.

`x` and `y` must be given together. Numbers may be sent as JSON numbers or numeric strings, except for `human_pause`, which takes JSON numbers only.

| Action | Parameters | Returns |
| --- | --- | --- |
| `system_click` | `x`, `y` required; `w`, `h`, `duration` and the mouse overrides | `system_clicked`, `landed_at`. With `w` and `h`, the click lands at a human offset inside that target. |
| `system_double_click` | as `system_click` | `system_double_clicked`, `landed_at`. Both clicks fall inside the 400 ms double-click time. |
| `system_right_click` | as `system_click` | `system_right_clicked`, `landed_at` |
| `mouse_click` | optional `x`, `y`; `w`, `h`, `duration` and the mouse overrides | `clicked_at` (`"current"` without coordinates), `landed_at`. Without coordinates, left-clicks where the pointer is. |
| `mouse_move`, `system_hover` | `x`, `y` required; `w`, `h`, `duration`, `speed`, `curvature`, `tremor` | `moved_to`, `landed_at`. Moves without clicking. |
| `system_mouse_down` | `button` (`left` default, `right`, `middle`); optional `x`, `y` with `w`, `h`, `duration` and the mouse overrides | `button`, `down_at`. Moves first when `x` and `y` are given, then presses. |
| `system_mouse_up` | `button` (`left` default); optional `x`, `y` | `button`, `up_at`. Moves first when `x` and `y` are given, then releases. |
| `system_drag` | `source_x`, `source_y`, `target_x`, `target_y` required; the mouse overrides | `source`, `target`, `landed_at`. Presses at the source, moves along a human path and releases at the target. |
| `scroll` | `amount` (non-zero integer, default -3, negative scrolls down); optional `x`, `y`; `notch_gap` | `scrolled`. Moves to `x`, `y` first when given, then sends that many wheel notches. |
| `system_type` | `text` required; `interval`, `typos`, `typo_rate`, `key_hold`, `rollover` | `typed_len`, `typos`. Types into the focused window. See [entering text](#entering-text). |
| `send_key` | `key` required; `key_hold`, `instant` | `send_key`. See below. |
| `human_pause` | `duration`; `x`, `y`, `w`, `h`; `drift`, `drift_interval`, `drift_distance`; `speed`, `curvature`, `tremor` | `duration`, `elapsed`, `drifts`, `parked`, `landed_at`. See below. |
| `paste_text` | `text` required; `x`, `y`, `w`, `h` and the mouse overrides; `replace` | See [entering text](#entering-text). |

`w`, `h` and `duration` must be greater than 0. `duration` scales the movement to that many seconds.

The mouse overrides change the session's mouse profile for one request:

| Override | Range | Meaning |
| --- | --- | --- |
| `speed` | 0.1 to 10 | Multiplier on the profile's movement speed. |
| `curvature` | 0 to 5 | How much the main stroke bends; 0 is straight. |
| `tremor` | 0 to 5 | Hand tremor amplitude in pixels. |
| `click_hold` | 0.01 to 5 | Median seconds the button is held. |
| `click_delay` | 0 to 10 | Median seconds between arriving and pressing. |

### send_key

`key` is a key name or a combo joined with `+`, in PyAutoGUI names: `enter`, `esc`, `tab`, `backspace`, `ctrl+a`, `alt+f4`, `win+left`, `ctrl+shift+t`. Modifiers go down in order with short human gaps, the last key is held, then all are released in reverse order.

- `key_hold` (0.01 to 2): median seconds the last key is held.
- `instant` (default `false`): press and release every key at once, with no human timing. It cannot be combined with `key_hold`.

Window manager shortcuts are pressed with `send_key`. [Keyboard shortcuts](keyboard.md) lists them.

### human_pause

A visible pause, such as reading time, where the pointer sits still most of the time and makes a few irregular small moves.

| Parameter | Default | Range | Meaning |
| --- | --- | --- | --- |
| `duration` | 1 | 0.1 to 300 | Seconds to pause. |
| `x`, `y` | none | | Centre of a region to park the pointer in first. Without them the pointer stays in the screen. |
| `w`, `h` | 80 | 4 to 10000 | Size of that region in pixels. Needs `x` and `y`. The region must overlap the screen. |
| `drift` | `true` | | Allow the small moves at all. |
| `drift_interval` | 12 | 1 to 120 | Median seconds between chances to move. |
| `drift_distance` | 60 | 0 to 500 | Largest move in pixels. 0 turns drift off. |

`speed`, `curvature` and `tremor` apply to the parking move and the drift. A pointer outside the screen is first moved onto it.

### Entering text

People paste far more than they type. `paste_text` enters text the way a person pastes it: it puts the text on the clipboard, clicks the field when `x` and `y` are given, then presses `ctrl+a`, `backspace` and `ctrl+v` through the humanized `send_key`, with irregular pauses between the keys and before the first key after the click.

| Parameter | Default | Meaning |
| --- | --- | --- |
| `text` | required | Up to 1 MiB of UTF-8. |
| `x`, `y`, `w`, `h` and the mouse overrides | none | Click the field first, as `system_click` does. |
| `replace` | `true` | `false` skips select-all and clear and pastes at the caret. |

It returns `pasted_len` and `replaced`, plus `clicked_at` and `landed_at` when it clicked. The text stays on the clipboard afterwards.

`paste_text` is meant for GUI text fields (browsers, GTK, Qt), where `ctrl+a` selects all and `ctrl+v` pastes. Terminals bind those keys differently (in xterm and shells `ctrl+a` moves to the line start), so type into a terminal with `system_type` or run the command with `run_command`.

Keep `system_type` for a few characters: a word, a short search, a small edit, a one-line command, or a field that blocks pasting. Typing a paragraph key by key is slow and is not what a person does. `\n` presses Enter and `\t` presses Tab. Characters outside the US layout are typed through their keysyms.

| `system_type` parameter | Default | Range | Meaning |
| --- | --- | --- | --- |
| `text` | required | | The text to type. |
| `interval` | the profile's | greater than 0 | Median seconds between keystrokes. |
| `key_hold` | the profile's | 0.01 to 2 | Median seconds each key is held. |
| `rollover` | the profile's | 0 to 1 | Probability that one key is still down when the next goes down. |
| `typos` | `false`, or `true` when `typo_rate` is above 0 | | Make occasional typos and correct them with Backspace. |
| `typo_rate` | 0.02 when `typos` is on | 0 to 0.2 | Typos per character. A rate above 0 with `typos: false` is an error. |

## Windows

Each window action except `desktop_list_windows` and `desktop_keybindings` picks one window by exactly one of these selectors. The first match wins.

| Selector | Matches |
| --- | --- |
| `id` | The window ID, such as `0x01200004`, in hex or decimal. |
| `title` | A case-insensitive substring of the title. |
| `wm_class` | A case-insensitive substring of WM_CLASS, such as `xterm`. |
| `pid` | The owning process ID. Only programs that publish `_NET_WM_PID` have one. |

| Action | Parameters | Returns |
| --- | --- | --- |
| `desktop_list_windows` | none | `windows` and `count`. Each window has `id`, `title`, `wm_class`, `pid` (`null` when unknown), `x`, `y`, `width`, `height`, `desktop` and `active`. |
| `desktop_focus_window` | selector | `window`. Raises and focuses it. |
| `desktop_move_resize_window` | selector; at least one of `x`, `y`, `width`, `height` (integers; `width` and `height` at least 1) | `window`, `requested`. Restores a maximized window first. Omitted values stay. |
| `desktop_set_window_state` | selector; `state` | `window`, `state`. `state` is `maximize`, `unmaximize`, `fullscreen`, `unfullscreen`, `minimize`, `unminimize`, `above` or `unabove`. |
| `desktop_close_window` | selector | `window`. Asks the window to close, as its close button would. |
| `desktop_keybindings` | none | The window manager shortcuts; see [keyboard shortcuts](keyboard.md). |

The `window` in each return is the window as it was before the action. Geometry comes from wmctrl and includes the frame offset Openbox adds, so a window placed at `100,100` can report a slightly different `x` and `y`.

## Programs and shell commands

`run_command` runs any command it is given and `launch_app` starts any program, both as the desktop user with `DISPLAY` set. Both are refused when `DESK_EXEC_ENABLED=false`. See [security](installation.md#security).

`cwd` must be an existing directory. `env` is an object of up to 200 string values added to the container's environment.

| Action | Parameters | Returns |
| --- | --- | --- |
| `run_command` | `command` required: a string run with `bash -c`, or an argv list run directly; `cwd`, `env`, `stdin` (a string up to 1 MiB), `timeout_s` (default 30, greater than 0, up to 600) | `exit_code`, `stdout`, `stderr`, `stdout_truncated`, `stderr_truncated`, `timed_out`, `duration` |
| `launch_app` | `command` required (argv list); `cwd`, `env` | `id`, `pid`, `argv`, `running`, `exit_code`, `started_at`, `log_path` |
| `list_launched` | `output` (`true` adds `output_tail`, the last 16 KiB of each program's output); `forget_finished` (`true` drops programs that exited before listing) | `launched` and `count` |
| `kill_launched` | `id` required (from `launch_app`); `signal` (`TERM` default, `INT`, `KILL`) | The program's entry after the signal. |

`run_command` keeps the first 1 MiB of stdout and of stderr and sets the `_truncated` flag when it cut one. It returns when the command exits; any process the command left in the background is killed then, so start long-running programs with `launch_app`. At the timeout the whole process group is killed, the action fails with `command timed out`, and `data` still holds the output so far. A non-zero exit code is still a successful action; check `exit_code`. Logs record only the program name, never its arguments.

`launch_app` starts the program in its own session with stdin closed and writes its stdout and stderr to `log_path`, under `DESK_LAUNCH_LOG_DIR`. IDs count up from 1. `kill_launched` signals the program's whole process group and waits up to 2 seconds for it to exit. Programs still running when the server stops get `SIGTERM`.

## Screen

| Action | Parameters | Returns |
| --- | --- | --- |
| `get_resolution` | none | `width`, `height` |
| `desktop_screenshot` | `width`, `height` or `whLargest` (see [screenshot sizes](#screenshot-sizes)); `path` to also write the PNG inside the container | `type`, `size` (bytes) and `path`. Over `POST /` the image itself is not in the response; use `GET /screenshot/desktop`. MCP returns the image, and a script collects it with `output_id`. |
| `start_recording` | `mode` (`window` default, `desktop`, `viewport`); `fps` (1 to 60, default 15); `show_cursor` (default `true`) | `recording_id`, `mode`, `fps`, `show_cursor`, `tmp_path`, `capture_size` |
| `stop_recording` | `slug` required (`[a-zA-Z0-9][a-zA-Z0-9_-]{0,62}`) | `recording_id`, `mode`, `slug`, `path`, `duration_s`, `size_bytes` |
| `recording_status` | none | `active`, and while recording `recording_id`, `mode`, `started_at`, `elapsed_s`, `tmp_path` |

Recording uses ffmpeg x11grab with H.264 into `/recordings`, which must be writable. Only one recording runs at a time. In this image `window`, `desktop` and `viewport` all capture the whole screen; `viewport` crops to the active surface, which a plugin can move. `stop_recording` writes `/recordings/<slug>.mp4`, and an existing name gets a `-2`, `-3` suffix. Leftover temporary files older than an hour are removed at startup.

## Clipboard

| Action | Parameters | Returns |
| --- | --- | --- |
| `set_clipboard` | `text`; or `format` with its value: `html` with `text`, `image/png` with `content_base64`, `files` with `files` | `length` and `bytes` for text; `format` and `bytes` otherwise |
| `get_clipboard` | `format`: `text` (default), `html`, `image/png`, `files` | `text`, `length`, `bytes` for text and HTML; `content_base64` for PNG; `files` (a list of `file://` URIs) for files |

Text and HTML are limited to 1 MiB of UTF-8, and a PNG to 1 MiB after decoding. `files` takes up to 32 absolute paths to existing regular files, not symlinks, totalling at most 1 GiB, and offers them as `text/uri-list`. The clipboard stays set until something replaces it. Logs never record clipboard contents.

## Events and handoff

The server keeps the last 1000 events in memory. Each has `id`, `type`, `timestamp` and `data`. The base publishes `action_failure` (with the `action` name), `handoff_started` and `handoff_ended` (with `duration` and `activity`); plugins can publish more. When older events were dropped, a read starting before them gets one `gap` event first, with `oldest_available_id`.

| Action | Parameters | Returns |
| --- | --- | --- |
| `get_events` | `after_id` (default 0), `types` (list), `limit` (1 to 1000, default 100) | `events`, `count` |
| `wait_for_event` | `after_id` (default 0), `types`, `timeout` (greater than 0, up to 300, default 30) | `events` and `count` as soon as one matches, or an empty list at the timeout |
| `begin_handoff` | none | `active`, `started_at`. Blocks every action that changes something until `end_handoff`, so a person can work in noVNC. |
| `handoff_status` | none | `active`, `started_at`, `activity` |
| `end_handoff` | none | `active`, `duration` in seconds, `activity` |

`activity` is `null` unless a plugin counts human input during the handoff.

During a handoff only these actions run: `ping`, `list_actions`, `sleep`, `get_events`, `wait_for_event`, `handoff_status`, `end_handoff`, `recording_status`, `get_resolution`, `desktop_screenshot`, `desktop_list_windows`, `desktop_keybindings` and `list_launched`. Everything else fails with `human handoff is active`.

## Scripts and utility

| Action | Parameters | Returns |
| --- | --- | --- |
| `run_script` | `steps` (list) with optional `name` (default `api_script`) and `on_error` (`stop` default, or `continue`); or `yaml`, a whole script document as a string | The script result; see [script mode](script-mode.md#output). Screenshots collected with `output_id` come back as data URIs. |
| `list_actions` | none | `actions`: every registered action name, plugins included |
| `ping` | none | `message`: `pong` |
| `sleep` | `duration` in seconds, 0 to 3600, default 1 | `slept` |
| `close` | none | `message`: `closing`. Stops the server, which stops the container. |
