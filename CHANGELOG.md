# Changelog

All notable changes to this project are documented in this file.

## [0.1.0] 2026-11-17

### Added

- Run a virtual Linux desktop in Docker: Xvfb at `XVFB_RESOLUTION`, Openbox with one desktop, x11vnc and noVNC on port 5900, and an HTTP API with an MCP endpoint on port 8080.
- Humanized OS-level mouse, keyboard and wheel input with per-request timing overrides, in screen coordinates. The input planners and executor come from stealthy-auto-browse v3.6.0.
- Window control through `desktop_list_windows`, `desktop_focus_window`, `desktop_move_resize_window`, `desktop_set_window_state` and `desktop_close_window`.
- Openbox key bindings for a terminal (`ctrl+alt+t`, `win+enter`), half-screen tiling, maximize, fullscreen, minimize and centering, plus `desktop_keybindings`, which lists every binding from the live config with its `send_key` value.
- Run shell commands with `run_command` and start programs with `launch_app`, `list_launched` and `kill_launched`. `DESK_EXEC_ENABLED=false` turns both off, and the container warns at startup when they are on without `AUTH_TOKEN`.
- Screenshots, screen recording, the X clipboard, events, human handoff, `run_script` and YAML script mode.
- A plugin interface for derived images: `AUTO_LINUX_DESK_PLUGINS` loads modules that add or replace actions, MCP tools, routes, screenshots, state, health checks, lifecycle hooks and the input coordinate surface. Root entrypoint hooks run from `/etc/auto-linux-desk/entrypoint.d/`.
- Documentation site, unit tests and a Docker-backed integration suite that measures input through a real X client.
- A Buy Me a Coffee funding link and a README Sponsor section.
