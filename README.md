# auto-linux-desk

[![CI](https://github.com/psyb0t/docker-auto-linux-desk/actions/workflows/pipeline.yml/badge.svg?branch=main)](https://github.com/psyb0t/docker-auto-linux-desk/actions/workflows/pipeline.yml)
[![version](https://raw.githubusercontent.com/psyb0t/docker-auto-linux-desk/badges/version.svg)](https://github.com/psyb0t/docker-auto-linux-desk/releases)
[![license](https://raw.githubusercontent.com/psyb0t/docker-auto-linux-desk/badges/license.svg)](LICENSE)
[![Docker Pulls](https://img.shields.io/docker/pulls/psyb0t/auto-linux-desk?style=flat-square)](https://hub.docker.com/r/psyb0t/auto-linux-desk)

A virtual Linux desktop in Docker that you drive over HTTP or MCP. One container runs Xvfb, the Openbox window manager, a noVNC viewer and an API that moves the real mouse with human motion, types with human rhythm, presses window manager shortcuts, arranges windows, starts programs, runs shell commands, reads and writes the clipboard, takes screenshots and records the screen.

Use it as it is for Linux desktop automation, or build your own image on it: a plugin adds actions for the software you install, such as a browser.

## Contents

- [Quick start](#quick-start)
- [How it works](#how-it-works)
- [What it can do](#what-it-can-do)
- [Agent integrations](#agent-integrations)
- [Script mode](#script-mode)
- [Building on it](#building-on-it)
- [Configuration and security](#configuration-and-security)
- [Documentation](#documentation)
- [Development](#development)
- [Sponsor](#sponsor)
- [License](#license)

## Quick start

```bash
docker run -d --name desk \
  -p 127.0.0.1:8080:8080 \
  -p 127.0.0.1:5900:5900 \
  psyb0t/auto-linux-desk
```

Open `http://localhost:5900/` to watch the screen. Port 8080 serves the HTTP API and the MCP endpoint at `/mcp/`.

```bash
# Open a terminal with the window manager shortcut
curl -X POST http://localhost:8080 \
  -H "Content-Type: application/json" \
  -d '{
    "action": "send_key",
    "key": "ctrl+alt+t"
  }'

# Type into it with human keystrokes
curl -X POST http://localhost:8080 \
  -H "Content-Type: application/json" \
  -d '{
    "action": "system_type",
    "text": "uname -a\n"
  }'

# Or run a command directly
curl -X POST http://localhost:8080 \
  -H "Content-Type: application/json" \
  -d '{
    "action": "run_command",
    "command": "ls -la /userdata"
  }'

# Look at the screen
curl "http://localhost:8080/screenshot/desktop?whLargest=512" -o desk.png
```

The example keeps both ports on loopback. Read [configuration and security](#configuration-and-security) before making them reachable from another machine.

## How it works

One container owns one desktop. HTTP requests and MCP tools call the same action dispatcher; `run_script` keeps several steps under one request lock. The noVNC viewer shows the same screen the agent controls.

| Component | Purpose |
| --- | --- |
| Xvfb and Openbox | Virtual screen, windows, focus, tiling and keyboard shortcuts. |
| PyAutoGUI and XTest | OS-level mouse, keyboard and wheel input with humanized motion and timing. |
| D-Bus and AT-SPI2 | Read and act on widgets that desktop apps expose to accessibility clients. |
| HTTP API and MCP | Control the desktop on port 8080; MCP uses `/mcp/`. |
| x11vnc and noVNC | Watch and control the desktop in a browser on port 5900. |
| ffmpeg, scrot and xclip | MP4 recordings, PNG screenshots and the shared X11 clipboard. |

## What it can do

| Area | Actions |
| --- | --- |
| Mouse | `system_click`, `system_double_click`, `system_right_click`, `mouse_click`, `mouse_move`, `system_hover`, `system_mouse_down`, `system_mouse_up`, `system_drag`, `scroll`, `human_pause` |
| Keyboard | `paste_text`, `system_type`, `send_key` |
| Keyboard shortcuts | One complete key map with no Super-key bindings: half and quarter tiling, maximize, fullscreen, minimize, close, focus by app, by number and by direction, terminal. `desktop_keybindings` lists it, and `KEYBINDINGS_FILE` replaces it |
| Accessibility tree | `desktop_accessibility_tree`, `desktop_accessibility_find` and `desktop_accessibility_action` read and act on controls an app exposes through AT-SPI2, like uiautomator |
| Windows | `desktop_list_windows`, `desktop_focus_window`, `desktop_move_resize_window`, `desktop_set_window_state`, `desktop_close_window` |
| Programs and shell | `launch_app`, `list_launched`, `kill_launched`, `run_command` |
| Screen | `desktop_screenshot`, `get_resolution`, `start_recording`, `stop_recording`, `recording_status` |
| Clipboard | `set_clipboard`, `get_clipboard` (text, HTML, PNG, file lists) |
| Events and handoff | `get_events`, `wait_for_event`, `begin_handoff`, `handoff_status`, `end_handoff` |
| Scripts and utility | `run_script`, `list_actions`, `ping`, `sleep`, `close` |

Input coordinates are screen pixels. Input is sent through XTest, so every X client sees ordinary input events, with mouse paths, click timing and typing rhythm shaped like a person's.

## Agent integrations

Install the desktop-control skill through the shared plugin catalog:

```bash
# Claude Code
claude plugin marketplace add psyb0t/agents
claude plugin install auto-linux-desk@psyb0t

# Codex
codex plugin marketplace add psyb0t/agents
codex plugin add auto-linux-desk@psyb0t

# OpenClaw skill and MCP bridge
openclaw skills install @psyb0t/auto-linux-desk
openclaw plugins install clawhub:@psyb0t/auto-linux-desk
```

Run the desktop container separately. The skill teaches the client how to use it; the OpenClaw bridge connects to `AUTO_LINUX_DESK_URL` and sends `AUTH_TOKEN` when configured. See [MCP and agent setup](https://psyb0t.github.io/docker-auto-linux-desk/mcp/) for configuration and security.

For a direct HTTP MCP connection without installing a plugin:

```bash
claude mcp add --transport http desk http://localhost:8080/mcp/
```

Most actions have their own MCP tool, and `desk_action` runs any action by name. The server instructions tell agents to use window manager shortcuts from `desktop_keybindings`, to enter text with `paste_text`, and to keep `system_type` for a few characters.

## Script mode

```bash
docker run --rm -i psyb0t/auto-linux-desk --script < script.yaml
```

The container runs the YAML steps, prints one JSON document on stdout and exits with 0 when every step succeeded, 1 otherwise.

## Building on it

Derived images install their software and set `AUTO_LINUX_DESK_PLUGINS` to Python modules whose `register(registry)` adds or replaces actions, MCP tools, routes, screenshots, state, health checks and lifecycle hooks. See [plugins and derived images](https://psyb0t.github.io/docker-auto-linux-desk/plugins/).

## Configuration and security

`run_command` runs any command it is given and `launch_app` starts any program. With no `AUTH_TOKEN`, anyone who can reach port 8080 can run commands in the container. Set `AUTH_TOKEN` before exposing the port beyond loopback, or set `DESK_EXEC_ENABLED=false` to turn both off. The token protects HTTP and MCP, not noVNC; keep port 5900 private too.

The desktop runs as UID 1000 by default, without sudo access. Opt in with `DESK_SUDO_ENABLED=true` to allow passwordless sudo for all commands inside the container. Do not give it sensitive host mounts. See [passwordless sudo](https://psyb0t.github.io/docker-auto-linux-desk/installation/#passwordless-sudo) for custom UIDs and Docker restrictions.

Copy [`.env.example`](https://github.com/psyb0t/docker-auto-linux-desk/blob/main/.env.example) to a private `.env`, replace its token placeholder and pass it with `docker run --env-file .env`. The [installation reference](https://psyb0t.github.io/docker-auto-linux-desk/installation/) covers ports, authentication, display settings, persistent directories and root startup hooks.

## Documentation

The full documentation is at **[psyb0t.github.io/docker-auto-linux-desk](https://psyb0t.github.io/docker-auto-linux-desk/)**.

| Page | Covers |
| --- | --- |
| [Installation and security](https://psyb0t.github.io/docker-auto-linux-desk/installation/) | Ports, environment variables, auth, users, volumes, hooks |
| [Actions reference](https://psyb0t.github.io/docker-auto-linux-desk/api/) | Every endpoint, action and parameter |
| [Humanized input](https://psyb0t.github.io/docker-auto-linux-desk/humanized-input/) | The input model, defaults and tuning options |
| [Keyboard shortcuts](https://psyb0t.github.io/docker-auto-linux-desk/keyboard/) | The complete key map, focus helpers and how to replace the map |
| [Accessibility tree](https://psyb0t.github.io/docker-auto-linux-desk/accessibility/) | Read, find and act on app widgets over AT-SPI2 |
| [MCP and agents](https://psyb0t.github.io/docker-auto-linux-desk/mcp/) | Client setup and tools |
| [Script mode](https://psyb0t.github.io/docker-auto-linux-desk/script-mode/) | YAML format and output |
| [Plugins and derived images](https://psyb0t.github.io/docker-auto-linux-desk/plugins/) | The extension interface |
| [Development](https://psyb0t.github.io/docker-auto-linux-desk/development/) | Make targets and tests |
| [Troubleshooting](https://psyb0t.github.io/docker-auto-linux-desk/troubleshooting/) | Startup, authentication, connectivity, app controls and persistence |

## Development

```bash
make lint
make test-unit
make test
```

Everything runs in containers. `make help` lists all targets.

## Sponsor

<a href="https://www.buymeacoffee.com/psyb0t"><img src="https://cdn.buymeacoffee.com/buttons/v2/default-blue.png" alt="Buy Me a Coffee" height="60" width="217"></a>

## License

Copyright (C) 2026 Ciprian Mandache. Licensed under the [GNU Affero General Public License v3.0 only](LICENSE) (AGPL-3.0-only). If you run a modified version as a network service, you must offer its source to the people who use it. Releases up to 0.2.3 were published under the WTFPL and keep it. See the [changelog](CHANGELOG.md) for releases.
