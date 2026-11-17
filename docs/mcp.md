---
title: MCP and agents
description: Connect an MCP client to the Streamable HTTP endpoint, authenticate it, and see which tools it gets.
nav_order: 4
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

| Tool | Action |
| --- | --- |
| `screenshot` | `desktop_screenshot`; returns the PNG as an image. Pass `whLargest=512` to save tokens. |
| `get_resolution` | `get_resolution` |
| `system_click`, `system_double_click`, `system_right_click`, `system_drag`, `mouse_move` | Humanized pointer input |
| `paste_text` | Enter text by pasting it with human key timing; the default for text input |
| `system_type`, `send_key` | Humanized keyboard input; `system_type` for a few characters |
| `scroll`, `human_pause` | Wheel input and visible pauses |
| `desktop_list_windows`, `desktop_focus_window`, `desktop_move_resize_window`, `desktop_set_window_state`, `desktop_close_window` | Window control |
| `desktop_keybindings` | The window manager shortcuts |
| `launch_app`, `list_launched`, `kill_launched` | Programs |
| `run_command` | Shell commands |
| `set_clipboard`, `set_clipboard_data`, `get_clipboard` | Clipboard: text, or HTML, PNG and file lists |
| `get_events`, `wait_for_event`, `begin_handoff`, `handoff_status`, `end_handoff` | Events and handoff |
| `run_script` | Several actions as one atomic script |
| `desk_action` | Any action by name with a params object, for actions without a dedicated tool such as recording |

The [actions reference](api.md) documents every parameter. The server's MCP instructions tell agents that coordinates are screen pixels, to use small screenshots, to call `desktop_list_windows` before clicking into windows, to call `desktop_keybindings` once and press the shortcuts with `send_key`, and to enter text with `paste_text` rather than typing it, keeping `system_type` for a few characters.

Plugins can add, replace or remove tools and change the instructions. A plugin can also switch the server to script-only mode, where `run_script` is the only tool; see [plugins](plugins.md).
