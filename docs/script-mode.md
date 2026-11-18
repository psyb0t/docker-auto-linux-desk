---
title: Script mode
description: Pipe a YAML script into a fresh container and get one JSON document back, with environment substitution, outputs, conditions and loops.
nav_order: 6
---

# Script mode

Pipe a YAML script into the container with `--script`. It starts the desktop, runs the steps, prints one JSON document on stdout and exits. There is no HTTP API or MCP in this mode; noVNC still runs if you publish port 5900 and want to watch. Logs go to stderr.

```bash
docker run --rm -i \
  -e GREETING=hello \
  psyb0t/auto-linux-desk --script < script.yaml > result.json
```

The exit code is 0 when every step succeeded and 1 otherwise. A script that is not valid YAML or fails validation exits 1 before any step runs, with the reason on stderr and nothing on stdout. The same format runs on a live server through the `run_script` action, with `steps` as a list or `yaml` as a string.

## Format

```yaml
name: Inspect the desktop
on_error: stop
steps:
  - action: run_command
    command: echo ${env.GREETING}
    output_id: greeting
  - if:
      condition:
        type: output
        output_id: greeting
        path: [exit_code]
        equals: 0
      then:
        - action: desktop_screenshot
          path: /recordings/desk.png
          whLargest: 512
          output_id: shot
```

- `name` is optional and defaults to `unnamed`. `steps` is required.
- Any action from the [actions reference](api.md) can be a step, with its parameters beside `action`, plugin actions included.
- `output_id` collects a successful step's `data` under `outputs`. Screenshots are collected as `data:image/png;base64,...` strings.
- `${env.NAME}` anywhere in a step's string values is replaced with the container's environment variable, or an empty string.
- `on_error: stop` (the default) ends at the first failed step; `continue` runs the rest.

## Control nodes

| Node | Shape |
| --- | --- |
| `if` | `condition`, `then` (steps), optional `else` (steps) |
| `repeat` | `count` (up to 100) and `steps` |
| `while` | `condition`, `max_iterations` (required, up to 100) and `steps` |

A `while` loop whose condition still matches after `max_iterations` fails with `while loop reached max_iterations`. Control nodes appear in `step_results` with their nested results under `data`.

A top-level condition can wait: add `timeout` (up to 60 seconds) and it is polled every 0.1 seconds until it matches. Nested conditions cannot set one.

| Condition `type` | Fields |
| --- | --- |
| `output` | `output_id`, optional `path` (keys and list indexes), then `equals` or `exists` |
| `all`, `any` | `conditions` (list) |
| `not` | `condition` |
| `element`, `text`, `url`, `javascript` | Page conditions. They need an `eval` action, which this image does not have; a plugin that adds one, such as a browser, makes them work. |

Nesting is limited to 8 levels, and a script runs at most 1000 steps inside loops.

## Output

```json
{
  "name": "Inspect the desktop",
  "success": true,
  "steps_executed": 2,
  "steps_total": 2,
  "duration": 0.125,
  "step_results": [
    {
      "step": 1,
      "action": "run_command",
      "duration": 0.022,
      "success": true,
      "data": {
        "exit_code": 0,
        "stdout": "hello\n"
      }
    }
  ],
  "outputs": {
    "greeting": {
      "exit_code": 0,
      "stdout": "hello\n"
    },
    "shot": "data:image/png;base64,iVBORw0KGgo..."
  }
}
```

This output is shortened; each step result is the action's full response (`success`, `timestamp`, `data`, and `error` when it failed) plus `step`, `action` and `duration`. `outputs` is left out when no step set `output_id`.
