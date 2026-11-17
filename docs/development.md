---
title: Development
description: Build the image, run lint, unit and Docker-backed integration tests, and the security scan, all inside containers.
nav_order: 7
---

# Development

Every check runs in Docker through the Makefile. Run `make help` for the full list.

| Command | Does |
| --- | --- |
| `make build` | Build `psyb0t/auto-linux-desk:latest`. |
| `make dev-image` | Build the runtime image and a development image on top of it with ruff, shellcheck, the Docker CLI and the security tools. |
| `make lint` | ruff check, ruff format check and shellcheck. |
| `make format`, `make lint-fix` | Apply ruff formatting and safe fixes. |
| `make test-unit` | Every `tests/test_*.py` in a read-only container. |
| `make test` | Build a test image and run the integration suite in `test.sh` against real containers. Pass names to run some: `make test TEST_ARGS="test_keybindings test_run_command"`. |
| `make sec` | semgrep, bandit and pip-audit, merged into `sec.sarif`. |
| `make docs-build` | Build this site with the GitHub Pages image into `.testing/docs-site`. |

## Layout

| Path | Holds |
| --- | --- |
| [`src/autolinuxdesk/`](https://github.com/psyb0t/docker-auto-linux-desk/tree/main/src/autolinuxdesk) | The server package: registry, actions, MCP tools, input planners and executor, windows, processes, key bindings. |
| [`entrypoint.sh`](https://github.com/psyb0t/docker-auto-linux-desk/blob/main/entrypoint.sh) | Ownership fixes, root hooks, privilege drop, Xvfb, Openbox, VNC and the server. |
| [`docker/configure-openbox.py`](https://github.com/psyb0t/docker-auto-linux-desk/blob/main/docker/configure-openbox.py) | Writes the Openbox config and its key bindings at build time. |
| [`tests/`](https://github.com/psyb0t/docker-auto-linux-desk/tree/main/tests) | Unit tests (`test_*.py`), integration modules (`test_*.sh`) and test apps, including a tk window that logs X input events. |

The integration tests measure humanized input through a real X client: the event logger records pointer motion, button holds, double-click recognition, typed characters and wheel notches, and the tests check them against human ranges.
