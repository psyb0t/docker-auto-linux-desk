# Changelog

All notable changes to this project are documented in this file.

## [0.4.1] 2026-11-19

### Added

- `DESK_SUDO_ENABLED`, off by default, grants the desktop UID passwordless sudo for all commands inside the container. Startup validates the setting and policy, replaces the grant when `PUID` changes, and removes the managed grant when disabled.
- An `.env.example` covers the desktop configuration, including the sudo flag and API authentication.
- Relative `CLAUDE.md` and `.claude` links point to the shared project guidance in `AGENTS.md` and `.agents`.
- A desktop-control skill, Claude Code and Codex plugin manifests, and an OpenClaw MCP bridge with locked dependencies and containerized development checks.
- Tag-triggered ClawHub and MCP Registry publication, plus Glama ownership metadata.
- README contents, agent installation instructions and a troubleshooting page.

### Changed

- Separate desktop accessibility documentation from GitHub's accessibility statement convention while preserving its published URL.
- Expand configuration, security, plugin and development guidance, and format command examples for reading.

## [0.4.0] 2026-11-19

### Added

- **Accessibility tree, like uiautomator for the desktop.** `desktop_accessibility_tree` reads controls that apps expose over AT-SPI2, the screen-reader protocol: role, name, states, screen bounds, actions, text and value per node. `desktop_accessibility_find` filters them by name, role and states, and `desktop_accessibility_action` runs a node's action, replaces an editable node's text or focuses it, without moving the mouse. They are HTTP actions and MCP tools; the two reads also run during a human handoff. The GTK zenity entry dialog was tested; other apps depend on their AT-SPI2 support and settings. See [Accessibility tree](https://psyb0t.github.io/docker-auto-linux-desk/accessibility/).
- The image installs `at-spi2-core` and `libatk-adaptor`, starts a D-Bus session bus and activates the AT-SPI2 bus on demand. The entrypoint sets `NO_AT_BRIDGE=0`, `GNOME_ACCESSIBILITY=1`, `ACCESSIBILITY_ENABLED=1`, `QT_ACCESSIBILITY=1` and `QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1`.
- **`KEYBINDINGS_FILE` replaces the whole key map at startup** with a file in the format of `docker/keymap.json`. An invalid map stops startup. See [Keyboard shortcuts](https://psyb0t.github.io/docker-auto-linux-desk/keyboard/#replacing-the-key-map).
- **Focus by app and by number.** `ctrl+alt+b` focuses the browser, `ctrl+alt+t` focuses the terminal or opens one, and `ctrl+alt+1` to `ctrl+alt+9` focus windows in the order they opened, through the new `desk-focus` script.
- Quarter tiling (`ctrl+alt+u`, `i`, `j`, `k`), top and bottom halves, toggle maximize, always on top, and reloading the window manager config.
- `desktop_keybindings` entries carry a `group` (Place, State, Focus, Open, Desktop), and their descriptions come from the key map.

### Changed

- **The key map is complete and owned, and no default binding uses the Super key.** `docker/keymap.json` is the whole keyboard section of the Openbox config; no stock Openbox binding survives. Every former `win+` binding moved to `ctrl+alt`: `win+left` and `win+right` are now `ctrl+alt+left` and `ctrl+alt+right`, `win+up` is `ctrl+alt+m` (toggle maximize), `win+down` is `ctrl+alt+r`, `win+f` is `ctrl+alt+f`, `win+h` is `ctrl+alt+n`, `win+c` is `ctrl+alt+c`, `win+d` is `ctrl+alt+d`, `win+shift+<arrow>` is `ctrl+alt+shift+<arrow>`, `win+enter` and `ctrl+alt+t` give way to `ctrl+alt+t` (focus or open) and `ctrl+alt+shift+t` (always a new terminal), `alt+space` is `ctrl+alt+space` and `alt+esc` is `ctrl+alt+esc`. `alt+tab`, `alt+shift+tab` and `alt+f4` stay. `ctrl+alt+tab` is gone.
- The keyboard docs table is generated from the key map, and a test fails when they differ.

### Fixed

- Alt+Tab keeps Openbox's default focus actions, and `desk-focus` handles WM_CLASS values with spaces.
- Invalid key maps stop startup with a nonzero exit status. Custom PUIDs get the account entry required by D-Bus.
- Accessibility actions validate their parameters, including empty text and action index zero. Tree walks handle cycles and only report node-limit truncation when a node is omitted.

## [0.3.0] 2026-11-18

### Changed

- The license is now the GNU Affero General Public License v3.0 only (AGPL-3.0-only) instead of the WTFPL. Releases up to 0.2.3 keep the WTFPL. A derived image that ships a plugin is a work based on auto-linux-desk and must also be released under the AGPL-3.0; anyone who runs a modified version as a network service must offer its source to its users.

### Documentation

- A [humanized input](https://psyb0t.github.io/docker-auto-linux-desk/humanized-input/) page describes how mouse, typing, wheel and pause input model a person, the defaults, and every tuning option.

## [0.2.3] 2026-11-18

### Fixed

- Screenshot providers registered with `register_screenshot` receive the request's Starlette `QueryParams` instead of a plain dict, so a repeated query parameter such as `frame=a&frame=b` reaches them in full through `getlist()`. `get()` works as before.

## [0.2.2] 2026-11-17

The code is unchanged from 0.2.1. This release republishes the image so the Docker Hub page carries the corrected README.

### Changed

- The README and documentation site present the image as usable on its own for Linux desktop automation as well as a base for derived images.
- `run_command` and `launch_app` are described as running any command or program they are given, instead of as a shell.
- The README lists every action. The actions reference documents every action's parameters, defaults, limits and return fields, including screenshot sizing, the events stream, recording modes and clipboard limits. The MCP page lists how each tool differs from its action. The installation, script mode, plugins and development pages fill in the remaining environment variable values, startup checks, script failure cases, registry options and Make targets.

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
