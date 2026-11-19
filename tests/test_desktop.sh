#!/bin/bash
# tests/test_desktop.sh - windows, launched programs and window manager shortcuts.

_geometry() {
    window_info "$1" | python3 -c "import sys,json; w=json.load(sys.stdin); print(w['x'], w['y'], w['width'], w['height'])"
}

test_window_actions() {
    local id
    id=$(start_event_logger /tmp/win.jsonl "window probe") || {
        echo "  FAIL: event logger window did not appear"
        return 1
    }
    echo "  OK: window $id"
    assert_success "$(post "{\"action\":\"desktop_move_resize_window\",\"id\":\"$id\",\"x\":100,\"y\":100,\"width\":640,\"height\":480}")" "move/resize" || return 1
    sleep 0.5
    local geometry
    geometry=$(_geometry "$id")
    read -r _ _ w h <<<"$geometry"
    assert_eq "${w}x${h}" "640x480" "window resized" || return 1
    assert_success "$(post "{\"action\":\"desktop_set_window_state\",\"title\":\"window probe\",\"state\":\"maximize\"}")" "maximize" || return 1
    sleep 0.5
    read -r _ _ w _ <<<"$(_geometry "$id")"
    assert_eq "$w" "1920" "window maximized" || return 1
    assert_success "$(post "{\"action\":\"desktop_focus_window\",\"title\":\"WINDOW PROBE\"}")" "focus by title" || return 1
    assert_eq "$(window_info "$id" | json_get "['active']")" "True" "window active" || return 1
    assert_failure "$(post '{"action":"desktop_focus_window","title":"no such window"}')" "missing window" || return 1
    assert_failure "$(post '{"action":"desktop_set_window_state","title":"window probe","state":"spin"}')" "bad state" || return 1
    assert_success "$(post "{\"action\":\"desktop_close_window\",\"id\":\"$id\"}")" "close" || return 1
    sleep 1
    assert_eq "$(window_info "$id")" "" "window gone"
}

test_launch_and_kill() {
    local resp id
    resp=$(post '{"action":"launch_app","command":["sh","-c","echo hello-launch; sleep 60"]}')
    assert_success "$resp" "launch" || return 1
    id=$(echo "$resp" | json_get "['data']['id']")
    sleep 0.5
    resp=$(post '{"action":"list_launched","output":true}')
    echo "$resp" | grep -q hello-launch || {
        echo "  FAIL: launch output missing: $resp"
        return 1
    }
    resp=$(post "{\"action\":\"kill_launched\",\"id\":$id}")
    assert_eq "$(echo "$resp" | json_get "['data']['running']")" "False" "killed" || return 1
    assert_failure "$(post '{"action":"kill_launched","id":9999}')" "unknown id" || return 1
    assert_failure "$(post '{"action":"launch_app","command":["/no/such/program"]}')" "missing program"
}

test_keybindings() {
    local resp
    resp=$(post '{"action":"desktop_keybindings"}')
    assert_success "$resp" "desktop_keybindings" || return 1
    echo "$resp" | python3 -c "
import sys, json
data = json.load(sys.stdin)['data']
keys = {b['key']: b for b in data['keybindings']}
for key in ('C-A-t', 'C-A-Left', 'C-A-Right', 'C-A-m', 'C-A-b', 'C-A-1', 'A-F4', 'A-Tab'):
    assert key in keys, key
assert not [k for k in keys if 'W-' in k], 'no Super bindings'
assert keys['C-A-t']['send_key'] == ['ctrl+alt+t']
assert keys['C-A-t']['group'] == 'Focus'
assert data['source'].endswith('/.config/openbox/rc.xml'), data['source']
" || return 1
    echo "  OK: bindings listed"

    local before after id
    before=$(post '{"action":"desktop_list_windows"}' | json_get "['data']['count']")
    assert_success "$(post '{"action":"send_key","key":"ctrl+alt+t"}')" "terminal shortcut" || return 1
    for ((i = 0; i < 25; i += 1)); do
        after=$(post '{"action":"desktop_list_windows"}' | json_get "['data']['count']")
        [ "$after" -gt "$before" ] && break
        sleep 0.2
    done
    [ "$after" -gt "$before" ] || {
        echo "  FAIL: ctrl+alt+t opened no window"
        return 1
    }
    id=$(post '{"action":"desktop_list_windows"}' | python3 -c "import sys,json; print([w['id'] for w in json.load(sys.stdin)['data']['windows'] if 'XTerm' in w['wm_class']][0])")
    echo "  OK: terminal $id"
    post "{\"action\":\"desktop_focus_window\",\"id\":\"$id\"}" >/dev/null
    post '{"action":"send_key","key":"ctrl+alt+left"}' >/dev/null
    sleep 0.5
    read -r x _ w _ <<<"$(_geometry "$id")"
    if [ "$x" -gt 5 ] || [ "$w" -lt 900 ] || [ "$w" -gt 970 ]; then
        echo "  FAIL: ctrl+alt+left did not tile left: x=$x w=$w"
        return 1
    fi
    echo "  OK: tiled left"
    post '{"action":"send_key","key":"ctrl+alt+right"}' >/dev/null
    sleep 0.5
    read -r x _ _ _ <<<"$(_geometry "$id")"
    [ "$x" -ge 950 ] || {
        echo "  FAIL: ctrl+alt+right did not tile right: x=$x"
        return 1
    }
    echo "  OK: tiled right"
    post '{"action":"send_key","key":"ctrl+alt+t"}' >/dev/null
    sleep 1
    assert_eq "$(post '{"action":"desktop_list_windows"}' | json_get "['data']['count']")" "$after" \
        "ctrl+alt+t with a terminal open focuses it, no new window" || return 1
    post '{"action":"send_key","key":"ctrl+alt+m"}' >/dev/null
    sleep 0.5
    read -r x _ w _ <<<"$(_geometry "$id")"
    [ "$w" -ge 1900 ] || {
        echo "  FAIL: ctrl+alt+m did not maximize: w=$w"
        return 1
    }
    echo "  OK: maximized"
    post '{"action":"send_key","key":"alt+f4"}' >/dev/null
    sleep 1
    assert_eq "$(window_info "$id")" "" "alt+f4 closed the terminal"
}

test_accessibility() {
    local resp
    resp=$(post '{"action":"desktop_accessibility_tree"}')
    assert_success "$resp" "desktop_accessibility_tree reaches the AT-SPI bus" || return 1
    echo "$resp" | python3 -c "
import sys, json
data = json.load(sys.stdin)['data']
assert isinstance(data['apps'], list) and isinstance(data['nodes'], list), data
assert data['count'] == len(data['nodes'])
" || return 1
    echo "  OK: accessibility tree read"
    assert_failure "$(post '{"action":"desktop_accessibility_find"}')" "find without a query" || return 1
    assert_failure "$(post '{"action":"desktop_accessibility_action","id":":1.999:/org/a11y/atspi/accessible/1","invoke":0}')" \
        "action on an element that does not exist" || return 1
}

test_keymap_override() {
    local name="${CONTAINER_NAME}-keymap-invalid" base
    printf '%s\n' '{"bindings":[{"key":"ctrl+alt+z"}]}' >"$RESULTS_DIR/keymap-invalid.json"
    base=$(start_extra_container "$name" -e KEYBINDINGS_FILE=/keymap.json \
        -v "$RESULTS_DIR/keymap-invalid.json:/keymap.json:ro")
    if ! assert_eq "$(docker wait "$name")" "1" "invalid keymap fails startup" ||
        ! grep -Fq 'ERROR: KEYBINDINGS_FILE=/keymap.json is not a valid key map' <<<"$(docker logs "$name" 2>&1)"; then
        stop_extra_container "$name"
        return 1
    fi
    stop_extra_container "$name"

    name="${CONTAINER_NAME}-keymap-custom"
    printf '%s\n' '{"bindings":[{"key":"ctrl+alt+z","group":"Custom","description":"custom close","actions":[{"name":"Close"}]}]}' >"$RESULTS_DIR/keymap-custom.json"
    base=$(start_extra_container "$name" -e KEYBINDINGS_FILE=/keymap.json \
        -v "$RESULTS_DIR/keymap-custom.json:/keymap.json:ro")
    if ! wait_for_api "$base" 60; then
        docker logs "$name"
        stop_extra_container "$name"
        return 1
    fi
    if ! post_to "$base" '{"action":"desktop_keybindings"}' | python3 -c '
import json, sys
reply = json.load(sys.stdin)
assert reply["success"], reply
bindings = reply["data"]["keybindings"]
assert len(bindings) == 1, bindings
assert bindings[0]["send_key"] == ["ctrl+alt+z"], bindings
assert bindings[0]["description"] == "custom close", bindings
assert bindings[0]["group"] == "Custom", bindings
'; then
        stop_extra_container "$name"
        return 1
    fi
    stop_extra_container "$name"
    echo "  OK: custom keymap replaces and describes the whole map"
}

ALL_TESTS+=(
    test_window_actions
    test_launch_and_kill
    test_keybindings
    test_accessibility
    test_keymap_override
)
