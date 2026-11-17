#!/bin/bash
# tests/test_input.sh - humanized input measured by a real X client.

_events() {
    desk_sh "cat $1"
}

test_humanized_input_reaches_x_clients() {
    local log=/tmp/input.jsonl id
    id=$(start_event_logger "$log" "input probe") || {
        echo "  FAIL: event logger window did not appear"
        return 1
    }
    post "{\"action\":\"desktop_focus_window\",\"id\":\"$id\"}" >/dev/null
    # The window covers the middle of the screen: 480..1440 x 270..810.
    assert_success "$(post '{"action":"mouse_move","x":600,"y":400}')" "move" || return 1
    assert_success "$(post '{"action":"system_click","x":900,"y":500,"w":40,"h":20}')" "click" || return 1
    assert_success "$(post '{"action":"system_double_click","x":800,"y":600}')" "double-click" || return 1
    assert_success "$(post '{"action":"system_type","text":"Hello, desk!"}')" "type" || return 1
    assert_success "$(post '{"action":"scroll","amount":-4,"x":900,"y":500}')" "scroll" || return 1
    assert_success "$(post '{"action":"system_right_click","x":700,"y":450}')" "right-click" || return 1
    sleep 0.5

    _events "$log" | python3 -c "
import json, statistics, sys
events = [json.loads(line) for line in sys.stdin if line.strip()]
moves = [e for e in events if e['type'] == 'move']
downs = [e for e in events if e['type'] == 'down']
ups = [e for e in events if e['type'] == 'up']
keys = [e for e in events if e['type'] == 'key']
doubles = [e for e in events if e['type'] == 'double']
left = [(d, u) for d, u in zip([e for e in downs if e['button'] == 1], [e for e in ups if e['button'] == 1])]
holds = [u['t'] - d['t'] for d, u in left]
wheel = [e for e in downs if e['button'] == 5]
right = [e for e in downs if e['button'] == 3]
typed = ''.join(e['char'] for e in keys if e['char'])
gaps = [b['t'] - a['t'] for a, b in zip(keys, keys[1:])]
click = left[0][0]
print(json.dumps({'moves': len(moves), 'left_clicks': len(left), 'doubles': len(doubles), 'holds': [round(h, 3) for h in holds], 'typed': typed, 'wheel': len(wheel), 'right': len(right), 'click_at': [click['x'], click['y']]}))
assert len(moves) >= 20, 'pointer teleported instead of moving along a path'
# tk hands the second press of a double-click only to <Double-Button-1>.
assert len(left) == 2, f'expected 2 single left presses, got {len(left)}'
assert len(doubles) >= 1, 'double-click not recognised by the toolkit'
assert all(0.02 <= h <= 0.4 for h in holds), holds
assert abs(click['x'] - 900) <= 20 and abs(click['y'] - 500) <= 10, click
assert typed == 'Hello, desk!', typed
assert statistics.pstdev(gaps) > 0.01, 'key gaps are uniform'
assert len(wheel) == 4, f'expected 4 wheel notches, got {len(wheel)}'
assert len(right) == 1
" || return 1
    echo "  OK: input measured"
}

test_paste_text_replaces_the_field_with_human_keys() {
    local log=/tmp/paste.jsonl id
    id=$(start_event_logger "$log" "paste probe") || {
        echo "  FAIL: event logger window did not appear"
        return 1
    }
    post "{\"action\":\"desktop_focus_window\",\"id\":\"$id\"}" >/dev/null
    assert_success "$(post '{"action":"system_type","text":"old"}')" "type old text" || return 1
    local resp
    resp=$(post '{"action":"paste_text","text":"pasted ✓ line one\nline two","x":960,"y":540,"w":300,"h":200}')
    assert_success "$resp" "paste_text" || return 1
    assert_eq "$(echo "$resp" | json_get "['data']['replaced']")" "True" "replaced" || return 1
    sleep 0.5
    desk_sh "cat $log" | python3 -c "
import json, sys
events = [json.loads(line) for line in sys.stdin if line.strip()]
contents = [e['text'] for e in events if e['type'] == 'content']
assert contents[-1] == 'pasted ✓ line one\nline two', repr(contents[-1])
keys = [e for e in events if e['type'] == 'key']
names = [e['keysym'] for e in keys]
tail = names[names.index('o') + 1:] if 'o' in names else names
# ctrl+a, backspace, ctrl+v as real key presses, in order.
order = [n for n in tail if n in ('a', 'BackSpace', 'v')]
assert order == ['a', 'BackSpace', 'v'], (order, tail)
times = {n: e['t'] for e in keys for n in [e['keysym']] if n in ('a', 'BackSpace', 'v')}
gaps = [times['BackSpace'] - times['a'], times['v'] - times['BackSpace']]
assert all(g >= 0.07 for g in gaps), gaps
print('gaps', [round(g, 3) for g in gaps])
" || return 1
    echo "  OK: pasted over the old text with human key gaps"
    resp=$(post '{"action":"paste_text","text":" more","replace":false}')
    assert_success "$resp" "paste at the caret" || return 1
    sleep 0.3
    desk_sh "cat $log" | python3 -c "
import json, sys
contents = [json.loads(l)['text'] for l in sys.stdin if l.strip() and json.loads(l)['type'] == 'content']
assert contents[-1].endswith(' more') and contents[-1].startswith('pasted'), repr(contents[-1])
" || return 1
    echo "  OK: paste at the caret kept the text"
}

test_input_validation() {
    assert_failure "$(post '{"action":"system_click","x":1}')" "missing y" || return 1
    assert_failure "$(post '{"action":"scroll","amount":0}')" "zero scroll" || return 1
    assert_failure "$(post '{"action":"system_type","text":""}')" "empty text" || return 1
    assert_failure "$(post '{"action":"scroll_to_bottom_humanized"}')" "browser-only action absent"
}

# mouse_move ends where it says it landed; mouse_click presses right there.
test_pointer_lands_where_reported() {
    local log=/tmp/land.jsonl resp landed
    start_event_logger "$log" "landing probe" >/dev/null || {
        echo "  FAIL: event logger window did not appear"
        return 1
    }
    resp=$(post '{"action":"mouse_move","x":700,"y":450}')
    assert_success "$resp" "mouse_move" || return 1
    landed=$(echo "$resp" | python3 -c "import sys,json; d=json.load(sys.stdin)['data']['landed_at']; print(d['x'], d['y'])")
    resp=$(post '{"action":"mouse_click","x":1100,"y":600}')
    assert_success "$resp" "mouse_click" || return 1
    sleep 0.3
    desk_sh "cat $log" | python3 -c "
import json, sys
landed = [int(v) for v in sys.argv[1].split()]
clicked = json.loads(sys.argv[2])['data']['landed_at']
events = [json.loads(line) for line in sys.stdin if line.strip()]
downs = [e for e in events if e['type'] == 'down']
moves = [e for e in events if e['type'] == 'move' and e['t'] < downs[0]['t']]
first_leg = [m for m in moves if abs(m['x'] - landed[0]) <= 2 and abs(m['y'] - landed[1]) <= 2]
assert abs(landed[0] - 700) <= 10 and abs(landed[1] - 450) <= 10, landed
assert first_leg, 'pointer never reached the reported mouse_move landing'
assert len(downs) == 1 and downs[0]['button'] == 1, downs
assert [downs[0]['x'], downs[0]['y']] == [clicked['x'], clicked['y']], (downs[0], clicked)
assert abs(clicked['x'] - 1100) <= 10 and abs(clicked['y'] - 600) <= 10, clicked
" "$landed" "$resp" || return 1
    echo "  OK: pointer landed where reported"
}

# A click on a background window focuses it, so typing goes there. The front
# window is an xterm: a second tk instance gets a WM_CLASS with a space,
# which desktop_list_windows misreports.
test_system_click_focuses_window() {
    local back=/tmp/focus-back.jsonl front_id
    start_event_logger "$back" "focus back" >/dev/null || return 1
    post '{"action":"launch_app","command":["xterm","-T","focus front","-geometry","50x10+0+0"]}' >/dev/null
    for ((i = 0; i < 50; i += 1)); do
        front_id=$(post '{"action":"desktop_list_windows"}' | python3 -c "import sys,json; print(next((w['id'] for w in json.load(sys.stdin)['data']['windows'] if w['title']=='focus front'), ''))")
        [ -n "$front_id" ] && break
        sleep 0.2
    done
    [ -n "$front_id" ] || {
        echo "  FAIL: xterm window did not appear"
        return 1
    }
    post "{\"action\":\"desktop_focus_window\",\"id\":\"$front_id\"}" >/dev/null
    sleep 0.3
    assert_eq "$(window_info "$front_id" | json_get "['active']")" "True" "front window active" || return 1
    assert_success "$(post '{"action":"system_click","x":1200,"y":700}')" "click the background window" || return 1
    assert_eq "$(window_info "$front_id" | json_get "['active']")" "False" "front window lost focus" || return 1
    assert_success "$(post '{"action":"system_type","text":"sc"}')" "type" || return 1
    sleep 0.3
    desk_sh "cat $back" | grep -q '"type": "content", "text": "sc"' || {
        echo "  FAIL: typing did not reach the clicked window"
        return 1
    }
    echo "  OK: click focused the window and typing followed"
}

test_send_key_reaches_focused_window() {
    local log=/tmp/keys.jsonl id
    id=$(start_event_logger "$log" "key probe") || return 1
    post "{\"action\":\"desktop_focus_window\",\"id\":\"$id\"}" >/dev/null
    assert_success "$(post '{"action":"send_key","key":"a"}')" "send_key a" || return 1
    assert_success "$(post '{"action":"send_key","key":"pagedown"}')" "send_key pagedown" || return 1
    sleep 0.3
    assert_eq "$(desk_sh "cat $log" | python3 -c "import sys,json; print(' '.join(e['keysym'] for e in map(json.loads, filter(str.strip, sys.stdin)) if e['type'] == 'key'))")" "a Next" "keys seen by the X client"
}

test_human_pause_parks_in_region() {
    local resp
    resp=$(post '{"action":"human_pause","duration":0.1,"x":500,"y":350,"w":200,"h":120,"drift":false}')
    assert_success "$resp" "human_pause" || return 1
    echo "$resp" | python3 -c '
import json, sys
data = json.load(sys.stdin)["data"]
assert data["duration"] == 0.1 and data["elapsed"] >= 0.1, data
assert data["drifts"] == 0 and data["parked"] is True, data
assert 400 <= data["landed_at"]["x"] <= 600 and 290 <= data["landed_at"]["y"] <= 410, data
' || return 1
    echo "  OK: parked inside its region"
    assert_eq "$(post '{"action":"human_pause","duration":301}' | json_get "['error']")" "duration must be between 0.1 and 300.0" "duration limit"
}

ALL_TESTS+=(
    test_humanized_input_reaches_x_clients
    test_paste_text_replaces_the_field_with_human_keys
    test_input_validation
    test_pointer_lands_where_reported
    test_system_click_focuses_window
    test_send_key_reaches_focused_window
    test_human_pause_parks_in_region
)
