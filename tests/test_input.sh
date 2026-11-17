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

test_input_validation() {
    assert_failure "$(post '{"action":"system_click","x":1}')" "missing y" || return 1
    assert_failure "$(post '{"action":"scroll","amount":0}')" "zero scroll" || return 1
    assert_failure "$(post '{"action":"system_type","text":""}')" "empty text" || return 1
    assert_failure "$(post '{"action":"scroll_to_bottom_humanized"}')" "browser-only action absent"
}

ALL_TESTS+=(
    test_humanized_input_reaches_x_clients
    test_input_validation
)
