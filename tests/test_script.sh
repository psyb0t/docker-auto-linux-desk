#!/bin/bash
# tests/test_script.sh - script mode (--script) and the run_script action:
# outputs, screenshots, on_error, control flow and the request lock.

# _script_run <yaml> [docker run args...]: run a script in a fresh container
# and print its stdout. The exit code is the container's.
_script_run() {
    local yaml="$1"
    shift
    docker run --rm -i "$@" "$IMAGE_NAME:$TEST_TAG" --script 2>/dev/null <<<"$yaml"
}

test_script_mode_outputs() {
    local out status
    set +e
    # shellcheck disable=SC2016 # ${env.X} and the shell code expand in the container.
    out=$(_script_run '
name: Outputs
on_error: stop
steps:
  - action: sleep
    duration: 0.2
  - action: desktop_screenshot
    output_id: full
  - action: desktop_screenshot
    path: /tmp/script-shot.png
    output_id: saved
  - action: desktop_screenshot
    whLargest: 200
    output_id: resized_largest
  - action: desktop_screenshot
    width: 300
    output_id: resized_width
  - action: desktop_screenshot
    width: 200
    height: 100
    output_id: resized_both
  - action: run_command
    command: printf %s "${env.SCRIPT_GREETING}"
    output_id: env
  - action: set_clipboard
    text: "script clipboard λ"
  - action: get_clipboard
    output_id: clipboard
  - action: human_pause
    duration: 0.1
    drift: false
    output_id: pause
  - action: ping
    output_id: ping
' -e SCRIPT_GREETING=hello-env)
    status=$?
    set -e
    assert_eq "$status" "0" "exit code 0" || return 1
    assert_eq "${out:0:1}" "{" "stdout starts with the JSON document" || return 1
    echo "$out" | python3 -c '
import base64, io, json, struct, sys
result = json.load(sys.stdin)
assert result["success"] is True, result
assert result["name"] == "Outputs"
assert result["steps_executed"] == result["steps_total"] == 11, result["steps_executed"]
outputs = result["outputs"]
def size(uri):
    assert uri.startswith("data:image/png;base64,"), uri[:40]
    data = base64.b64decode(uri.split(",", 1)[1])
    return struct.unpack(">II", data[16:24])
assert size(outputs["full"]) == (1920, 1080)
assert size(outputs["saved"]) == (1920, 1080)
assert result["step_results"][2]["data"]["path"] == "/tmp/script-shot.png", result["step_results"][2]
assert size(outputs["resized_largest"]) == (200, 112)
assert size(outputs["resized_width"]) == (300, 168)
assert size(outputs["resized_both"]) == (200, 100)
assert len(outputs["resized_largest"]) < len(outputs["full"])
assert outputs["env"]["stdout"] == "hello-env", outputs["env"]
assert outputs["clipboard"]["text"] == "script clipboard λ", outputs["clipboard"]
assert outputs["pause"]["duration"] == 0.1 and outputs["pause"]["drifts"] == 0, outputs["pause"]
assert outputs["ping"]["message"] == "pong"
' || {
        echo "  FAIL: unexpected script result: ${out:0:600}"
        return 1
    }
    echo "  OK: outputs, screenshots, env substitution, clipboard, pause"
}

test_script_mode_on_error() {
    local out status
    set +e
    out=$(_script_run '
name: Continue
on_error: continue
steps:
  - action: ping
  - action: no_such_action
  - action: ping
    output_id: after
')
    status=$?
    set -e
    assert_eq "$status" "1" "failed step exits 1" || return 1
    echo "$out" | python3 -c '
import json, sys
result = json.load(sys.stdin)
assert result["success"] is False
assert result["steps_executed"] == 3, result
assert result["outputs"]["after"]["message"] == "pong"
' || {
        echo "  FAIL: on_error continue: $out"
        return 1
    }
    echo "  OK: on_error continue runs every step"

    set +e
    out=$(_script_run '
name: Stop
on_error: stop
steps:
  - action: ping
  - action: no_such_action
  - action: ping
    output_id: should_not_run
')
    status=$?
    set -e
    assert_eq "$status" "1" "stopped script exits 1" || return 1
    echo "$out" | python3 -c '
import json, sys
result = json.load(sys.stdin)
assert result["success"] is False
assert result["steps_executed"] == 2, result
assert "should_not_run" not in result.get("outputs", {})
' || {
        echo "  FAIL: on_error stop: $out"
        return 1
    }
    echo "  OK: on_error stop skips the rest"

    out=$(_script_run '
name: Quiet
steps:
  - action: sleep
    duration: 0.1
')
    assert_eq "$(echo "$out" | python3 -c 'import json, sys; print("outputs" in json.load(sys.stdin))')" "False" "no outputs key without output_id"
}

# Control flow on output conditions; state lives in a file the steps share.
# shellcheck disable=SC2016 # The shell code runs in the container.
_CONTROL_FLOW_YAML='
name: Control Flow
on_error: stop
steps:
  - action: run_command
    command: rm -f /tmp/cf-repeat /tmp/cf-while; printf ready
    output_id: bootstrap
  - if:
      condition:
        type: all
        conditions:
          - type: output
            output_id: bootstrap
            path: [stdout]
            equals: ready
          - type: any
            conditions:
              - type: output
                output_id: missing
                exists: true
              - type: not
                condition:
                  type: output
                  output_id: missing
                  exists: true
      then:
        - action: run_command
          command: printf then-ran
          output_id: all_branch
      else:
        - action: run_command
          command: printf unexpected-else
          output_id: all_branch
  - if:
      condition:
        type: output
        output_id: bootstrap
        path: [exit_code]
        equals: 1
      then:
        - action: run_command
          command: printf unexpected-then
          output_id: else_branch
      else:
        - action: run_command
          command: printf else-ran
          output_id: else_branch
  - repeat:
      count: 3
      steps:
        - action: run_command
          command: echo x >> /tmp/cf-repeat; printf %s "$(wc -l < /tmp/cf-repeat)"
          output_id: repeat_count
  - while:
      condition:
        type: not
        condition:
          type: output
          output_id: while_count
          path: [stdout]
          equals: "2"
      max_iterations: 3
      steps:
        - action: run_command
          command: echo x >> /tmp/cf-while; printf %s "$(wc -l < /tmp/cf-while)"
          output_id: while_count
'

_CONTROL_FLOW_CHECK='
import json, sys
result = json.load(sys.stdin)
result = result.get("data", result)
assert result["success"] is True, result
assert result["steps_executed"] == result["steps_total"] == 5
outputs = result["outputs"]
assert outputs["all_branch"]["stdout"] == "then-ran"
assert outputs["else_branch"]["stdout"] == "else-ran"
assert outputs["repeat_count"]["stdout"] == "3"
assert outputs["while_count"]["stdout"] == "2"
steps = result["step_results"]
assert steps[1]["data"]["branch"] == "then"
assert steps[2]["data"]["branch"] == "else"
assert len(steps[3]["data"]["iterations"]) == 3
assert len(steps[4]["data"]["iterations"]) == 2
'

test_script_mode_control_flow() {
    local out
    out=$(_script_run "$_CONTROL_FLOW_YAML")
    echo "$out" | python3 -c "$_CONTROL_FLOW_CHECK" || {
        echo "  FAIL: control flow: ${out:0:600}"
        return 1
    }
    echo "  OK: all/any/not/output conditions, branches, repeat, while"
}

test_run_script_steps_and_yaml() {
    local resp
    resp=$(post '{"action":"run_script","name":"test_json","steps":[{"action":"ping","output_id":"ping"},{"action":"get_resolution","output_id":"res"},{"action":"run_command","command":"echo hi","output_id":"cmd"}]}')
    assert_success "$resp" "run_script steps" || return 1
    echo "$resp" | python3 -c '
import json, sys
data = json.load(sys.stdin)["data"]
assert data["name"] == "test_json"
assert data["success"] is True and data["steps_executed"] == data["steps_total"] == 3
assert data["outputs"]["ping"]["message"] == "pong"
assert data["outputs"]["res"]["width"] == 1920
' || return 1
    echo "  OK: JSON steps"
    resp=$(post "$(python3 -c 'import json; print(json.dumps({"action": "run_script", "yaml": "name: test_yaml\non_error: stop\nsteps:\n  - action: ping\n    output_id: ping\n"}))')")
    assert_success "$resp" "run_script yaml" || return 1
    assert_eq "$(echo "$resp" | json_get "['data']['name']")" "test_yaml" "yaml script name" || return 1
    assert_eq "$(echo "$resp" | json_get "['data']['outputs']['ping']['message']")" "pong" "yaml output" || return 1
    resp=$(post "$(python3 -c "import json, sys; print(json.dumps({'action': 'run_script', 'yaml': sys.argv[1]}))" "$_CONTROL_FLOW_YAML")")
    echo "$resp" | python3 -c "$_CONTROL_FLOW_CHECK" || {
        echo "  FAIL: run_script control flow: $resp"
        return 1
    }
    echo "  OK: control flow over the API"
    resp=$(post '{"action":"run_script","steps":[{"action":"human_pause","duration":0.1,"drift":false,"output_id":"pause"},{"action":"ping","output_id":"after_pause"}]}')
    echo "$resp" | python3 -c '
import json, sys
data = json.load(sys.stdin)["data"]
assert data["success"] is True and data["steps_executed"] == 2
assert data["outputs"]["pause"]["duration"] == 0.1 and data["outputs"]["pause"]["drifts"] == 0
assert data["outputs"]["after_pause"]["message"] == "pong"
' || return 1
    echo "  OK: human_pause step"
}

test_run_script_errors() {
    local resp
    resp=$(post '{"action":"run_script","on_error":"stop","steps":[{"action":"ping"},{"action":"no_such_action"},{"action":"ping"}]}')
    assert_success "$resp" "on_error stop wrapper" || return 1
    echo "$resp" | python3 -c '
import json, sys
data = json.load(sys.stdin)["data"]
assert data["success"] is False
assert data["steps_executed"] < data["steps_total"], data
' || return 1
    echo "  OK: on_error stop halts"
    resp=$(post '{"action":"run_script","on_error":"continue","steps":[{"action":"ping"},{"action":"no_such_action"},{"action":"ping","output_id":"final_ping"}]}')
    echo "$resp" | python3 -c '
import json, sys
data = json.load(sys.stdin)["data"]
assert data["success"] is False
assert data["steps_executed"] == data["steps_total"] == 3
assert "final_ping" in data["outputs"]
' || return 1
    echo "  OK: on_error continue runs every step"
    resp=$(post '{"action":"run_script"}')
    assert_failure "$resp" "no steps refused" || return 1
    echo "$resp" | json_get "['error']" | grep -qi required || {
        echo "  FAIL: no steps error: $resp"
        return 1
    }
    resp=$(post '{"action":"run_script","steps":[{"repeat":{"count":0,"steps":[{"action":"ping"}]}}]}')
    assert_failure "$resp" "repeat count 0 refused" || return 1
    echo "$resp" | json_get "['error']" | grep -q "repeat count" || {
        echo "  FAIL: repeat count error: $resp"
        return 1
    }
    # Page conditions need a plugin with an eval action; the base fails the step.
    resp=$(post '{"action":"run_script","steps":[{"if":{"condition":{"type":"javascript","expression":"true"},"then":[{"action":"ping"}]}}]}')
    assert_eq "$(echo "$resp" | json_get "['data']['step_results'][0]['error']")" "condition evaluation failed" "page condition fails cleanly without a page"
}

test_request_lock() {
    local start end total_ms pid1 pid2 pid3 health health_start health_ms
    start=$(date +%s%N)
    curl -sf --max-time 10 -X POST "$BASE" -H 'Content-Type: application/json' -d '{"action":"sleep","duration":2}' >/dev/null &
    pid1=$!
    sleep 0.1
    curl -sf --max-time 10 -X POST "$BASE" -H 'Content-Type: application/json' -d '{"action":"sleep","duration":2}' >/dev/null &
    pid2=$!
    wait "$pid1"
    wait "$pid2"
    end=$(date +%s%N)
    total_ms=$(((end - start) / 1000000))
    if [ "$total_ms" -lt 3500 ]; then
        echo "  FAIL: two 2s sleeps took ${total_ms}ms; actions are not serialized"
        return 1
    fi
    echo "  OK: actions serialized (${total_ms}ms)"
    curl -sf --max-time 10 -X POST "$BASE" -H 'Content-Type: application/json' -d '{"action":"sleep","duration":3}' >/dev/null &
    pid3=$!
    sleep 0.2
    health_start=$(date +%s%N)
    health=$(curl -sf --max-time 5 "$BASE/health")
    health_ms=$((($(date +%s%N) - health_start) / 1000000))
    wait "$pid3"
    assert_eq "$health" "ok" "/health answers during a locked action" || return 1
    if [ "$health_ms" -gt 500 ]; then
        echo "  FAIL: /health took ${health_ms}ms during a locked action"
        return 1
    fi
    echo "  OK: /health not blocked (${health_ms}ms)"
}

ALL_TESTS+=(
    test_script_mode_outputs
    test_script_mode_on_error
    test_script_mode_control_flow
    test_run_script_steps_and_yaml
    test_run_script_errors
    test_request_lock
)
