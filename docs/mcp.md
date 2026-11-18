---
title: MCP and agents
description: Connect an MCP client to the Streamable HTTP endpoint, authenticate it, and see which tools it gets.
nav_order: 5
---

# MCP and agents

The server exposes an MCP endpoint over Streamable HTTP at `/mcp/` on the API port. Tools call the same actions as `POST /` and wait for the same request lock.

## Connect a client

Claude Code:

```bash
claude mcp add --transport http desk http://localhost:8080/mcp/
```

With `AUTH_TOKEN` set:

```bash
claude mcp add --transport http desk http://localhost:8080/mcp/ \
  --header "Authorization: Bearer change-me"
```

Other clients take the same URL and header in their HTTP MCP server config.

## Tools

Each tool runs the action of the same name with the same parameters, except where the table says otherwise, and returns the action's JSON response as text.

| Tool | Action and differences |
| --- | --- |
| `screenshot` | `desktop_screenshot` with `width`, `height`, `whLargest`. Returns the PNG as an image, not JSON. Pass `whLargest=512` to save tokens. |
| `get_resolution` | `get_resolution` |
| `system_click`, `system_double_click`, `system_right_click` | Same parameters as the actions. |
| `mouse_move` | `mouse_move` |
| `system_drag` | `system_drag` |
| `scroll` | `scroll`, `amount` defaults to -3. |
| `human_pause` | `human_pause` |
| `paste_text` | `paste_text`, the default way to enter text. |
| `system_type` | `system_type`. Giving `typo_rate` turns `typos` on. |
| `send_key` | `send_key` |
| `desktop_list_windows`, `desktop_focus_window`, `desktop_move_resize_window`, `desktop_set_window_state`, `desktop_close_window`, `desktop_keybindings` | The window actions. |
| `launch_app`, `kill_launched`, `run_command` | The program actions. |
| `list_launched` | `list_launched` with `output` only. |
| `set_clipboard` | `set_clipboard` with `text` only. |
| `set_clipboard_data` | `set_clipboard` with `format` and `text` (HTML), `content_base64` (PNG) or `files`. |
| `get_clipboard` | `get_clipboard` |
| `get_events`, `wait_for_event`, `begin_handoff`, `handoff_status`, `end_handoff` | The event and handoff actions. |
| `run_script` | `run_script` with `steps`, `name` (default `mcp_script`) and `on_error`. The whole script runs under one request lock, so no other request runs in between. Steps that already ran are not undone when a later one fails. |
| `desk_action` | Any action by name with a `params` object, for actions without their own tool: `system_hover`, `mouse_click`, `system_mouse_down`, `system_mouse_up`, `start_recording`, `stop_recording`, `recording_status`, `list_actions`, `ping`, `sleep`, `close`, and plugin actions. |

The [actions reference](api.md) documents every parameter, default and return field.

The server is named `auto-linux-desk`. Its MCP instructions tell agents that coordinates are screen pixels from the top-left corner, to pass `whLargest=512` to screenshots, to call `desktop_list_windows` before clicking into windows, to call `desktop_keybindings` once and press the shortcuts with `send_key`, to enter text with `paste_text` and keep `system_type` for a few characters, never to pass `instant` to `send_key`, and to use `run_script` for multi-step work.

Plugins can add, replace or remove tools and change the instructions. A plugin can also switch the server to script-only mode, where `run_script` is the only tool; see [plugins](plugins.md).
