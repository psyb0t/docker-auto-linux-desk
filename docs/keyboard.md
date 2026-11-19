---
title: Keyboard shortcuts
description: The desktop's complete key map, how to press each binding with send_key, how to replace the map, and how desktop_keybindings reads it.
nav_order: 4
---

# Keyboard shortcuts

The desktop has one key map, and it is the whole list: every key the window manager answers to is in the table below and nothing else is bound. A client presses a binding with `send_key` instead of running shell commands or moving windows through the API.

```bash
curl --fail-with-body http://localhost:8080/ \
  -H 'Content-Type: application/json' \
  -d '{
    "action": "send_key",
    "key": "ctrl+alt+left"
  }'
```

Most bindings act on the focused window. The focus bindings (`alt+tab`, `ctrl+alt+b`, `ctrl+alt+t`, `ctrl+alt+1` to `ctrl+alt+9`) pick a window first.

## Bindings

The `send_key` column is the exact `key` value to send.

| `send_key` | Group | Does |
| --- | --- | --- |
| `ctrl+alt+left` | Place | Tile the focused window to the left half |
| `ctrl+alt+right` | Place | Tile the focused window to the right half |
| `ctrl+alt+up` | Place | Tile the focused window to the top half |
| `ctrl+alt+down` | Place | Tile the focused window to the bottom half |
| `ctrl+alt+u` | Place | Tile the focused window to the top-left quarter |
| `ctrl+alt+i` | Place | Tile the focused window to the top-right quarter |
| `ctrl+alt+j` | Place | Tile the focused window to the bottom-left quarter |
| `ctrl+alt+k` | Place | Tile the focused window to the bottom-right quarter |
| `ctrl+alt+c` | Place | Center the focused window |
| `ctrl+alt+m` | State | Maximize the focused window, or restore it if it is maximized |
| `ctrl+alt+f` | State | Toggle fullscreen on the focused window |
| `ctrl+alt+r` | State | Restore the focused window from maximized |
| `ctrl+alt+n` | State | Minimize the focused window |
| `ctrl+alt+a` | State | Toggle always on top for the focused window |
| `ctrl+alt+w` | State | Close the focused window |
| `alt+f4` | State | Close the focused window |
| `alt+tab` | Focus | Switch to the next window |
| `alt+shift+tab` | Focus | Switch to the previous window |
| `ctrl+alt+shift+left` | Focus | Focus the nearest window to the left |
| `ctrl+alt+shift+right` | Focus | Focus the nearest window to the right |
| `ctrl+alt+shift+up` | Focus | Focus the nearest window above |
| `ctrl+alt+shift+down` | Focus | Focus the nearest window below |
| `ctrl+alt+b` | Focus | Focus the browser |
| `ctrl+alt+t` | Focus | Focus the terminal, or open one if none is running |
| `ctrl+alt+1` | Focus | Focus window 1 (windows count in the order they opened) |
| `ctrl+alt+2` | Focus | Focus window 2 |
| `ctrl+alt+3` | Focus | Focus window 3 |
| `ctrl+alt+4` | Focus | Focus window 4 |
| `ctrl+alt+5` | Focus | Focus window 5 |
| `ctrl+alt+6` | Focus | Focus window 6 |
| `ctrl+alt+7` | Focus | Focus window 7 |
| `ctrl+alt+8` | Focus | Focus window 8 |
| `ctrl+alt+9` | Focus | Focus window 9 |
| `ctrl+alt+shift+t` | Open | Open a new terminal |
| `ctrl+alt+d` | Desktop | Hide or show all windows |
| `ctrl+alt+space` | Desktop | Open the focused window's menu (move, resize, layer, close) |
| `ctrl+alt+esc` | Desktop | Send the focused window to the back |
| `ctrl+alt+shift+r` | Desktop | Reload the window manager config |

No binding in the default map uses the Super (`win`) key. The map uses `ctrl+alt` combinations except for `alt+tab`, `alt+shift+tab` and `alt+f4`. A remote desktop viewer or VM console can forward keys to another system; which keys reach it depends on its keyboard grab and settings.

Right-clicking an empty part of the screen opens the Openbox root menu, which also has a terminal entry.

## Focus by app and by number

`ctrl+alt+b`, `ctrl+alt+t` and `ctrl+alt+1` to `ctrl+alt+9` run `desk-focus`, a small script in the image ([`docker/desk-focus`](https://github.com/psyb0t/docker-auto-linux-desk/blob/main/docker/desk-focus)):

- `desk-focus --class REGEX` focuses the most recently opened window whose `WM_CLASS` (`instance.Class`, as `wmctrl -l -x` prints it) matches the case-insensitive regular expression. `--launch COMMAND...` starts a program when nothing matches; `ctrl+alt+t` uses it to open a terminal.
- `desk-focus --slot N` focuses the Nth window, counting from 1 in the order the windows opened.

Slots follow the `wmctrl` list order, excluding windows on desktop `-1`, such as panels and docks. To compare with `desktop_list_windows`, first exclude its entries whose `desktop` is `-1`. A missing slot or unmatched class leaves focus alone and exits with status 1.

## Replacing the key map

The map lives in [`docker/keymap.json`](https://github.com/psyb0t/docker-auto-linux-desk/blob/main/docker/keymap.json). Each entry has a `key` in `send_key` notation, a `group`, a `description` and a list of Openbox `actions`, each with a `name` and its `options`:

```json
{
  "bindings": [
    {
      "key": "ctrl+alt+left",
      "group": "Place",
      "description": "tile the focused window to the left half",
      "actions": [
        {
          "name": "UnmaximizeFull"
        },
        {
          "name": "MoveResizeTo",
          "options": {
            "x": "0",
            "y": "0",
            "width": "50%",
            "height": "100%"
          }
        }
      ]
    }
  ]
}
```

Action names and options are Openbox's own; the [Openbox actions reference](http://openbox.org/help/Actions) lists them. Modifiers are `ctrl`, `alt`, `shift` and `win`. The generator validates the map's structure; Openbox resolves key names and action options. Check its startup log when a structurally valid custom binding does not work.

To use another map, mount a file in the same format and point `KEYBINDINGS_FILE` at it:

```bash
docker run -d -p 127.0.0.1:8080:8080 \
  -v "$PWD/my-keymap.json:/keymap.json:ro" \
  -e KEYBINDINGS_FILE=/keymap.json \
  psyb0t/auto-linux-desk
```

The entrypoint writes it as the whole keyboard section of `~/.config/openbox/rc.xml` before Openbox starts. A map with a key bound twice, an unknown modifier, or an entry without a description or actions stops the container with `ERROR: KEYBINDINGS_FILE=<path> is not a valid key map`. An image built on this one can instead replace `/etc/auto-linux-desk/keymap.json` and run `/usr/local/lib/auto-linux-desk/configure-openbox.py` in its own build.

## Reading the bindings at runtime

`desktop_keybindings` parses `~/.config/openbox/rc.xml` when called, so it lists what is installed. Each binding's `description` and `group` come from the `keymap.json` written next to it:

```bash
curl --fail-with-body http://localhost:8080/ \
  -H 'Content-Type: application/json' \
  -d '{
    "action": "desktop_keybindings"
  }'
```

```json
{
  "success": true,
  "data": {
    "source": "/home/desk/.config/openbox/rc.xml",
    "count": 38,
    "keybindings": [
      {
        "key": "C-A-Left",
        "send_key": [
          "ctrl+alt+left"
        ],
        "description": "tile the focused window to the left half",
        "group": "Place",
        "actions": [
          {
            "name": "UnmaximizeFull",
            "options": {}
          },
          {
            "name": "MoveResizeTo",
            "options": {
              "x": "0",
              "y": "0",
              "width": "50%",
              "height": "100%"
            }
          }
        ]
      }
    ]
  }
}
```

`send_key` is a list with one entry per press. A rc.xml written another way can hold chained bindings, where Openbox waits for a second key; send their entries in order. The MCP tool of the same name returns this list, and the MCP instructions tell agents to call it.
