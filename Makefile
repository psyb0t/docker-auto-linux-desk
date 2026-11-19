SHELL := /bin/bash

IMAGE_NAME := psyb0t/auto-linux-desk
TAG ?= latest
TEST_TAG ?= $(TAG)-test
DEV_BASE_IMAGE := $(IMAGE_NAME):dev-base
DEV_IMAGE := $(IMAGE_NAME):dev
AGENT_DEV_IMAGE := $(IMAGE_NAME):agent-dev
AGENT_PLUGIN_DIR := .agents/plugins/auto-linux-desk
PROJECT_ROOT := $(CURDIR)
DOCS_IMAGE := ghcr.io/actions/jekyll-build-pages:v1.0.13@sha256:6791ebfd912185ed59bfb5fb102664fa872496b79f87ff8b9cfba292a7345041
TEST_ARGS ?=
PYTHON_SOURCES := src/autolinuxdesk/*.py tests/*.py tests/apps/*.py
UNIT_TESTS := $(sort $(wildcard tests/test_*.py))

UID := $(shell id -u)
GID := $(shell id -g)
DOCKER_SOCK := /var/run/docker.sock
DOCKER_GID := $(shell stat -c '%g' $(DOCKER_SOCK) 2>/dev/null || echo 0)

DEV_RUN_BASE := docker run --rm --init --read-only \
	--tmpfs /tmp:rw,noexec,nosuid,size=512m \
	--tmpfs /work-env:rw,exec,nosuid,size=512m \
	--user $(UID):$(GID) \
	-e HOME=/tmp \
	-e PYTHONDONTWRITEBYTECODE=1 \
	-e PYTHONPATH=/work/src \
	-e RUFF_CACHE_DIR=/work-env/ruff-cache \
	-w /work

DEV_RUN := $(DEV_RUN_BASE) -v "$(PROJECT_ROOT):/work:ro" $(DEV_IMAGE)
DEV_RUN_WRITE := $(DEV_RUN_BASE) -v "$(PROJECT_ROOT):/work" $(DEV_IMAGE)

AGENT_RUN := docker run --rm --init --read-only \
	--tmpfs /tmp:rw,noexec,nosuid,size=128m \
	--tmpfs /work-env:rw,exec,nosuid,size=512m,mode=1777 \
	--user $(UID):$(GID) -e HOME=/tmp \
	-v "$(PROJECT_ROOT):/work:ro" -w /work-env \
	$(AGENT_DEV_IMAGE)

DEV_RUN_DIND := docker run --rm --init --read-only \
	--tmpfs /tmp:rw,noexec,nosuid,size=512m \
	--tmpfs /work-env:rw,exec,nosuid,size=512m \
	--user $(UID):$(GID) \
	--group-add $(DOCKER_GID) \
	-e HOME=/tmp \
	-e PYTHONDONTWRITEBYTECODE=1 \
	-e TEST_DOCKER_NETWORK_ATTACH=true \
	-v "$(PROJECT_ROOT):$(PROJECT_ROOT)" \
	-v "$(DOCKER_SOCK):$(DOCKER_SOCK)" \
	-w "$(PROJECT_ROOT)" \
	$(DEV_IMAGE)

.DEFAULT_GOAL := help
.PHONY: help dev-image shell build build-test lint lint-fix format test test-unit sec generate clean docs-build
.PHONY: agent-dev-image agent-check pkg-lock

help: ## Show supported development commands.
	@awk 'BEGIN {FS = ":.*##"} /^[a-zA-Z0-9_-]+:.*##/ {printf "%-16s %s\n", $$1, $$2}' $(MAKEFILE_LIST)

dev-image: ## Build the sandboxed development image.
	docker build -t $(DEV_BASE_IMAGE) .
	docker build --build-arg BASE_IMAGE=$(DEV_BASE_IMAGE) -f Dockerfile.dev -t $(DEV_IMAGE) .

agent-dev-image: ## Build the isolated Node tooling for the agent bridge.
	docker build --target agent-dev -f Dockerfile.dev -t $(AGENT_DEV_IMAGE) .

pkg-lock: agent-dev-image ## Refresh the MCP bridge lockfile without install scripts.
	$(AGENT_RUN) sh -ec 'cp -R /work/$(AGENT_PLUGIN_DIR) plugin; cd plugin; pnpm install --lockfile-only --ignore-scripts >&2; cat pnpm-lock.yaml' > $(AGENT_PLUGIN_DIR)/pnpm-lock.yaml

agent-check: agent-dev-image ## Check the locked bridge package, JavaScript syntax and input errors.
	$(AGENT_RUN) sh -ec 'cp -R /work/$(AGENT_PLUGIN_DIR) plugin; cd plugin; pnpm install --frozen-lockfile --ignore-scripts --store-dir /work-env/store; node --check bin/cli.js; node /work/tests/test_agent_bridge.mjs /work-env/plugin/bin/cli.js'

shell: dev-image ## Open a shell in the development image.
	$(DEV_RUN_WRITE) bash

build: ## Build the production image.
	docker build -t $(IMAGE_NAME):$(TAG) .

build-test: ## Build the test-tagged production image.
	docker build -t $(IMAGE_NAME):$(TEST_TAG) .

format: dev-image ## Format Python source files.
	$(DEV_RUN_WRITE) python -m ruff format $(PYTHON_SOURCES)

lint: dev-image ## Run Python and shell checks in Docker.
	$(DEV_RUN) python -m ruff check $(PYTHON_SOURCES)
	$(DEV_RUN) python -m ruff format --check $(PYTHON_SOURCES)
	$(DEV_RUN) shellcheck entrypoint.sh test.sh tests/*.sh scripts/*.sh

lint-fix: dev-image ## Apply safe Python lint fixes and formatting.
	$(DEV_RUN_WRITE) python -m ruff check --fix $(PYTHON_SOURCES)
	$(DEV_RUN_WRITE) python -m ruff format $(PYTHON_SOURCES)

test: dev-image ## Run the complete Docker-backed test suite.
	$(DEV_RUN_DIND) bash test.sh $(TEST_ARGS)

test-unit: dev-image ## Run in-process Python unit tests.
	@set -e; for t in $(UNIT_TESTS); do echo "== $$t"; $(DEV_RUN) python $$t; done

sec: dev-image ## Write security findings to sec.sarif for GitHub Security.
	$(DEV_RUN_WRITE) bash scripts/sec.sh

generate: ## This repository has no generated source.
	@:

docs-build: ## Build the GitHub Pages documentation locally.
	docker run --rm --user $(UID):$(GID) -e HOME=/tmp -e GITHUB_WORKSPACE=/work \
		-e GITHUB_REPOSITORY=psyb0t/docker-auto-linux-desk \
		-e INPUT_SOURCE=docs -e INPUT_DESTINATION=.testing/docs-site \
		-e INPUT_VERBOSE=false -v "$(PROJECT_ROOT):/work" $(DOCS_IMAGE)

clean: ## Remove only this project's local images.
	docker image rm $(DEV_IMAGE) $(DEV_BASE_IMAGE) $(IMAGE_NAME):$(TAG) $(IMAGE_NAME):$(TEST_TAG)
