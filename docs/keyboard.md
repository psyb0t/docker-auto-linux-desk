---
title: Keyboard shortcuts
description: The Openbox key bindings in the image, how to press them with send_key, and how desktop_keybindings reads them from the live config.
nav_order: 4
---

# Keyboard shortcuts

The window manager has shortcuts for opening a terminal, tiling windows to half the screen, maximizing, fullscreen, minimizing, closing and switching windows. A client can press them with `send_key` instead of running shell commands.

```bash
curl --fail-with-body http://localhost:8080/ \
  -H 'Content-Type: application/json' \
  -d '{"action":"send_key","key":"win+left"}'
```

Shortcuts act on the focused window. Focus one first with a click or `desktop_focus_window`.

## Bindings

`win` is the Super key. The `send_key` column is the exact `key` value to send.

| `send_key` | Openbox key | Does |
| --- | --- | --- |
| `ctrl+alt+t` | `C-A-t` | Open a terminal (xterm) |
| `win+enter` | `W-Return` | Open a terminal (xterm) |
| `win+left` | `W-Left` | Tile the focused window to the left half |
| `win+right` | `W-Right` | Tile the focused window to the right half |
| `win+up` | `W-Up` | Maximize the focused window |
| `win+down` | `W-Down` | Restore the focused window from maximized |
| `win+f` | `W-f` | Toggle fullscreen on the focused window |
| `win+h` | `W-h` | Minimize the focused window |
| `win+c` | `W-c` | Center the focused window |
| `alt+f4` | `A-F4` | Close the focused window |
| `alt+tab` | `A-Tab` | Switch to the next window |
| `alt+shift+tab` | `A-S-Tab` | Switch to the previous window |
| `ctrl+alt+tab` | `C-A-Tab` | Switch to the next window, panels included |
| `win+shift+left` | `W-S-Left` | Focus the nearest window to the left |
| `win+shift+right` | `W-S-Right` | Focus the nearest window to the right |
| `win+shift+up` | `W-S-Up` | Focus the nearest window above |
| `win+shift+down` | `W-S-Down` | Focus the nearest window below |
| `win+d` | `W-d` | Hide or show all windows |
| `alt+esc` | `A-Escape` | Send the focused window to the back |
| `alt+space` | `A-space` | Open the window menu (move, resize, layer, close) |

Right-clicking an empty part of the screen opens the Openbox root menu, which also has a terminal entry.

The image has one desktop, so the stock Openbox bindings for switching desktops are removed, as are its file manager and screenshot bindings, whose programs are not installed. [`docker/configure-openbox.py`](https://github.com/psyb0t/docker-auto-linux-desk/blob/main/docker/configure-openbox.py) writes this config at build time.

## Reading the bindings at runtime

`desktop_keybindings` parses `~/.config/openbox/rc.xml` when called, so it lists what is installed, including changes a derived image makes:

```bash
curl --fail-with-body http://localhost:8080/ \
  -H 'Content-Type: application/json' \
  -d '{"action":"desktop_keybindings"}'
```

```json
{
  "success": true,
  "data": {
    "source": "/home/desk/.config/openbox/rc.xml",
    "count": 20,
    "keybindings": [
      {
        "key": "C-A-t",
        "send_key": [
          "ctrl+alt+t"
        ],
        "description": "run x-terminal-emulator",
        "actions": [
          {
            "name": "Execute",
            "options": {
              "command": "x-terminal-emulator"
            }
          }
        ]
      }
    ]
  }
}
```

`send_key` is a list with one entry per press. Chained bindings, where Openbox waits for a second key, have more than one entry; send them in order. The MCP tool of the same name returns this list, and the MCP instructions tell agents to call it.

## Changing the bindings

A derived image can edit `~/.config/openbox/rc.xml` of its desktop user. Openbox reads it at startup. `desktop_keybindings` picks up the change without code changes.
