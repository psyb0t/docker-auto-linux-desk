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
    local entry params expected
    for entry in "whLargest=512|512x288" "whLargest=256|256x144" "width=800|800x450" "height=300|533x300" "width=400&height=400|400x400"; do
        IFS='|' read -r params expected <<<"$entry"
        curl -sf -o "$out" "$BASE/screenshot/desktop?$params" || return 1
        assert_eq "$(png_dimensions "$out")" "$expected" "resized desktop screenshot ($params)" || return 1
    done
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

_clipboard_payload() {
    python3 -c 'import json,sys; print(json.dumps({"action":"set_clipboard","text":sys.argv[1]}))' "$1"
}

test_clipboard_roundtrip() {
    local text resp
    assert_success "$(post '{"action":"set_clipboard","text":"clip ✓ text"}')" "set clipboard" || return 1
    assert_eq "$(post '{"action":"get_clipboard"}' | json_get "['data']['text']")" "clip ✓ text" "clipboard roundtrip" || return 1
    assert_eq "$(desk_sh 'xclip -o -selection clipboard')" "clip ✓ text" "clipboard visible to X clients" || return 1

    # shellcheck disable=SC2016 # The command substitution is clipboard test data.
    text=$'quotes: "single" and '\''double'\''\nUnicode: café λ 🙂\nshell: $(touch /tmp/never-created)'
    assert_success "$(post "$(_clipboard_payload "$text")")" "set complex text" || return 1
    grep -Fq "$text" <<<"$(docker logs "$CONTAINER_NAME" 2>&1)" && {
        echo "  FAIL: clipboard contents appeared in container logs"
        return 1
    }
    resp=$(post '{"action":"get_clipboard"}')
    assert_eq "$(echo "$resp" | json_get "['data']['text']")" "$text" "exact complex text" || return 1
    assert_eq "$(echo "$resp" | json_get "['data']['length']")" "$(printf '%s' "$text" | wc -m | tr -d ' ')" "character count" || return 1
    assert_eq "$(echo "$resp" | json_get "['data']['bytes']")" "$(printf '%s' "$text" | wc -c | tr -d ' ')" "byte count" || return 1
    assert_eq "$(desk_sh 'test -e /tmp/never-created && echo created || echo absent')" "absent" "clipboard text never executed" || return 1

    assert_success "$(post "$(_clipboard_payload "")")" "set empty text" || return 1
    assert_eq "$(post '{"action":"get_clipboard"}' | json_get "['data']['text']")" "" "empty text roundtrip"
}

test_clipboard_validation() {
    local entry label payload expected
    for entry in \
        'missing|{"action":"set_clipboard"}|text required' \
        'null|{"action":"set_clipboard","text":null}|text must be a string' \
        'boolean|{"action":"set_clipboard","text":true}|text must be a string' \
        'number|{"action":"set_clipboard","text":42}|text must be a string' \
        'object|{"action":"set_clipboard","text":{}}|text must be a string' \
        'list|{"action":"set_clipboard","text":[]}|text must be a string'; do
        IFS='|' read -r label payload expected <<<"$entry"
        assert_eq "$(post "$payload" | json_get "['error']")" "$expected" "validation[$label]" || return 1
    done
    python3 - "$BASE" 1048576 <<'PY' || return 1
import json, sys, urllib.request
base, limit = sys.argv[1], int(sys.argv[2])
def post(text):
    body = json.dumps({"action": "set_clipboard", "text": text}).encode()
    request = urllib.request.Request(base, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request) as response:
        return json.load(response)
at_limit = post("a" * limit)
assert at_limit["success"] is True, at_limit
assert at_limit["data"] == {"length": limit, "bytes": limit}, at_limit
over = post("a" * (limit + 1))
assert over["success"] is False and over["error"] == f"clipboard text exceeds {limit} bytes", over
PY
    echo "  OK: 1 MiB limit"
}

# Paste the API clipboard into an X client and copy its selection back. The
# text stays in the Basic Multilingual Plane, which is all tk 8.6 handles.
test_clipboard_x_client_copy_paste() {
    local log=/tmp/clip.jsonl id paste_text="API to desktop paste λ ✓" copy_text="desktop copy to API café"
    id=$(start_event_logger "$log" "clipboard probe") || {
        echo "  FAIL: event logger window did not appear"
        return 1
    }
    post "{\"action\":\"desktop_focus_window\",\"id\":\"$id\"}" >/dev/null
    assert_success "$(post "$(_clipboard_payload "$paste_text")")" "seed clipboard" || return 1
    # A held ctrl+v: with instant the release lands while tk still waits for
    # the selection, so the logged content would predate the paste.
    assert_success "$(post '{"action":"send_key","key":"ctrl+v"}')" "ctrl+v" || return 1
    sleep 0.5
    assert_eq "$(desk_sh "cat $log" | python3 -c '
import json, sys
contents = [json.loads(l)["text"] for l in sys.stdin if l.strip() and json.loads(l)["type"] == "content"]
print(contents[-1])
')" "$paste_text" "pasted into the X client" || return 1
    post '{"action":"send_key","key":"ctrl+a"}' >/dev/null
    post '{"action":"send_key","key":"backspace"}' >/dev/null
    post "$(python3 -c 'import json, sys; print(json.dumps({"action": "system_type", "text": sys.argv[1]}))' "$copy_text")" >/dev/null
    assert_success "$(post '{"action":"send_key","key":"ctrl+a","instant":true}')" "select all" || return 1
    assert_success "$(post '{"action":"send_key","key":"ctrl+c","instant":true}')" "ctrl+c" || return 1
    sleep 0.3
    assert_eq "$(post '{"action":"get_clipboard"}' | json_get "['data']['text']")" "$copy_text" "copied from the X client"
}

test_clipboard_run_script() {
    local text="run_script clipboard should never be logged" resp
    resp=$(post "$(python3 -c 'import json,sys; print(json.dumps({"action":"run_script","steps":[{"action":"set_clipboard","text":sys.argv[1]},{"action":"get_clipboard","output_id":"clipboard"}]}))' "$text")")
    assert_success "$resp" "run_script clipboard" || return 1
    assert_eq "$(echo "$resp" | json_get "['data']['outputs']['clipboard']['text']")" "$text" "run_script clipboard output" || return 1
    grep -Fq "$text" <<<"$(docker logs "$CONTAINER_NAME" 2>&1)" && {
        echo "  FAIL: run_script clipboard contents appeared in container logs"
        return 1
    }
    echo "  OK: clipboard text kept out of the logs"
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
_, setdata = post({"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "set_clipboard_data", "arguments": {"format": "html", "text": "<b>mcp</b>"}}}, sid)
_, gethtml = post({"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "get_clipboard", "arguments": {"format": "html"}}}, sid)
assert json.loads(setdata["result"]["content"][0]["text"])["success"], setdata
assert json.loads(gethtml["result"]["content"][0]["text"])["data"]["text"] == "<b>mcp</b>", gethtml
print(json.dumps({"names": names, "called": called["result"]["content"][0]["text"], "shot": shot["result"]["content"][0]["type"]}))
PY
    ) || return 1
    echo "$result"
    for name in run_script run_command launch_app screenshot system_click paste_text system_type send_key set_clipboard_data desktop_list_windows desktop_keybindings desk_action; do
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

# Generic tool contracts over MCP: session, clipboard, events, handoff,
# pause, desk_action, run_script control flow and unknown tools.
test_mcp_tool_contracts() {
    python3 - "$BASE" <<'PY'
import json, sys, urllib.error, urllib.request
base = sys.argv[1]
sid = None
def post(body):
    global sid
    headers = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if sid:
        headers["mcp-session-id"] = sid
    request = urllib.request.Request(base + "/mcp/", json.dumps(body).encode(), headers)
    with urllib.request.urlopen(request, timeout=30) as response:
        text = response.read().decode()
        sid = response.headers.get("mcp-session-id") or sid
    data = [line[6:] for line in text.splitlines() if line.startswith("data: ")]
    return json.loads(data[0]) if data else None
def call(name, **arguments):
    return post({"jsonrpc": "2.0", "id": 9, "method": "tools/call", "params": {"name": name, "arguments": arguments}})
def data(name, **arguments):
    response = json.loads(call(name, **arguments)["result"]["content"][0]["text"])
    assert response["success"] is True, (name, response)
    return response["data"]
init = post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test", "version": "1"}}})
assert sid and init, "no MCP session"
post({"jsonrpc": "2.0", "method": "notifications/initialized"})
print("  OK: initialize")
assert data("system_click", x=500, y=300)["landed_at"]
print("  OK: system_click")
assert data("desk_action", action="ping")["message"] == "pong"
print("  OK: desk_action")
text = "MCP clipboard café λ"
set_data = data("set_clipboard", text=text)
get_data = data("get_clipboard")
assert set_data["bytes"] == len(text.encode()) and get_data["text"] == text and get_data["length"] == len(text), get_data
assert data("set_clipboard_data", format="html", text="<b>x</b>")["format"] == "html"
print("  OK: clipboard tools")
assert isinstance(data("get_events", limit=5)["events"], list)
assert data("begin_handoff")["active"] is True
assert data("handoff_status")["active"] is True
assert data("end_handoff")["active"] is False
print("  OK: events and handoff")
pause = data("human_pause", duration=0.1, x=500, y=350, w=200, h=120, drift=False)
landed = pause["landed_at"]
assert pause["duration"] == 0.1 and pause["drifts"] == 0 and pause["parked"] is True, pause
assert 400 <= landed["x"] <= 600 and 290 <= landed["y"] <= 410, landed
print("  OK: human_pause parks inside its region")
script = data("run_script", steps=[
    {"action": "ping", "output_id": "pong"},
    {"if": {
        "condition": {"type": "output", "output_id": "pong", "path": ["message"], "equals": "pong"},
        "then": [{"action": "run_command", "command": "printf mcp-then", "output_id": "branch"}],
        "else": [{"action": "run_command", "command": "printf mcp-else", "output_id": "branch"}],
    }},
])
assert script["outputs"]["branch"]["stdout"] == "mcp-then", script
print("  OK: run_script control flow")
try:
    response = call("nonexistent_tool_xyz", foo="bar")
    assert response.get("error") is not None or response.get("result", {}).get("isError"), response
except urllib.error.HTTPError:
    pass
print("  OK: unknown tool is an error")
PY
}

ALL_TESTS+=(
    test_health_state_and_actions
    test_desktop_screenshots
    test_events_and_handoff
    test_clipboard_roundtrip
    test_clipboard_validation
    test_clipboard_x_client_copy_paste
    test_clipboard_run_script
    test_run_script_api
    test_mcp_tools
    test_mcp_tool_contracts
)
