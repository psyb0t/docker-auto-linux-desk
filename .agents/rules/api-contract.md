# API contract

- Action names, parameters, response fields, MCP tool names and schemas, environment variables and registry methods are public. stealthy-auto-browse builds on them; renaming or removing one is a breaking change and needs a major version.
- A new action gets an MCP tool or a mention in the `desk_action` docstring, a row in `docs/api.md`, and tests.
- Handlers return `ok()` or `fail()` from `responses.py`, or raise `ActionError`. Read-only actions register with `handoff_safe=True`.
- `run_command` and `launch_app` must check `DESK_EXEC_ENABLED`. Anything else that executes arbitrary programs must check it too.
- Log program names only, never command arguments, clipboard contents or tokens.
