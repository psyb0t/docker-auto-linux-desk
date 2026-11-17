#!/bin/bash
# tests/test_exec.sh - run_command behavior and the DESK_EXEC_ENABLED switch.

test_run_command() {
    local resp
    resp=$(post '{"action":"run_command","command":"echo out; echo err >&2; exit 4"}')
    assert_eq "$(echo "$resp" | json_get "['data']['exit_code']")" "4" "exit code" || return 1
    assert_eq "$(echo "$resp" | json_get "['data']['stderr']")" "err" "stderr" || return 1
    resp=$(post '{"action":"run_command","command":["id","-u"]}')
    assert_eq "$(echo "$resp" | json_get "['data']['stdout']")" "1000" "runs as the desktop user" || return 1
    # shellcheck disable=SC2016 # Expanded inside the container.
    resp=$(post '{"action":"run_command","command":"echo $DISPLAY"}')
    assert_eq "$(echo "$resp" | json_get "['data']['stdout']")" ":99" "sees the display" || return 1
    resp=$(post '{"action":"run_command","command":"echo partial; sleep 30","timeout_s":1}')
    assert_failure "$resp" "timeout fails the action" || return 1
    assert_eq "$(echo "$resp" | json_get "['data']['stdout']")" "partial" "timeout keeps output" || return 1
    resp=$(post '{"action":"run_command","command":"head -c 3000000 /dev/zero | tr \"\\\\0\" x","timeout_s":30}')
    assert_eq "$(echo "$resp" | json_get "['data']['stdout_truncated']")" "True" "output truncated" || return 1
    resp=$(post '{"action":"run_command","command":"sleep 60 & echo detached","timeout_s":10}')
    assert_eq "$(echo "$resp" | json_get "['data']['timed_out']")" "False" "background child does not block" || return 1
    assert_failure "$(post '{"action":"run_command","command":"true","timeout_s":601}')" "timeout bound"
}

test_exec_disabled() {
    local name="${CONTAINER_NAME}-noexec" base
    base=$(start_extra_container "$name" -e DESK_EXEC_ENABLED=false)
    if ! wait_for_api "$base" 60; then
        docker logs "$name" | tail -20
        stop_extra_container "$name"
        return 1
    fi
    local resp
    resp=$(post_to "$base" '{"action":"run_command","command":"id"}')
    echo "$resp" | grep -q "DESK_EXEC_ENABLED=false" || {
        echo "  FAIL: run_command not refused: $resp"
        stop_extra_container "$name"
        return 1
    }
    resp=$(post_to "$base" '{"action":"launch_app","command":["xterm"]}')
    echo "$resp" | grep -q "DESK_EXEC_ENABLED=false" || {
        echo "  FAIL: launch_app not refused: $resp"
        stop_extra_container "$name"
        return 1
    }
    for ((i = 0; i < 50; i += 1)); do
        grep -q "Ctrl+C to exit" <<<"$(docker logs "$name" 2>&1)" && break
        sleep 0.2
    done
    grep -q "WARNING: run_command" <<<"$(docker logs "$name" 2>&1)" && {
        echo "  FAIL: exec warning printed while exec is off"
        stop_extra_container "$name"
        return 1
    }
    assert_success "$(post_to "$base" '{"action":"desktop_list_windows"}')" "other actions still work"
    stop_extra_container "$name"
}

test_auth_token() {
    local name="${CONTAINER_NAME}-auth" base
    base=$(start_extra_container "$name" -e "AUTH_TOKEN=$TEST_TOKEN")
    if ! wait_for_api "$base" 60; then
        docker logs "$name" | tail -20
        stop_extra_container "$name"
        return 1
    fi
    local code
    code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$base" -d '{"action":"run_command","command":"id"}')
    assert_eq "$code" "401" "run_command without token" || {
        stop_extra_container "$name"
        return 1
    }
    code=$(curl -s -o /dev/null -w '%{http_code}' -X POST "$base/mcp/" -H 'Content-Type: application/json' -d '{}')
    assert_eq "$code" "401" "MCP without token" || {
        stop_extra_container "$name"
        return 1
    }
    code=$(curl -s -o /dev/null -w '%{http_code}' "$base/screenshot/desktop?auth_token=$TEST_TOKEN")
    assert_eq "$code" "401" "token in query string refused" || {
        stop_extra_container "$name"
        return 1
    }
    assert_success "$(post_to "$base" '{"action":"run_command","command":"id"}' -H "Authorization: Bearer $TEST_TOKEN")" "run_command with token" || {
        stop_extra_container "$name"
        return 1
    }
    for ((i = 0; i < 50; i += 1)); do
        grep -q "Ctrl+C to exit" <<<"$(docker logs "$name" 2>&1)" && break
        sleep 0.2
    done
    grep -q "WARNING: run_command" <<<"$(docker logs "$name" 2>&1)" && {
        echo "  FAIL: exec warning printed although AUTH_TOKEN is set"
        stop_extra_container "$name"
        return 1
    }
    stop_extra_container "$name"
    echo "  OK: auth"
}

ALL_TESTS+=(
    test_run_command
    test_exec_disabled
    test_auth_token
)
