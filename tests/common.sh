#!/bin/bash
# tests/common.sh - shared helpers and infrastructure, sourced by test.sh.
# Variables here are read by the test modules test.sh sources.
# shellcheck disable=SC2034

IMAGE_NAME="psyb0t/auto-linux-desk"
TEST_TAG="latest-test"
CONTAINER_NAME="auto-linux-desk-test"
INTERNAL_PORT="8080"
WORKDIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RESULTS_DIR="$WORKDIR/tests/results"
TEST_APPS="/testapps"
BASE=""
TEST_TOKEN="integration-token-not-a-secret"

EXTRA_CONTAINERS=()
ALL_TESTS=()

json_get() {
    python3 -c "import sys,json; print(json.load(sys.stdin)$1)"
}

png_dimensions() {
    python3 -c "
from struct import unpack
with open('$1','rb') as f:
    f.read(16)
    w,h = unpack('>II', f.read(8))
    print(f'{w}x{h}')
"
}

post_to() {
    curl -sf -X POST "$1" -H "Content-Type: application/json" "${@:3}" -d "$2"
}

post() {
    post_to "$BASE" "$1"
}

assert_success() {
    if ! echo "$1" | grep -qE '"success":\s*true'; then
        echo "  FAIL: $2: $1"
        return 1
    fi
    echo "  OK: $2"
}

assert_failure() {
    if ! echo "$1" | grep -qE '"success":\s*false'; then
        echo "  FAIL: $2: expected failure, got $1"
        return 1
    fi
    echo "  OK: $2"
}

assert_eq() {
    if [ "$1" != "$2" ]; then
        echo "  FAIL: $3: expected $2, got $1"
        return 1
    fi
    echo "  OK: $3"
}

container_ip() {
    docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$1"
}

wait_for_api() {
    local base_url="$1"
    local max_wait="${2:-30}"
    for ((i = 0; i < max_wait; i += 1)); do
        if curl -sf "$base_url/health" >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
    done
    return 1
}

# start_extra_container NAME [docker run args...] prints the API base URL.
start_extra_container() {
    local name="$1"
    shift
    docker rm -f "$name" >/dev/null 2>&1 || true
    docker run -d --name "$name" "$@" "$IMAGE_NAME:$TEST_TAG" >/dev/null
    EXTRA_CONTAINERS+=("$name")
    echo "http://$(container_ip "$name"):${INTERNAL_PORT}"
}

stop_extra_container() {
    docker rm -f "$1" >/dev/null 2>&1 || true
}

# Run a shell command in the main container through the API; print stdout.
desk_sh() {
    post "$(python3 -c 'import json,sys; print(json.dumps({"action":"run_command","command":sys.argv[1],"timeout_s":60}))' "$1")" |
        json_get "['data']['stdout']"
}

# Launch the event logger, wait for its window and print the window id.
start_event_logger() {
    local log="$1"
    local title="$2"
    desk_sh "rm -f $log" >/dev/null
    post "{\"action\":\"launch_app\",\"command\":[\"python3\",\"$TEST_APPS/event_logger.py\",\"$log\",\"$title\"]}" >/dev/null
    local id
    for ((i = 0; i < 50; i += 1)); do
        if desk_sh "grep -c mapped $log 2>/dev/null || true" | grep -q '^[1-9]'; then
            # The window can be mapped before the window manager lists it.
            id=$(post "{\"action\":\"desktop_list_windows\"}" |
                python3 -c "import sys,json; print(next((w['id'] for w in json.load(sys.stdin)['data']['windows'] if w['title']=='$title'), ''))")
            if [ -n "$id" ]; then
                echo "$id"
                return 0
            fi
        fi
        sleep 0.2
    done
    return 1
}

window_info() {
    post "{\"action\":\"desktop_list_windows\"}" |
        python3 -c "import sys,json; w=[w for w in json.load(sys.stdin)['data']['windows'] if w['id']=='$1']; print(json.dumps(w[0]) if w else '')"
}

setup() {
    mkdir -p "$RESULTS_DIR"
    echo "Building test image..."
    docker build -t "$IMAGE_NAME:$TEST_TAG" .
    docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
    echo "Starting test container..."
    docker run -d --name "$CONTAINER_NAME" \
        -v "$WORKDIR/tests/apps:$TEST_APPS:ro" \
        "$IMAGE_NAME:$TEST_TAG" >/dev/null
    BASE="http://$(container_ip "$CONTAINER_NAME"):${INTERNAL_PORT}"
    if ! wait_for_api "$BASE" 60; then
        echo "FAIL: API did not become ready"
        docker logs "$CONTAINER_NAME"
        exit 1
    fi
    echo "API ready at $BASE"
}

test_teardown() {
    # Close windows and programs a test left behind.
    post '{"action":"list_launched"}' |
        python3 -c "import sys,json; [print(p['id']) for p in json.load(sys.stdin)['data']['launched'] if p['running']]" |
        while read -r id; do
            post "{\"action\":\"kill_launched\",\"id\":$id,\"signal\":\"KILL\"}" >/dev/null || true
        done
    post '{"action":"list_launched","forget_finished":true}' >/dev/null || true
    post '{"action":"end_handoff"}' >/dev/null 2>&1 || true
}

cleanup() {
    echo "Cleaning up..."
    for c in "${EXTRA_CONTAINERS[@]}"; do
        docker rm -f "$c" >/dev/null 2>&1 || true
    done
    docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
    docker rmi "$IMAGE_NAME:$TEST_TAG" >/dev/null 2>&1 || true
}
