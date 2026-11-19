---
title: Accessibility tree
description: Read the widgets of desktop apps over AT-SPI2, like uiautomator on Android, find them by name, role and state, and act on them without the mouse.
nav_order: 5
---

# Accessibility tree

The accessibility tree lists the buttons, fields, menu items and labels an app exposes through AT-SPI2, with their roles, names, states, screen rectangles and supported actions. Linux screen readers use the same protocol. Like `uiautomator dump` on Android, it lets a client find controls without recognizing pixels.

AT-SPI2 uses a separate accessibility D-Bus bus, discovered through the session bus. The image installs `at-spi2-core` and `libatk-adaptor`. The entrypoint starts a session bus and sets `NO_AT_BRIDGE=0`, `GNOME_ACCESSIBILITY=1`, `ACCESSIBILITY_ENABLED=1`, `QT_ACCESSIBILITY=1` and `QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1`. The API enables accessibility through `org.a11y.Status.IsEnabled`, discovers the accessibility bus through `org.a11y.Bus.GetAddress` and reads it directly with the pure-Python jeepney library.

## App support

The API can read controls that an app exports through AT-SPI2. The GTK `zenity --entry` dialog has been checked: its tree exposes the label, text field and buttons, and the API can replace the field's text and invoke OK. Zenity is not installed in the base image.

Qt apps, browsers, Electron and LibreOffice have not been tested here. Availability and detail depend on the app, its toolkit and its accessibility settings. A custom-drawn control or remote desktop's contents may have no accessible nodes. Use screenshots and `desktop_list_windows` when the tree does not expose what you need.

## Dump the tree

```bash
curl --fail-with-body http://localhost:8080/ \
  -H 'Content-Type: application/json' \
  -d '{"action":"desktop_accessibility_tree","app":"zenity"}'
```

| Parameter | Default | Meaning |
| --- | --- | --- |
| `app` | all apps | Application name (case-insensitive substring) or application id. |
| `max_depth` | `30` | Positive integer. How deep to walk below each application, whose root is depth 0. |
| `max_nodes` | `3000` | Positive integer. Maximum returned nodes across applications; `truncated` is `true` when another matching node was omitted. |
| `showing_only` | `true` | Leave out nodes without the AT-SPI `showing` state, with their children. Application roots are kept. |

The answer lists all registered applications in `apps` and the selected applications' nodes depth first in `nodes`. The walk stops at `max_depth` and at nodes with the `manages_descendants` state. These stops do not set `truncated`, which reports only the node limit. Nodes that disappear or cannot be read during the walk are skipped. A `zenity --entry` dialog gives:

```json
{
  "success": true,
  "data": {
    "apps": [
      {
        "id": ":1.2:/org/a11y/atspi/accessible/root",
        "name": "zenity",
        "children": 1
      }
    ],
    "count": 11,
    "truncated": false,
    "nodes": [
      {
        "id": ":1.2:/org/a11y/atspi/accessible/1",
        "role": "dialog",
        "name": "Probe",
        "bounds": {
          "x": 863,
          "y": 480,
          "w": 196,
          "h": 144
        },
        "parent": ":1.2:/org/a11y/atspi/accessible/root",
        "depth": 1
      },
      {
        "id": ":1.2:/org/a11y/atspi/accessible/6",
        "role": "label",
        "name": "Your name",
        "text": "Your name",
        "bounds": {
          "x": 877,
          "y": 513,
          "w": 168,
          "h": 17
        },
        "parent": ":1.2:/org/a11y/atspi/accessible/5",
        "depth": 5
      },
      {
        "id": ":1.2:/org/a11y/atspi/accessible/7",
        "role": "text",
        "name": "",
        "editable": true,
        "actions": [
          "Activate"
        ],
        "bounds": {
          "x": 877,
          "y": 536,
          "w": 168,
          "h": 34
        },
        "parent": ":1.2:/org/a11y/atspi/accessible/5",
        "depth": 5
      },
      {
        "id": ":1.2:/org/a11y/atspi/accessible/10",
        "role": "push button",
        "name": "OK",
        "actions": [
          "Click"
        ],
        "bounds": {
          "x": 965,
          "y": 578,
          "w": 86,
          "h": 34
        },
        "parent": ":1.2:/org/a11y/atspi/accessible/8",
        "depth": 5
      }
    ]
  }
}
```

(Captured from a live zenity dialog. Shortened to four of its 11 nodes, with states and some fields omitted. The ids, bounds and parent links are from that run; query your own tree before acting.)

Each node has:

| Field | Meaning |
| --- | --- |
| `id` | The node's bus name and object path. Pass it to `desktop_accessibility_action`. It can become stale when a widget is destroyed or the app exits; query again after the UI changes. |
| `role` | The AT-SPI role name: `push button`, `entry`, `text`, `label`, `menu item`, `check box`, `link`, `dialog`, `frame` and so on. |
| `name`, `description` | What the widget is called, as a screen reader would say it. |
| `states` | AT-SPI states such as `focused`, `focusable`, `enabled`, `sensitive`, `showing`, `visible`, `checked`, `selected`, `editable`, `expanded`, `modal`, `read_only`. |
| `bounds` | Screen rectangle in pixels, the same coordinates `system_click` takes. Present when the node supports the Component interface; off-screen nodes may report unusable coordinates. |
| `actions` | The actions the widget accepts, by the names the toolkit gives them (`Click`, `Press`, `Activate`, `Toggle`). |
| `text` | The widget's text, up to 2000 characters. |
| `value` | The current value of sliders, spin buttons and progress bars. |
| `editable` | `true` when its text can be replaced with `set_text`. |
| `parent`, `depth` | The parent node's id and the depth below the application. |

## Find nodes

```bash
curl --fail-with-body http://localhost:8080/ \
  -H 'Content-Type: application/json' \
  -d '{"action":"desktop_accessibility_find","name":"OK","role":"push button","exact":true}'
```

`name` matches case-insensitively, as a substring unless `exact` is `true`. `role` must equal the role name. `states` is a list that must all be present. At least one of the three is required. `app`, `max_depth`, `max_nodes` and `showing_only` work as in the dump. The answer has `matches`, `count` and `truncated`.

## Act on a node

There are two ways, and they look different on screen:

- **With the mouse.** Click the middle of the node's `bounds` with `system_click`. The pointer moves there along a human path, the way a person would do it, and a recording shows it.
- **Without the mouse.** `desktop_accessibility_action` asks the app to do it through AT-SPI, without moving the pointer. The app decides whether it can act on a covered or off-screen widget.

```bash
# Replace the text of an editable field
curl --fail-with-body http://localhost:8080/ \
  -H 'Content-Type: application/json' \
  -d '{"action":"desktop_accessibility_action","id":":1.2:/org/a11y/atspi/accessible/7","set_text":"hello"}'

# Run one of the node's actions by the name it lists
curl --fail-with-body http://localhost:8080/ \
  -H 'Content-Type: application/json' \
  -d '{"action":"desktop_accessibility_action","id":":1.2:/org/a11y/atspi/accessible/10","invoke":"Click"}'
```

Pass exactly one of:

| Parameter | Does | Answer |
| --- | --- | --- |
| `invoke` | Runs the named action, or the action at that zero-based index. | Fields `id`, `action`, `done`. |
| `set_text` | Replaces an editable node's whole text. | Fields `id`, `text_set`. |
| `focus` | `true` asks the node to take keyboard focus. | Fields `id`, `focused`. |

An id that no longer exists, an action the node does not have, or a node without the needed interface answers `success: false` with the reason. The `done`, `text_set` or `focused` boolean reports whether the app accepted a valid request.

`set_text` accepts valid UTF-8 text without NUL characters.

## During a human handoff

`desktop_accessibility_tree` and `desktop_accessibility_find` only read, so they keep working while a person has control through a handoff. `desktop_accessibility_action` changes the app and is refused until the handoff ends.

## When the tree is empty

- The app does not expose the controls through AT-SPI2; see [app support](#app-support).
- A program started outside the API with a cleaned environment has no `DBUS_SESSION_BUS_ADDRESS`. Start it with `launch_app`, which passes the desktop's environment on.
