---
title: Development
description: Build the image, run lint, unit and Docker-backed integration tests, and the security scan, all inside containers.
nav_order: 9
---

# Development

Every check runs in Docker through the Makefile. Run `make help` for the full list.

| Command | Does |
| --- | --- |
| `make build` | Build `psyb0t/auto-linux-desk:latest`. |
| `make build-test` | Build the test-tagged image. |
| `make dev-image` | Build the runtime image and a development image on top of it with ruff, shellcheck, the Docker CLI and the security tools. |
| `make shell` | Open a shell in the development image. |
| `make lint` | ruff check, ruff format check and shellcheck. |
| `make format`, `make lint-fix` | Apply ruff formatting and safe fixes. |
| `make test-unit` | Every `tests/test_*.py` in a read-only container. |
| `make test` | Build a test image and run the integration suite in `test.sh` against real containers. Pass names to run some: `make test TEST_ARGS="test_keybindings test_run_command"`. |
| `make sec` | semgrep, bandit and pip-audit, merged into `sec.sarif`. |
| `make docs-build` | Build this site with the GitHub Pages image into `.testing/docs-site`. |
| `make agent-dev-image` | Build the isolated Node development image for the MCP bridge. |
| `make agent-check` | Install the bridge's locked dependencies with lifecycle scripts disabled, check JavaScript syntax and exercise invalid configuration without networking. |
| `make pkg-lock` | Refresh the bridge's pnpm lockfile. New dependency releases must be at least seven days old. |
| `make clean` | Remove this project's local images. |

## Layout

| Path | Holds |
| --- | --- |
| [`src/autolinuxdesk/`](https://github.com/psyb0t/docker-auto-linux-desk/tree/main/src/autolinuxdesk) | The server package: registry, actions, MCP tools, input planners and executor, windows, processes, key bindings and accessibility. |
| [`entrypoint.sh`](https://github.com/psyb0t/docker-auto-linux-desk/blob/main/entrypoint.sh) | Ownership fixes, root hooks, privilege drop, Xvfb, Openbox, VNC and the server. |
| [`docker/configure-openbox.py`](https://github.com/psyb0t/docker-auto-linux-desk/blob/main/docker/configure-openbox.py) | Writes the Openbox config from `docker/keymap.json` at build time and for a `KEYBINDINGS_FILE` override at startup. Prints the keyboard docs table with `--markdown`. |
| [`tests/`](https://github.com/psyb0t/docker-auto-linux-desk/tree/main/tests) | Unit tests (`test_*.py`), integration modules (`test_*.sh`) and test apps, including a tk window that logs X input events. |

The integration tests measure humanized input through a real X client: the event logger records pointer motion, button holds, double-click recognition, typed characters and wheel notches, and the tests check them against human ranges.

## Agent packaging

The [shared agent directory](https://github.com/psyb0t/docker-auto-linux-desk/tree/main/.agents) contains the desktop-control skill, passive Claude Code and Codex manifests, and a separate OpenClaw MCP bridge package. The bridge's dependencies and lockfile live beside its `package.json`. `make agent-check` copies the package into a temporary container filesystem, so dependency installation does not modify the checkout.

## Release pipeline

The [pipeline](https://github.com/psyb0t/docker-auto-linux-desk/blob/main/.github/workflows/pipeline.yml) checks branch pushes before building and publishing the multi-platform image. A version tag waits for the default branch's pipeline, promotes its image and creates the release. ClawHub publication explicitly selects the desktop skill and bridge package; MCP Registry publication uses GitHub OIDC. GitHub Pages builds this `docs/` directory separately from the default branch.
