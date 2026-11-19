---
title: Troubleshooting
description: Diagnose desktop startup, HTTP and MCP authentication, app accessibility, sudo, screenshots, volumes and client connection problems.
nav_order: 10
---

# Troubleshooting

## The container exits before the API starts

Read `docker logs desk` for a container you own. A malformed `DESK_EXEC_ENABLED`, `DESK_SUDO_ENABLED`, `VNC_SHOW_CURSOR` or key map stops startup. Check the accepted values in [installation](installation.md#environment-variables) and the [key map format](keyboard.md#replacing-the-key-map). The sudo flag rejects an explicitly empty value; omit it to use the default `false`.

A custom `PUID` is normally created by the root entrypoint before it drops privileges. `--user` skips account creation, ownership fixes and root hooks. A UID without a passwd entry can prevent D-Bus from starting. Prefer the documented `PUID`/`PGID` path unless your derived image already prepares its user and writable directories.

## HTTP or MCP returns Unauthorized

`GET /health` is the only unauthenticated endpoint when `AUTH_TOKEN` is set. Send `Authorization: Bearer <token>` for all other endpoints, including MCP. A token query parameter is not accepted. Make sure the client's private token matches the container's environment. Do not paste it into issue reports or logs.

## The viewer works but MCP does not

The viewer uses port 5900; HTTP and MCP use port 8080. Configure Streamable HTTP at `/mcp/`, not the viewer URL. A stdio-only client needs the [bridge](mcp.md#openclaw-skill-and-bridge). Its `AUTO_LINUX_DESK_URL` is the base URL without `/mcp/`. Inside another container, `localhost` means that container, not the desktop; use an appropriate private network address.

## Sudo is enabled but startup fails

The entrypoint must initially run as root to create the managed grant. An explicit `--user` works only with a preconfigured usable grant for that same `PUID`. Invalid sudoers policy or a read-only policy directory stops setup. Docker's `no-new-privileges` or dropped capabilities can prevent elevation. The flag does not bypass them. Keep sudo disabled if the workload must retain those restrictions. See [passwordless sudo](installation.md#passwordless-sudo).

## Input appears to do nothing

List windows and focus the intended app before entering text. Use `desktop_keybindings` and `send_key` for window manager shortcuts. Coordinates are pixels from the top-left corner of the active surface. During a human handoff, mutating actions fail until it ends. Check `success`, not just HTTP status; an action error normally returns HTTP 200 with `success: false`.

`run_command` has a second result to inspect: a nonzero program `exit_code` is still a successfully executed action. Long-running programs belong in `launch_app`; background children of a completed `run_command` are terminated.

## Accessibility queries return no controls

AT-SPI2 only exposes what the app supports. A custom-drawn interface may have no useful tree. Use a screenshot and window geometry instead. Apps launched with `launch_app` inherit the desktop's session bus; a program started elsewhere with a cleared environment may not. See [app support](desktop-accessibility.md#app-support).

## Files or recordings disappear

Mount `/userdata` and `/recordings` when those files must survive container removal. The home directory is separate and needs its own mount when its configuration must persist. Never share a writable directory between unrelated desktop instances. Check ownership for the configured UID/GID and ensure `/recordings` is writable.

## Screenshots are too large

Pass `whLargest=512` for normal inspection. Without a size option the server returns the full virtual screen. Increase it only when a control or text is too small to resolve. See [screenshot sizes](api.md#screenshot-sizes).
