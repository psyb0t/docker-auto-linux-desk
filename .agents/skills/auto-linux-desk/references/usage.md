# Desktop actions

For an unauthenticated loopback-only desktop, inspect windows with:

```bash
curl --fail-with-body "$AUTO_LINUX_DESK_URL/" \
  -H 'Content-Type: application/json' \
  -d '{
    "action": "desktop_list_windows"
  }'
```

When the server uses authentication, include the private Bearer header configured in your client. Do not print or persist its value in logs.

Read controls exported by an application:

```json
{
  "action": "desktop_accessibility_find",
  "name": "Save",
  "role": "push button",
  "exact": true
}
```

Use a returned node's bounds for `system_click`, or its current ID and listed action for `desktop_accessibility_action`. AT-SPI2 availability depends on the app. See [the accessibility reference](https://psyb0t.github.io/docker-auto-linux-desk/accessibility/).

Multi-step HTTP script:

```json
{
  "action": "run_script",
  "steps": [
    {
      "action": "send_key",
      "key": "ctrl+alt+t"
    },
    {
      "action": "system_type",
      "text": "uname -a\n"
    }
  ]
}
```

For MCP `run_script`, pass `steps` directly rather than the outer `action` field. For `desk_action`, put the action's parameters in `params`.

## Find the right interface

| Need | Interface |
| --- | --- |
| Observe screen | MCP `screenshot(whLargest=512)` or HTTP `GET /screenshot/desktop?whLargest=512`. |
| Focus or arrange windows | `desktop_list_windows`, `desktop_keybindings`, `send_key`; window actions are also available. |
| Enter text | `paste_text`, `system_type`, `send_key`; use clipboard data actions for HTML, PNG or file lists. |
| Inspect controls | `desktop_accessibility_tree`, `desktop_accessibility_find`, `desktop_accessibility_action`. |
| Run an authorized program | `launch_app`, `run_command`, `list_launched`, `kill_launched`; execution must be enabled. |
| Record | `start_recording`, `stop_recording`, `recording_status` through HTTP or `desk_action`; files are stored in `/recordings`. |
| Human control | `begin_handoff`, `handoff_status`, `end_handoff`. |

See the [complete action reference](https://psyb0t.github.io/docker-auto-linux-desk/api/), [MCP tool mapping](https://psyb0t.github.io/docker-auto-linux-desk/mcp/), [keyboard map](https://psyb0t.github.io/docker-auto-linux-desk/keyboard/) and [script format](https://psyb0t.github.io/docker-auto-linux-desk/script-mode/).
