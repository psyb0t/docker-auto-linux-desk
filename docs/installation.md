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

The API can run any command in the container. `run_command` runs any command it is given through `bash -c`, and `launch_app` starts any program, both as the desktop user. Without `AUTH_TOKEN`, anyone who can reach port 8080 can do both. The container prints a warning at startup when they are enabled and no token is set.

- Set `AUTH_TOKEN` before the API port is reachable from anywhere but loopback. Every endpoint except `/health` then needs `Authorization: Bearer <token>`, MCP included. A token in the query string is refused.
- Set `DESK_EXEC_ENABLED=false` when clients only need input, windows, screenshots and the clipboard. `run_command` and `launch_app` then fail with an error. Input can still type into a terminal window that is already open, so this switch narrows the API, it is not a sandbox.
- noVNC has no password. Publish port 5900 on loopback, or put it behind something that authenticates.
- The desktop user is not root and has no sudo access by default. `DESK_SUDO_ENABLED=true` grants passwordless root access inside the container. The container is the isolation boundary: do not mount the Docker socket or host directories you would not hand to the client.

## Environment variables

| Variable | Default | Effect |
| --- | --- | --- |
| `AUTH_TOKEN` | unset | Bearer token for every endpoint except `/health`. Empty or whitespace counts as unset. |
| `DESK_EXEC_ENABLED` | `true` | `false` refuses `run_command` and `launch_app`. Accepts `true`, `1`, `yes`, `on` and `false`, `0`, `no`, `off`; anything else stops startup. |
| `DESK_SUDO_ENABLED` | `false` | Grants the desktop UID passwordless sudo for all commands and target users. Accepts `true`, `1`, `yes`, `on` and `false`, `0`, `no`, `off`; empty or other values stop startup. See [passwordless sudo](#passwordless-sudo). |
| `DESK_DARK_MODE` | `false` | Switches the whole desktop to dark: xterm colors, the Openbox theme (`Onyx`), GTK applications through `GTK_THEME=Adwaita:dark` (a browser's toolbar and the `prefers-color-scheme` it reports to pages) and the root window. Accepts `true`, `1`, `yes`, `on` and `false`, `0`, `no`, `off`; empty or other values stop startup. See [dark mode](#dark-mode). |
| `XVFB_RESOLUTION` | `1920x1080` | Screen size as `WIDTHxHEIGHT`. |
| `XVFB_DEPTH` | `24` | Screen colour depth. |
| `TZ` | `UTC` | Time zone. |
| `PUID`, `PGID` | `1000` | UID and GID the desktop runs as. `PGID` defaults to `PUID`. |
| `VNC_SHOW_CURSOR` | `true` | `true` draws the pointer into the VNC view, `false` hides it. Any other value stops startup. |
| `HTTP_LISTEN_HOST`, `HTTP_LISTEN_PORT` | `0.0.0.0`, `8080` | API listen address inside the container. |
| `VNC_LISTEN_HOST`, `VNC_LISTEN_PORT` | `0.0.0.0`, `5900` | noVNC listen address inside the container. |
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING` or `ERROR`, for the JSON logs on stderr. |
| `LOG_FILE` | unset | Also write logs to this file, rotated at 10 MiB with 5 old files kept. |
| `KEYBINDINGS_FILE` | unset | A key map file in the format of [`docker/keymap.json`](https://github.com/psyb0t/docker-auto-linux-desk/blob/main/docker/keymap.json) that replaces the whole map at startup. An invalid map stops startup. See [keyboard shortcuts](keyboard.md#replacing-the-key-map). |
| `DESK_LAUNCH_LOG_DIR` | `/tmp/auto-linux-desk/launched` | Where `launch_app` writes each program's output. |
| `AUTO_LINUX_DESK_PLUGINS` | unset | Comma-separated Python modules to load as [plugins](plugins.md). |
| `DESK_HOME`, `DESK_WRITABLE_DIRS`, `DESK_BANNER` | `/home/desk`, `/userdata /recordings`, `AUTO-LINUX-DESK` | Set by derived images; see [plugins and derived images](plugins.md). |
| `DESK_HOOK_DIR` | `/etc/auto-linux-desk/entrypoint.d` | Trusted root startup hook directory. See [entrypoint hooks](#entrypoint-hooks). |

Copy [`.env.example`](https://github.com/psyb0t/docker-auto-linux-desk/blob/main/.env.example) to a private `.env`, replace the token placeholder and pass `--env-file .env` to `docker run`. The file uses Docker env-file syntax, not a shell script. Recreate the container when changing its environment; restarting an existing container does not replace its stored environment. `AUTO_LINUX_DESK_URL` is a client/bridge setting, not a server listen address; see [agent setup](mcp.md).

## Users and volumes

The desktop runs as `desk` (UID and GID 1000, home `/home/desk`). The entrypoint starts as root, creates an account for a custom `PUID` if needed by D-Bus, gives `/userdata`, `/recordings` and the home directory to `PUID` and `PGID` when anything in them belongs to someone else, runs the [hooks](#entrypoint-hooks), then drops to that UID and GID. Started with `docker run --user`, it skips account creation, ownership fixes and hooks. The given UID must already have a passwd entry for D-Bus to start.

| Path | Holds |
| --- | --- |
| `/userdata` | Free for your files; persisted when mounted. |
| `/recordings` | MP4 files from `stop_recording`. Must stay writable for recording. |
| `/home/desk` | Home directory, including the Openbox config. |

## Entrypoint hooks

Before dropping privileges, the entrypoint sources every `*.sh` file in `/etc/auto-linux-desk/entrypoint.d/` in filename order, as root. They do not run under `docker run --user`. Hooks can read `TARGET_UID`, `TARGET_GID` and `DESK_HOME`. Use them for setup that needs root, such as fixing ownership of an extra directory.


## Dark mode

`DESK_DARK_MODE=true` turns the desktop dark with one setting:

- xterm, whichever launcher opens it (`xterm`, `uxterm`, `lxterm`), gets a dark background, light text and DejaVu Sans Mono from `/etc/auto-linux-desk/dark.Xresources`, loaded with `xrdb` at start.
- Openbox title bars and menus use the `Onyx` theme.
- `GTK_THEME=Adwaita:dark` is set for the server and everything it launches, so GTK applications, a Firefox-based browser's own toolbar included, draw dark and report `prefers-color-scheme: dark` to pages.
- The root window is dark grey.

It is off by default. A page can read `prefers-color-scheme`, so a derived image that cares about how its browser looks to sites should leave it off unless dark is wanted. Switching it off again on a restarted container puts the stock Openbox theme back.
## Passwordless sudo

Enable sudo only for a desktop you trust with root access:

```bash
docker run -d --name desk \
  -p 127.0.0.1:8080:8080 \
  -p 127.0.0.1:5900:5900 \
  -e AUTH_TOKEN=your-token-here \
  -e DESK_SUDO_ENABLED=true \
  psyb0t/auto-linux-desk:latest
```

The desktop still runs as `PUID` (1000 by default), but `sudo -n id -u` returns `0`. The same applies to commands submitted through `run_command`, programs started through `launch_app`, and commands typed into a terminal. Disabling those API actions does not prevent sudo through the desktop.

The root entrypoint validates the existing sudoers configuration and installs `/etc/sudoers.d/auto-linux-desk`, owned by root with mode `0440`. It grants the numeric UID `NOPASSWD: ALL` as any user and group. Changing `PUID` replaces the old managed grant; disabling the flag removes only that file on the next root startup. Other sudoers rules are not changed. `PUID` must be a canonical decimal number from 1 to 4294967294 when enabled, without leading zeros.

Start the entrypoint as root so it can configure the grant before dropping privileges. With `--user`, the flag works only if the running UID matches `PUID` and the image already has a working passwordless sudo grant. Otherwise startup fails. A read-only sudoers directory prevents configuring the grant. Docker's `no-new-privileges`, dropped capabilities and other restrictions can prevent sudo; the flag does not bypass them, and startup fails if the enabled grant cannot be used.

Anyone who controls this desktop can become root inside the container when enabled. Keep both ports private, require API authentication, and avoid sensitive host mounts.
