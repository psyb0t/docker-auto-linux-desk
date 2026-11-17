# Changelog

All notable changes to this project are documented in this file.

## [0.2.1] 2026-11-17

v0.2.0 was tagged but never published: a ShellCheck finding in the new VNC cursor test failed the lint job, so no image or release was built. v0.2.1 is the first published release with everything listed under 0.2.0.

### Fixed

- The VNC cursor test passes ShellCheck.

## [0.2.0] 2026-11-17

### Added

- `paste_text` action and MCP tool: enters text the way people do. It puts the text on the clipboard, clicks the field when `x` and `y` are given, then presses `ctrl+a`, `backspace` and `ctrl+v` through the humanized `send_key`, with irregular pauses between the keys and before the first key after the click. `replace: false` pastes at the caret. It is meant for GUI text fields; terminals bind those keys differently.
- `set_clipboard_data` MCP tool for HTML, PNG and file-list clipboard data, matching stealthy-auto-browse.
- The MCP `mouse_move` and `human_pause` tools take every option stealthy-auto-browse's do (`curvature`, `tremor`, `drift_interval`, `drift_distance`, `speed`), and `system_double_click`, `system_right_click` and `system_drag` take the mouse overrides.
- The integration suite now covers every system-level check from stealthy-auto-browse's suites: users and ownership, recording, auth, the VNC cursor over a raw RFB client, resolutions, desktop screenshots, script mode and `run_script` control flow, the clipboard with a real X client, the request lock, the generic MCP tools, and humanized mouse, typing, scroll and pause metrics against human thresholds.

### Changed

- The MCP instructions and the `system_type`, `send_key` and `set_clipboard` descriptions tell agents to enter text with `paste_text` and keep `system_type` for a few characters. The actions reference and MCP docs say the same.

### Fixed

- The noVNC viewer kept showing the pointer where it was once viewers had sent no input for about 30 seconds, so someone watching automation saw a frozen cursor. x11vnc's idle napping stopped it from redrawing the cursor; it now runs with `-nonap`. An integration test idles past that point and checks the cursor still moves.
- `desktop_list_windows` returned a wrong title and WM_CLASS for windows whose WM_CLASS contains a space, such as a second Tk window (`tk #2`), so finding those windows by title failed. Titles now come from a listing without WM_CLASS, and WM_CLASS is read separately.

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
