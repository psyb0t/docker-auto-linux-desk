#!/bin/bash
# tests/test_api.sh - core API, screenshots, events, MCP.

test_health_state_and_actions() {
    assert_eq "$(curl -sf "$BASE/health")" "ok" "health" || return 1
    local state
    state=$(curl -sf "$BASE/state")
    assert_eq "$(echo "$state" | json_get "['surface']['name']")" "screen" "state surface" || return 1
    assert_eq "$(echo "$state" | json_get "['resolution']['width']")" "1920" "state width" || return 1
    local actions
    actions=$(post '{"action":"list_actions"}' | json_get "['data']['actions']")
    for name in run_command launch_app desktop_list_windows desktop_keybindings system_click system_type run_script; do
        echo "$actions" | grep -q "'$name'" || {
            echo "  FAIL: missing action $name"
            return 1
        }
    done
    assert_failure "$(post '{"action":"no_such_action"}')" "unknown action" || return 1
    assert_eq "$(post '{"action":"get_resolution"}' | json_get "['data']['height']")" "1080" "get_resolution"
}

test_desktop_screenshots() {
    local out="$RESULTS_DIR/desktop.png"
    curl -sf -o "$out" "$BASE/screenshot/desktop" || return 1
    assert_eq "$(png_dimensions "$out")" "1920x1080" "full desktop screenshot" || return 1
    curl -sf -o "$out" "$BASE/screenshot/desktop?whLargest=512" || return 1
    assert_eq "$(png_dimensions "$out")" "512x288" "resized desktop screenshot" || return 1
    local resp
    resp=$(post '{"action":"desktop_screenshot","path":"/tmp/shot.png","width":320}')
    assert_success "$resp" "desktop_screenshot action" || return 1
    assert_eq "$(echo "$resp" | json_get "['data']['path']")" "/tmp/shot.png" "screenshot path" || return 1
    assert_eq "$(desk_sh 'python3 -c "import struct;f=open(\"/tmp/shot.png\",\"rb\");f.read(16);print(struct.unpack(\">II\",f.read(8)))"')" "(320, 180)" "saved screenshot size" || return 1
    assert_eq "$(curl -s -o /dev/null -w '%{http_code}' "$BASE/screenshot/nope")" "404" "unknown screenshot"
}

test_events_and_handoff() {
    local resp after
    after=$(post '{"action":"get_events","limit":1000}' | python3 -c "import sys,json; e=json.load(sys.stdin)['data']['events']; print(e[-1]['id'] if e else 0)")
    assert_success "$(post '{"action":"begin_handoff"}')" "begin handoff" || return 1
    assert_failure "$(post '{"action":"system_click","x":5,"y":5}')" "mutating action blocked during handoff" || return 1
    assert_success "$(post '{"action":"desktop_list_windows"}')" "read-only action allowed during handoff" || return 1
    assert_success "$(post '{"action":"end_handoff"}')" "end handoff" || return 1
    resp=$(post "{\"action\":\"get_events\",\"after_id\":$after}")
    echo "$resp" | grep -q handoff_started || {
        echo "  FAIL: no handoff_started event: $resp"
        return 1
    }
    echo "$resp" | grep -q handoff_ended || {
        echo "  FAIL: no handoff_ended event"
        return 1
    }
    echo "  OK: handoff events"
}

test_clipboard_roundtrip() {
    assert_success "$(post '{"action":"set_clipboard","text":"clip ✓ text"}')" "set clipboard" || return 1
    assert_eq "$(post '{"action":"get_clipboard"}' | json_get "['data']['text']")" "clip ✓ text" "clipboard roundtrip" || return 1
    assert_eq "$(desk_sh 'xclip -o -selection clipboard')" "clip ✓ text" "clipboard visible to X clients"
}

test_run_script_api() {
    local resp
    resp=$(post '{"action":"run_script","steps":[{"action":"run_command","command":"echo step","output_id":"cmd"},{"action":"get_resolution","output_id":"res"}]}')
    assert_success "$resp" "run_script" || return 1
    assert_eq "$(echo "$resp" | json_get "['data']['outputs']['cmd']['stdout']")" "step" "script output collected" || return 1
    resp=$(post '{"action":"run_script","yaml":"name: y\nsteps:\n  - action: sleep\n    duration: 0\n"}')
    assert_success "$resp" "run_script yaml"
}

test_mcp_tools() {
    local result
    result=$(python3 - "$BASE" <<'PY'
import json, sys, urllib.request
base = sys.argv[1]
def post(body, sid=None):
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if sid:
        headers["mcp-session-id"] = sid
    request = urllib.request.Request(base + "/mcp/", json.dumps(body).encode(), headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        text = response.read().decode()
        sid = response.headers.get("mcp-session-id") or sid
    data = [line[6:] for line in text.splitlines() if line.startswith("data: ")]
    return sid, json.loads(data[0]) if data else None
sid, _ = post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}})
post({"jsonrpc": "2.0", "method": "notifications/initialized"}, sid)
_, tools = post({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, sid)
names = sorted(tool["name"] for tool in tools["result"]["tools"])
_, called = post({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "run_command", "arguments": {"command": "echo mcp"}}}, sid)
_, shot = post({"jsonrpc": "2.0", "id": 4, "method": "tools/call", "params": {"name": "screenshot", "arguments": {"whLargest": 64}}}, sid)
print(json.dumps({"names": names, "called": called["result"]["content"][0]["text"], "shot": shot["result"]["content"][0]["type"]}))
PY
    ) || return 1
    echo "$result"
    for name in run_script run_command launch_app screenshot system_click system_type send_key desktop_list_windows desktop_keybindings desk_action; do
        echo "$result" | grep -q "\"$name\"" || {
            echo "  FAIL: MCP tool $name missing"
            return 1
        }
    done
    echo "$result" | grep -q 'mcp\\\\n' || echo "$result" | grep -q 'mcp\\n' || {
        echo "  FAIL: MCP run_command output"
        return 1
    }
    assert_eq "$(echo "$result" | json_get "['shot']")" "image" "MCP screenshot returns an image"
}

ALL_TESTS+=(
    test_health_state_and_actions
    test_desktop_screenshots
    test_events_and_handoff
    test_clipboard_roundtrip
    test_run_script_api
    test_mcp_tools
)
