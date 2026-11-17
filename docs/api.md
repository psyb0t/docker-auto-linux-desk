---
title: Actions reference
description: Every endpoint and base action with its parameters, covering input, windows, programs, shell commands, clipboard, screenshots, recording and events.
nav_order: 2
---

# Actions reference

## Endpoints

| Endpoint | Method | What it does |
| --- | --- | --- |
| `/` | POST | Run one action. The body is a JSON object with `action` and its parameters. |
| `/screenshot/desktop` | GET | The whole screen as PNG. Query `whLargest`, `width` or `height` to resize. |
| `/screenshot/<name>` | GET | A screenshot a plugin registered. |
| `/state` | GET | Surface, window offset, resolution, handoff state, loaded plugins and plugin state. |
| `/events` | GET | Server-sent events. Query `after_id` and repeated `type`. |
| `/health` | GET | `ok`, or 503 with details when a plugin health check fails. Never needs the token. |
| `/mcp/` | POST | MCP Streamable HTTP; see [MCP and agents](mcp.md). |

Requests run one at a time, from HTTP and MCP alike, so only one action drives the X server at once.

Every response carries `X-Request-Id` and `X-Trace-Id` headers. Send your own `X-Request-Id` (up to 64 characters of `A-Za-z0-9._-`) to find the request in the JSON logs.

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

A failure has `"success": false` and an `error` string, and some failures also carry `data`, such as the output of a command that timed out.

## Coordinates

Input coordinates are screen pixels from the top-left corner. `desktop_list_windows` returns each window's geometry in the same space, so a point inside a window is its `x` plus an offset. Derived images can change the coordinate origin; see [plugins](plugins.md).

## Mouse and keyboard

All input goes through XTest with human timing: curved paths with overshoot and tremor, Fitts's-law durations, lognormal click holds, key-pair dependent typing rhythm with overlapping keys, and spaced wheel notches. Each container samples one consistent typist and mouse profile at startup.

| Action | Parameters | Notes |
| --- | --- | --- |
| `system_click` | `x`, `y` required; `w`, `h`, `duration`, `speed`, `curvature`, `tremor`, `click_hold`, `click_delay` | Moves to the point and left-clicks. With `w` and `h`, lands at a human offset inside that target. |
| `system_double_click` | `x`, `y`; `w`, `h`, `duration` and the mouse overrides | Both clicks fall inside the 400 ms double-click window. |
| `system_right_click` | as `system_click` | |
| `system_hover`, `mouse_move` | `x`, `y` required; `w`, `h`, `duration`, `speed`, `curvature`, `tremor` | Moves without clicking. |
| `mouse_click` | optional `x`, `y` and the mouse overrides | Without coordinates, clicks where the pointer is. |
| `system_mouse_down`, `system_mouse_up` | `button` (`left`, `right`, `middle`), optional `x`, `y` | Press or release one button. |
| `system_drag` | `source_x`, `source_y`, `target_x`, `target_y`; mouse overrides | Press, move along a human path, release. |
| `system_type` | `text` required; `interval`, `typos`, `typo_rate`, `key_hold`, `rollover` | Types into the focused window. `\n` presses Enter and `\t` presses Tab. Characters outside the US layout are typed through their keysyms. |
| `send_key` | `key` required; `key_hold`, `instant` | A key or combo in PyAutoGUI names: `enter`, `esc`, `ctrl+a`, `alt+f4`, `win+left`. `instant` skips human timing. |
| `scroll` | `amount` (non-zero, negative scrolls down, default -3); `x`, `y`, `notch_gap` | Wheel notches, after moving to `x`, `y` when given. |
| `human_pause` | `duration` (0.1 to 300); `x`, `y`, `w`, `h`, `drift`, `drift_interval`, `drift_distance`, mouse overrides | A visible pause with sparse pointer drift inside the screen or the given region. |

Override ranges: `speed` 0.1 to 10 (a multiplier), `curvature` 0 to 5, `tremor` 0 to 5 px, `click_hold` 0.01 to 5 s, `click_delay` 0 to 10 s, `key_hold` 0.01 to 2 s, `rollover` 0 to 1, `typo_rate` 0 to 0.2, `notch_gap` 0.015 to 5 s.

Window manager shortcuts are pressed with `send_key`. [Keyboard shortcuts](keyboard.md) lists them.

## Windows

Each window action except `desktop_list_windows` picks one window by exactly one of `id` (such as `0x01200004`), `title` (case-insensitive substring), `wm_class` (substring, such as `xterm`) or `pid`. The first match wins. `pid` only matches programs that publish `_NET_WM_PID`.

| Action | Parameters | Returns |
| --- | --- | --- |
| `desktop_list_windows` | none | `windows`: `id`, `title`, `wm_class`, `pid`, `x`, `y`, `width`, `height`, `desktop`, `active` |
| `desktop_focus_window` | selector | Raises and focuses the window. |
| `desktop_move_resize_window` | selector; any of `x`, `y`, `width`, `height` | Restores a maximized window first. Omitted values stay. |
| `desktop_set_window_state` | selector; `state` | `maximize`, `unmaximize`, `fullscreen`, `unfullscreen`, `minimize`, `unminimize`, `above`, `unabove`. |
| `desktop_close_window` | selector | Asks the window to close, as its close button would. |
| `desktop_keybindings` | none | The window manager shortcuts; see [keyboard shortcuts](keyboard.md). |

Window geometry comes from wmctrl and includes the frame offset Openbox adds, so a window placed at `100,100` can report a slightly different `x` and `y`.

## Programs and shell commands

`run_command` and `launch_app` are refused when `DESK_EXEC_ENABLED=false`. Both run as the desktop user with `DISPLAY` set.

| Action | Parameters | Returns |
| --- | --- | --- |
| `run_command` | `command` required: a string run with `bash -c`, or an argv list; `cwd`, `env` (object), `stdin` (up to 1 MiB), `timeout_s` (default 30, max 600) | `exit_code`, `stdout`, `stderr`, `stdout_truncated`, `stderr_truncated`, `timed_out`, `duration` |
| `launch_app` | `command` required (argv list); `cwd`, `env` | `id`, `pid`, `argv`, `running`, `exit_code`, `started_at`, `log_path` |
| `list_launched` | `output` (adds the last 16 KiB of each program's output), `forget_finished` | `launched` |
| `kill_launched` | `id` required; `signal` (`TERM` default, `INT`, `KILL`) | The program's entry after the signal. |

`run_command` keeps the first 1 MiB of each stream. It returns when the command exits; any process the command left in the background is killed then, so start long-running programs with `launch_app`. At the timeout the whole process group is killed, the action fails, and `data` still holds the output so far. Logs record only the program name, never its arguments.

`launch_app` starts the program in its own session and writes its output to `log_path`. Programs still running when the server stops get `SIGTERM`.

## Screen

| Action | Parameters | Returns |
| --- | --- | --- |
| `get_resolution` | none | `width`, `height` |
| `desktop_screenshot` | `width`, `height` or `whLargest`; `path` to also write the PNG inside the container | `type`, `size`, `path`. MCP returns the image itself; over HTTP use `GET /screenshot/desktop`. |
| `start_recording` | `mode` (`window` default, `desktop`, `viewport`), `fps` (default 15), `show_cursor` | Recording details. `viewport` crops to the active surface, which is the whole screen in this image. |
| `stop_recording` | `slug` required (`[a-zA-Z0-9][a-zA-Z0-9_-]{0,62}`) | Writes `/recordings/<slug>.mp4`. An existing name gets a numeric suffix. |
| `recording_status` | none | `active`, `mode`, start time |

## Clipboard

| Action | Parameters | Notes |
| --- | --- | --- |
| `set_clipboard` | `text`; or `format` with `text` (`html`), `content_base64` (`image/png`) or `files` (absolute paths) | Owns the X clipboard until replaced. Text up to 1 MiB. |
| `get_clipboard` | `format`: `text` (default), `html`, `image/png`, `files` | |

## Events and handoff

The server keeps the last 1000 events in memory: `action_failure`, `handoff_started`, `handoff_ended` and any a plugin publishes.

| Action | Parameters |
| --- | --- |
| `get_events` | `after_id`, `types` (list), `limit` (1 to 1000) |
| `wait_for_event` | `after_id`, `types`, `timeout` (up to 300 s) |
| `begin_handoff` | none. Blocks every action that changes something until `end_handoff`, so a person can work in noVNC. |
| `handoff_status` | none |
| `end_handoff` | none. Returns how long the handoff lasted. |

During a handoff only read-only actions run: `ping`, `list_actions`, `sleep`, events, `handoff_status`, `end_handoff`, `recording_status`, `get_resolution`, `desktop_screenshot`, `desktop_list_windows`, `desktop_keybindings` and `list_launched`.

## Scripts and utility

| Action | Parameters |
| --- | --- |
| `run_script` | `steps` (list) with optional `name` and `on_error` (`stop` or `continue`), or `yaml` (a script document). See [script mode](script-mode.md) for the format. |
| `list_actions` | none. Every registered action name, plugins included. |
| `ping` | none |
| `sleep` | `duration` in seconds, 0 to 3600 |
| `close` | none. Stops the server, which stops the container. |
