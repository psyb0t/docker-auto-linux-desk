# auto-linux-desk

[![CI](https://github.com/psyb0t/docker-auto-linux-desk/actions/workflows/pipeline.yml/badge.svg?branch=main)](https://github.com/psyb0t/docker-auto-linux-desk/actions/workflows/pipeline.yml)
[![version](https://raw.githubusercontent.com/psyb0t/docker-auto-linux-desk/badges/version.svg)](https://github.com/psyb0t/docker-auto-linux-desk/releases)
[![license](https://raw.githubusercontent.com/psyb0t/docker-auto-linux-desk/badges/license.svg)](LICENSE)
[![Docker Pulls](https://img.shields.io/docker/pulls/psyb0t/auto-linux-desk?style=flat-square)](https://hub.docker.com/r/psyb0t/auto-linux-desk)

A virtual Linux desktop in Docker that you drive over HTTP or MCP. One container runs Xvfb, the Openbox window manager, a noVNC viewer and an API that moves the real mouse with human motion, types with human rhythm, presses window manager shortcuts, arranges windows, starts programs, runs shell commands, reads the clipboard, takes screenshots and records the screen.

It is also the base image for [stealthy-auto-browse](https://github.com/psyb0t/docker-stealthy-auto-browse), which adds a stealth browser through the plugin interface.

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
  -d '{"action":"send_key","key":"ctrl+alt+t"}'

# Type into it with human keystrokes
curl -X POST http://localhost:8080 \
  -H "Content-Type: application/json" \
  -d '{"action":"system_type","text":"uname -a\n"}'

# Or run a command directly
curl -X POST http://localhost:8080 \
  -H "Content-Type: application/json" \
  -d '{"action":"run_command","command":"ls -la /userdata"}'

# Look at the screen
curl "http://localhost:8080/screenshot/desktop?whLargest=512" -o desk.png
```

`run_command` and `launch_app` give whoever reaches port 8080 a shell in the container. Set `AUTH_TOKEN` before exposing the port anywhere but loopback, or set `DESK_EXEC_ENABLED=false` to turn both off. See [installation and security](https://psyb0t.github.io/docker-auto-linux-desk/installation/).

## What it can do

| Area | Actions |
| --- | --- |
| Mouse and keyboard | `system_click`, `system_double_click`, `system_right_click`, `system_drag`, `mouse_move`, `scroll`, `system_type`, `send_key`, `human_pause` |
| Keyboard shortcuts | `desktop_keybindings` lists the Openbox bindings: terminal, half-screen tiling, maximize, fullscreen, minimize, close, window switching |
| Windows | `desktop_list_windows`, `desktop_focus_window`, `desktop_move_resize_window`, `desktop_set_window_state`, `desktop_close_window` |
| Programs and shell | `launch_app`, `list_launched`, `kill_launched`, `run_command` |
| Screen | `desktop_screenshot`, `get_resolution`, `start_recording`, `stop_recording` |
| Other | clipboard, events, human handoff, `run_script`, `list_actions` |

Input coordinates are screen pixels. The timing is modelled on published human mouse and typing data and sent through XTest, so every X client sees ordinary input events.

## MCP

```bash
claude mcp add --transport http desk http://localhost:8080/mcp/
```

Every action has an MCP tool or is reachable through `desk_action`. The server instructions point agents at `desktop_keybindings` so they can use shortcuts as well as shell commands.

## Script mode

```bash
docker run --rm -i psyb0t/auto-linux-desk --script < script.yaml
```

The container runs the YAML steps, prints one JSON document on stdout and exits with 0 or 1.

## Building on it

Derived images set `AUTO_LINUX_DESK_PLUGINS` to Python modules whose `register(registry)` adds or replaces actions, MCP tools, routes, screenshots, state, health checks and lifecycle hooks. See [plugins and derived images](https://psyb0t.github.io/docker-auto-linux-desk/plugins/).

## Documentation

The full documentation is at **[psyb0t.github.io/docker-auto-linux-desk](https://psyb0t.github.io/docker-auto-linux-desk/)**.

| Page | Covers |
| --- | --- |
| [Installation and security](https://psyb0t.github.io/docker-auto-linux-desk/installation/) | Ports, environment variables, auth, users, volumes, hooks |
| [Actions reference](https://psyb0t.github.io/docker-auto-linux-desk/api/) | Every endpoint, action and parameter |
| [Keyboard shortcuts](https://psyb0t.github.io/docker-auto-linux-desk/keyboard/) | The window manager bindings |
| [MCP and agents](https://psyb0t.github.io/docker-auto-linux-desk/mcp/) | Client setup and tools |
| [Script mode](https://psyb0t.github.io/docker-auto-linux-desk/script-mode/) | YAML format and output |
| [Plugins and derived images](https://psyb0t.github.io/docker-auto-linux-desk/plugins/) | The extension interface |
| [Development](https://psyb0t.github.io/docker-auto-linux-desk/development/) | Make targets and tests |

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

[WTFPL](LICENSE). See the [changelog](CHANGELOG.md) for releases.
