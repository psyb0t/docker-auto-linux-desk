---
title: MCP and agent integrations
description: Connect Claude Code, Codex or OpenClaw to the desktop, configure authentication, and map the MCP tools to desktop actions.
nav_order: 6
---

# MCP and agent integrations

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

## Claude Code and Codex skills

Register the shared catalog and install the desktop skill:

```bash
claude plugin marketplace add psyb0t/agents
claude plugin install auto-linux-desk@psyb0t

codex plugin marketplace add psyb0t/agents
codex plugin add auto-linux-desk@psyb0t
```

The skill lives in [`.agents/skills/auto-linux-desk`](https://github.com/psyb0t/docker-auto-linux-desk/tree/main/.agents/skills/auto-linux-desk). It teaches the agent to inspect windows and widgets, use keyboard shortcuts and humanized input, choose clipboard paste, verify effects and respect a human handoff. Installing the skill does not start a container or automatically connect MCP.

Claude Code asks for a server `url` and optional sensitive `auth_token` when its plugin is enabled. Codex discovers the skill through the plugin or from a source checkout's `.agents/skills`; supply `AUTO_LINUX_DESK_URL` and optional `AUTH_TOKEN` privately. For named MCP tools, configure the direct HTTP connection above as well.

## OpenClaw skill and bridge

```bash
openclaw skills install @psyb0t/auto-linux-desk
openclaw plugins install clawhub:@psyb0t/auto-linux-desk
```

The skill provides instructions. The separate bridge lets a stdio MCP host reach the existing HTTP server. Set `AUTO_LINUX_DESK_URL` to the server's base URL, such as `http://localhost:8080`, and set `AUTH_TOKEN` when the server requires it. The bridge appends `/mcp/`; do not include that suffix yourself. URLs with embedded credentials, query strings or fragments are rejected.

The [bridge package](https://github.com/psyb0t/docker-auto-linux-desk/tree/main/.agents/plugins/auto-linux-desk) needs Node.js 18 or newer. When launched, its `auto-linux-desk-mcp` executable starts the pinned `mcp-remote` child process. Installation does not start a desktop. Configuration is environment-only. Protocol messages use stdout and diagnostics use stderr. The proxy reads the token from its inherited environment; arguments and normal startup messages contain only a placeholder. Keep the client machine and process environment private, and do not enable proxy debug logging with private data.

The configured desktop receives the Bearer token and tool inputs. Use a trusted server and HTTPS outside loopback or a trusted private network. These clients inherit the server's capabilities, including enabled program execution and optional sudo; they do not add a sandbox. Read [installation and security](installation.md) before enabling access.

## Publishing and discovery

The tag pipeline waits for the default-branch checks and image, promotes that image, creates the release, then publishes the selected skill and bridge to ClawHub and the Docker server metadata to the official MCP Registry using OIDC. Plugin package versions are filled from the release tag; their source `0.0.0` is a publishing placeholder.

The root [`server.json`](https://github.com/psyb0t/docker-auto-linux-desk/blob/main/server.json) describes the Docker artifact and its Streamable HTTP endpoint. [`glama.json`](https://github.com/psyb0t/docker-auto-linux-desk/blob/main/glama.json) identifies the Glama listing maintainer; adding it does not itself submit, approve or health-check a listing.

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
| `desktop_accessibility_tree`, `desktop_accessibility_find`, `desktop_accessibility_action` | The [accessibility tree](desktop-accessibility.md): dump, find and act on app widgets. |
| `launch_app`, `kill_launched`, `run_command` | The program actions. |
| `list_launched` | `list_launched` with `output` only. |
| `set_clipboard` | `set_clipboard` with `text` only. |
| `set_clipboard_data` | `set_clipboard` with `format` and `text` (HTML), `content_base64` (PNG) or `files`. |
| `get_clipboard` | `get_clipboard` |
| `get_events`, `wait_for_event`, `begin_handoff`, `handoff_status`, `end_handoff` | The event and handoff actions. |
| `run_script` | `run_script` with `steps`, `name` (default `mcp_script`) and `on_error`. The whole script runs under one request lock, so no other request runs in between. Steps that already ran are not undone when a later one fails. |
| `desk_action` | Any action by name with a `params` object, for actions without their own tool: `system_hover`, `mouse_click`, `system_mouse_down`, `system_mouse_up`, `start_recording`, `stop_recording`, `recording_status`, `list_actions`, `ping`, `sleep`, `close`, and plugin actions. |

The [actions reference](api.md) documents every parameter, default and return field.

The server is named `auto-linux-desk`. Its MCP instructions tell agents that coordinates are screen pixels from the top-left corner, to pass `whLargest=512` to screenshots, to call `desktop_list_windows` before clicking into windows, to call `desktop_keybindings` once and press its keys with `send_key` instead of moving windows through the API, that the default map has no Super-key binding, to find exported controls with `desktop_accessibility_tree` and `desktop_accessibility_find` and use screenshots when controls are not exposed, to enter text with `paste_text` and keep `system_type` for a few characters, never to pass `instant` to `send_key`, and to use `run_script` for multi-step work.

Plugins can add, replace or remove tools and change the instructions. A plugin can also switch the server to script-only mode, where `run_script` is the only tool; see [plugins](plugins.md).
