---
title: Home
description: Run a virtual Linux desktop in Docker and drive it over HTTP or MCP with humanized input, window control, app launching, shell commands, screenshots and recording.
nav_order: 0
permalink: /
seo:
  type: WebSite
---

# auto-linux-desk

One container runs a virtual X display with the Openbox window manager, an HTTP API, an MCP server and a noVNC viewer. A client sends actions: move and click the real mouse, type with real keystrokes, paste text, press window manager shortcuts, list and arrange windows, start programs, run shell commands, read and write the clipboard, take screenshots and record the screen. You can watch or take over through noVNC at any time.

Use it as it is for Linux desktop automation, or build your own image on it and add actions for the software you install through the [plugin interface](plugins.md).

## Start here

```bash
docker run -d --name desk \
  -p 127.0.0.1:8080:8080 \
  -p 127.0.0.1:5900:5900 \
  psyb0t/auto-linux-desk:latest
```

Open `http://localhost:5900/` for the viewer. Send HTTP commands to `http://localhost:8080/`, or connect an MCP client to `http://localhost:8080/mcp/`. This example listens on loopback only and has no authentication. Read [installation and security](installation.md) before making it reachable from another machine: `run_command` runs any command it is given.

```bash
curl --fail-with-body http://localhost:8080/ \
  -H 'Content-Type: application/json' \
  -d '{"action":"send_key","key":"ctrl+alt+t"}'
```

That opens a terminal with the window manager's shortcut. Type a short command into it with humanized keystrokes:

```bash
curl --fail-with-body http://localhost:8080/ \
  -H 'Content-Type: application/json' \
  -d '{"action":"system_type","text":"uname -a\n"}'
```

Then look at the result:

```bash
curl -o desk.png 'http://localhost:8080/screenshot/desktop?whLargest=1024'
```

## What is in the image

| Component | Purpose |
| --- | --- |
| Xvfb and Openbox | A virtual screen at `XVFB_RESOLUTION` with a window manager for title bars, focus and shortcuts. |
| x11vnc and noVNC | Watch and control the screen from a browser on port 5900. |
| Humanized input | Mouse paths, click timing, typing rhythm and wheel notches modelled on human data, sent through XTest. |
| wmctrl and xdotool | List, focus, move, resize, maximize and close top-level windows. |
| xterm | The default terminal, opened by `ctrl+alt+t` or `win+enter`. |
| ffmpeg, scrot, xclip | Screen recording, screenshots and the X clipboard. |
| HTTP, MCP and script mode | One action set behind `POST /`, an MCP endpoint at `/mcp/` and YAML scripts on stdin. |

## Documentation

- [Installation and security](installation.md): ports, authentication, users, volumes and the exec switch.
- [Actions reference](api.md): every endpoint and action with parameters.
- [Humanized input](humanized-input.md): how mouse, typing, wheel and pause input model a person, and every tuning option.
- [Keyboard shortcuts](keyboard.md): the window manager bindings and how to press them.
- [MCP and agents](mcp.md): connecting an MCP client and the tool list.
- [Script mode](script-mode.md): one-shot YAML scripts with JSON output.
- [Plugins and derived images](plugins.md): extending the action set and building images on this one.
- [Development](development.md): building, linting and testing.
