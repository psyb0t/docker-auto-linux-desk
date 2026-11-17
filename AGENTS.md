# AGENTS.md

Guidance for coding agents working in this repository. Read it and the files in `.agents/rules/` before changing anything.

## What this project is

A Docker image that runs a virtual Linux desktop (Xvfb, Openbox, x11vnc, noVNC) and a server, `autolinuxdesk`, that drives it over a JSON HTTP API, MCP and YAML scripts. It is the base image of `psyb0t/stealthy-auto-browse`, which loads a browser plugin through the registry. Treat every action name, parameter, response field, environment variable and registry method as public: derived images and agents depend on them.

## Ground rules

- **Stay in scope.** Do the change you were asked for. Propose anything extra; do not do it.
- **Releases are cut by the maintainer.** Do not commit, push, tag, or edit a released CHANGELOG section unless told to in that turn.
- **Docker is the only dependency.** All tooling runs in containers through `make`. Do not install tools on the host.
- **Clean up what you start.** Remove only containers and images you created.
- **No real data in prompts, fixtures or docs.** Use obvious placeholders.

## Build and check

```bash
make build
make lint
make test-unit
make test
make test TEST_ARGS="test_keybindings test_run_command"
make docs-build
make help
```

Before calling a change done: `make lint`, `make test-unit`, and the integration tests that cover it. Changes to the Dockerfile, entrypoint, input or server need the full `make test`.

## Layout

```
Dockerfile                  # runtime image; installs the package system-wide
entrypoint.sh               # ownership fixes, entrypoint.d hooks, gosu, Xvfb, Openbox, VNC, server
docker/configure-openbox.py # Openbox rc.xml: one desktop and the key bindings
src/autolinuxdesk/
  server.py                 # FastAPI app, auth and trace middleware, MCP mount, script mode, main()
  registry.py               # actions, MCP tools, routes, screenshots, hooks, plugin loading
  desk.py                   # shared state, settings from the environment, dispatch
  actions.py                # base actions
  mcp_tools.py              # base MCP tools
  input_actions.py          # humanized input actions over a Surface
  surface.py                # coordinate surface; the screen by default
  system.py human_*.py      # input executor and planners (shared with stealthy-auto-browse)
  windows.py processes.py keybindings.py
tests/                      # test_*.py unit tests, test_*.sh integration modules, apps/
docs/                       # GitHub Pages site
```

See `.agents/rules/` for the rules on each area.
