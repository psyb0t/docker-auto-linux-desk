---
title: Plugins and derived images
description: Build an image on auto-linux-desk and load Python plugins that add or replace actions, MCP tools, routes, hooks and the input surface.
nav_order: 8
---

# Plugins and derived images

auto-linux-desk works on its own, and it can also be the base of your own image. A derived image installs its software and a Python plugin that registers actions for it, next to the desktop actions. A browser image, for example, adds the browser and actions that drive it.

## License

auto-linux-desk is licensed under the [AGPL-3.0-only](https://github.com/psyb0t/docker-auto-linux-desk/blob/main/LICENSE). A plugin runs inside the server's Python process, so an image that ships a plugin with auto-linux-desk is a work based on it and must be released under the AGPL-3.0 as well. Programs the image installs and only starts, such as a browser, keep their own licenses. Clients that only call the HTTP or MCP API are not affected.

## A derived image

```dockerfile
FROM psyb0t/auto-linux-desk:latest

USER root
RUN apt-get update \
    && apt-get install -y --no-install-recommends gedit \
    && rm -rf /var/lib/apt/lists/*

COPY my_plugin/ /opt/my-plugin/my_plugin/
ENV PYTHONPATH=/opt/my-plugin \
    AUTO_LINUX_DESK_PLUGINS=my_plugin \
    DESK_BANNER="MY DESK"
```

The first-party base uses `:latest` so fixes reach derived builds. Rebuild the derived image to pick up a new base. The entrypoint stays the base one; it starts `python -m autolinuxdesk`, which loads the plugins before the server starts. These in-process Python plugins are different from the client-side agent plugins described in [MCP and agent integrations](mcp.md).

These variables shape the entrypoint for a derived image:

| Variable | Default | Effect |
| --- | --- | --- |
| `DESK_HOME` | `/home/desk` | Home directory of the desktop user, chowned for `PUID` and `PGID`. |
| `DESK_WRITABLE_DIRS` | `/userdata /recordings` | Space-separated directories chowned for `PUID` and `PGID`. |
| `DESK_BANNER` | `AUTO-LINUX-DESK` | Startup banner title. |
| `DESK_EXEC_ENABLED` | `true` | Set `false` in the image to ship without `run_command` and `launch_app`. |
| `DESK_SUDO_ENABLED` | `false` | Opt in to passwordless sudo for the desktop UID. See [installation and security](installation.md#passwordless-sudo). |
| `DESK_DARK_MODE` | `false` | Set `true` in the image to ship a dark desktop. See [dark mode](installation.md#dark-mode). |
| `AUTO_LINUX_DESK_PLUGINS` | unset | Comma-separated module names. |

To rename the desktop user while keeping UID 1000, run `usermod -l <name> -d /home/<name> -m desk` and `groupmod -n <name> desk`, then set `DESK_HOME`. Root setup that must run on every start goes in `/etc/auto-linux-desk/entrypoint.d/*.sh`; see [installation](installation.md#entrypoint-hooks).

## A plugin

A plugin is a module with `register(registry)`. It runs once, before the server starts. An import error or exception stops startup with the plugin's name in the message.

```python
from autolinuxdesk.responses import ActionError, ok


async def open_file(cmd: dict, desk) -> dict:
    path = cmd.get("path")
    if not isinstance(path, str):
        raise ActionError("path must be a string")
    return ok(desk.processes.launch({"command": ["gedit", path]}))


def register(registry) -> None:
    registry.register_action("open_file", open_file)

    @registry.mcp_tool()
    async def open_file_tool(path: str) -> str:
        """Open a file in the text editor."""
        return str(await registry.call("open_file", path=path))
```

An action handler is `async (cmd, desk) -> dict`. Return `ok(data)` or `fail(error)` from `autolinuxdesk.responses`, or raise `ActionError`. `desk` holds the shared state: `system` (humanized input), `recorder`, `clipboard`, `events`, `processes`, `settings`, `surface`, and `extensions`, a dict for the plugin's own state.

## Registry

| Method | Use |
| --- | --- |
| `register_action(name, handler, handoff_safe=False, replace=False)` | Add an action. A duplicate name fails unless `replace=True`. `handoff_safe` lets it run during a handoff. |
| `action(name, ...)` | Decorator form. |
| `remove_action(name)` | Drop an action, including a base one. |
| `register_mcp_tool(fn, name=None, replace=False)`, `mcp_tool(...)` | Add an MCP tool. The function signature and docstring become its schema and description. |
| `remove_mcp_tool(name)` | Drop a tool. |
| `call(action, **params)` | Dispatch an action under the request lock, for MCP tools. |
| `set_mcp_identity(name, instructions)` | Change the MCP server name and instructions. |
| `set_mcp_mode("full" or "script_only")` | `script_only` exposes only `run_script`. |
| `register_route(method, path, handler)` | Add an HTTP route; the handler is a FastAPI endpoint. Auth applies. |
| `register_screenshot(name, provider, replace=False)` | Serve `GET /screenshot/<name>` from `async provider(desk, query_params) -> bytes`. `query_params` is the request's Starlette `QueryParams`: `get()` reads one value, `getlist()` a repeated parameter. Raising `ActionError` returns 400. |
| `register_state(provider)` | Merge `async provider(desk) -> dict` into `GET /state`. |
| `register_health(check)` | `async check(desk) -> {"ok": bool, ...}`; any false answer makes `/health` return 503. |
| `register_request_guard(guard)` | `guard(action, cmd)` returns an error string to refuse a `POST /` request, or `None`. |
| `on_startup(hook)`, `on_shutdown(hook)` | `async hook(desk)`. Startup hooks run after the input system is ready and before the server listens or a script runs. |
| `set_surface(surface)` | Change the coordinate space of input actions; see below. |
| `set_handoff_activity(provider)` | `async provider(desk, stop) -> dict` that counts human input during a handoff. |

## Surfaces

Input actions take coordinates relative to the active surface. The default `autolinuxdesk.surface.Surface` is the whole screen. A plugin can subclass it so that coordinates start at a window's content area, as a browser viewport does:

| Method | Default | Override to |
| --- | --- | --- |
| `refresh_offset(system)` | leaves `system.window_offset` alone | set `system.window_offset` to where the surface origin is on screen; called before every pointer move |
| `size(system)` | screen size | return the surface's `{"w", "h"}` |
| `scroll_y()` | `None` | return the scroll position, which enables `input_actions.SCROLL_POSITION_ACTIONS` |
| `editable_focused()` | `False` | report whether a text field has focus |
| `typing_guard(text)` | `None`, typos allowed | return an object with `reason`, `is_allowed`, `verify(text)` and `dispose()` to refuse typos in risky fields and check the typed value |

`autolinuxdesk.actions.input_action(handler)` adapts an `input_actions` handler to the registry signature, for registering `SCROLL_POSITION_ACTIONS` or wrapping a base input action.
