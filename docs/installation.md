---
title: Installation and security
description: Ports, environment variables, authentication, the run_command and launch_app switch, PUID and PGID, volumes and entrypoint hooks.
nav_order: 1
---

# Installation and security

## Run the image

```bash
docker run -d --name desk \
  -p 127.0.0.1:8080:8080 \
  -p 127.0.0.1:5900:5900 \
  -e AUTH_TOKEN=change-me \
  -v "$PWD/userdata:/userdata" \
  -v "$PWD/recordings:/recordings" \
  psyb0t/auto-linux-desk:latest
```

Images are published for `linux/amd64` and `linux/arm64`.

| Port | Serves |
| --- | --- |
| 8080 | HTTP API (`POST /`, screenshots, state, events, health) and MCP at `/mcp/` |
| 5900 | noVNC in a browser (`http://host:5900/`), proxied to x11vnc |

## Security

The API can run any command in the container. `run_command` is a shell, and `launch_app` starts any program, both as the desktop user. Without `AUTH_TOKEN`, anyone who can reach port 8080 has that shell. The container prints a warning at startup when commands are enabled and no token is set.

- Set `AUTH_TOKEN` before the API port is reachable from anywhere but loopback. Every endpoint except `/health` then needs `Authorization: Bearer <token>`, MCP included. A token in the query string is refused.
- Set `DESK_EXEC_ENABLED=false` when clients only need input, windows, screenshots and the clipboard. `run_command` and `launch_app` then fail with an error. Input can still type into a terminal window that is already open, so this switch narrows the API, it is not a sandbox.
- noVNC has no password. Publish port 5900 on loopback, or put it behind something that authenticates.
- The desktop user is not root and has no sudo. The container is the isolation boundary: do not mount the Docker socket or host directories you would not hand to the client.

## Environment variables

| Variable | Default | Effect |
| --- | --- | --- |
| `AUTH_TOKEN` | unset | Bearer token for every endpoint except `/health`. |
| `DESK_EXEC_ENABLED` | `true` | `false` refuses `run_command` and `launch_app`. |
| `XVFB_RESOLUTION` | `1920x1080` | Screen size. The framebuffer is allocated at this size, so screenshots and recordings work at any resolution. |
| `XVFB_DEPTH` | `24` | Screen colour depth. |
| `TZ` | `UTC` | Time zone. |
| `PUID`, `PGID` | `1000` | UID and GID the desktop runs as. `PGID` defaults to `PUID`. |
| `VNC_SHOW_CURSOR` | `true` | `false` hides the pointer in the VNC view. |
| `HTTP_LISTEN_HOST`, `HTTP_LISTEN_PORT` | `0.0.0.0`, `8080` | API listen address. |
| `VNC_LISTEN_HOST`, `VNC_LISTEN_PORT` | `0.0.0.0`, `5900` | noVNC listen address. |
| `LOG_LEVEL` | `INFO` | JSON log level on stderr. |
| `LOG_FILE` | unset | Also write logs to this file, rotated. |
| `DESK_LAUNCH_LOG_DIR` | `/tmp/auto-linux-desk/launched` | Where `launch_app` writes each program's output. |
| `AUTO_LINUX_DESK_PLUGINS` | unset | Comma-separated Python modules to load as [plugins](plugins.md). |
| `DESK_HOME`, `DESK_WRITABLE_DIRS`, `DESK_BANNER` | `/home/desk`, `/userdata /recordings`, `AUTO-LINUX-DESK` | Set by derived images; see [plugins and derived images](plugins.md). |

## Users and volumes

The desktop runs as `desk` (UID and GID 1000, home `/home/desk`). With `PUID` and `PGID`, the entrypoint starts as root, takes ownership of `/userdata`, `/recordings` and the home directory for that UID and GID, then drops to it. Started with `docker run --user`, the entrypoint skips those ownership fixes.

| Path | Holds |
| --- | --- |
| `/userdata` | Free for your files; persisted when mounted. |
| `/recordings` | MP4 files from `stop_recording`. |
| `/home/desk` | Home directory, including the Openbox config. |

## Entrypoint hooks

Before dropping privileges, the entrypoint sources every `*.sh` file in `/etc/auto-linux-desk/entrypoint.d/` in filename order, as root. Hooks can read `TARGET_UID`, `TARGET_GID` and `DESK_HOME`. Use them for setup that needs root, such as fixing ownership of an extra directory.
