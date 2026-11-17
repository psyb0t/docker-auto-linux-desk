#!/bin/bash
# tests/test_humanized_input.sh - what an X client sees from the humanized
# input actions, judged against human motor data by tests/input_checks.py.
#
# The tk event logger records X events with server timestamps. A robotic
# control session (raw pyautogui: straight constant-speed moves, zero-hold
# clicks and keys, burst wheel, periodic jiggle) goes through the same checks
# and must be caught, which proves the checks can tell the difference.

HI_RESULTS_DIR="$RESULTS_DIR/humanized-input"
HI_CLICK_COUNT=30
HI_CLICK_ORDER_SEED=7
HI_SCROLL_NOTCHES=8
HI_PAUSE_SECONDS=14
HI_PAUSE_DRIFT_INTERVAL=2.5
HI_PAUSE_DRIFT_DISTANCE=30
HI_ROBOT_JIGGLE_INTERVAL=0.5
HI_HEALTH_MAX_SECONDS=1.0
HI_HEALTH_POLLS=5
# Eight 120x70 targets inside the logger window (480..1440 x 270..810).
HI_TARGETS=(
    "620 420 120 70" "830 420 120 70" "1040 420 120 70" "1250 420 120 70"
    "620 640 120 70" "830 640 120 70" "1040 640 120 70" "1250 640 120 70"
)
HI_TYPED_TEXT=$'Hello World, THIS is a test: 42% done (ok?)\nCafé ñandú costs €5 & more!'
# Three sentences: at the 2% typo rate the chance of no typo at all is ~1e-4.
HI_TYPO_SENTENCE="the quick brown fox jumps over the lazy dog while the busy farmer counts sheep near the old stone bridge and hums a quiet song about rivers mountains forests and distant summer evenings"
HI_TYPO_TEXT="$HI_TYPO_SENTENCE $HI_TYPO_SENTENCE $HI_TYPO_SENTENCE"
HI_TYPO_INTERVAL=0.06
HI_LONG_TEXT="steady typing keeps the request lock busy while health checks still answer quickly because input runs in a worker thread and never blocks the event loop of the server at all"

# _hi_post <json>: POST through python so text needs no shell escaping.
_hi_post() {
    python3 -c '
import sys, urllib.request
req = urllib.request.Request(sys.argv[2], data=sys.argv[1].encode(), headers={"Content-Type": "application/json"})
print(urllib.request.urlopen(req, timeout=300).read().decode())
' "$1" "$BASE"
}

# _hi_type <text> [extra params json]: system_type into the focused window.
_hi_type() {
    _hi_post "$(python3 -c 'import json, sys; d = {"action": "system_type", "text": sys.argv[1]}; d.update(json.loads(sys.argv[2] or "{}")); print(json.dumps(d))' "$1" "${2:-}")"
}

# _hi_logger <log> <title>: start a focused event logger.
_hi_logger() {
    local id
    mkdir -p "$HI_RESULTS_DIR"
    id=$(start_event_logger "$1" "$2") || {
        echo "  FAIL: event logger window did not appear"
        return 1
    }
    post "{\"action\":\"desktop_focus_window\",\"id\":\"$id\"}" >/dev/null
}

# _hi_fetch <log> <file>: copy the logger's log out of the container.
_hi_fetch() {
    docker exec "$CONTAINER_NAME" cat "$1" >"$2"
}

# _hi_reset <log>: forget what the logger recorded so far.
_hi_reset() {
    desk_sh ": > $1" >/dev/null
}

# _hi_clear_field: empty the logger's text field.
_hi_clear_field() {
    post '{"action":"send_key","key":"ctrl+a"}' >/dev/null
    post '{"action":"send_key","key":"backspace"}' >/dev/null
}

# _hi_content <file>: the logger's text after the last key, as JSON.
_hi_content() {
    python3 -c '
import json, sys
contents = [json.loads(l)["text"] for l in open(sys.argv[1]) if l.strip() and json.loads(l)["type"] == "content"]
print(json.dumps(contents[-1] if contents else None, ensure_ascii=False))
' "$1"
}

# _hi_judge <mode> <events> <expect> [extra args...]
_hi_judge() {
    local mode="$1" events="$2" expect="$3"
    shift 3
    if ! python3 "$WORKDIR/tests/input_checks.py" "$mode" "$events" --expect "$expect" "$@"; then
        echo "  FAIL: $mode session judged wrong (expected $expect)"
        return 1
    fi
    echo "  OK: $mode session judged $expect"
}

# _hi_robot <python>: run raw pyautogui on the desktop.
_hi_robot() {
    local resp
    resp=$(_hi_post "$(python3 -c 'import json, sys; print(json.dumps({"action": "run_command", "command": ["python3", "-c", "import pyautogui; pyautogui.FAILSAFE = False; " + sys.argv[1]], "timeout_s": 120}))' "$1")")
    if [ "$(echo "$resp" | json_get "['data']['exit_code']")" != "0" ]; then
        echo "  FAIL: robotic control session could not run: $resp"
        return 1
    fi
}

# _hi_click_sequence: target indexes in a shuffled order without immediate
# repeats, so the session is not a repeating pattern.
_hi_click_sequence() {
    python3 -c '
import random, sys
count, seed, size = map(int, sys.argv[1:4])
rng, out = random.Random(seed), []
while len(out) < count:
    pick = rng.randrange(size)
    if not out or out[-1] != pick:
        out.append(pick)
print(" ".join(map(str, out)))
' "$HI_CLICK_COUNT" "$HI_CLICK_ORDER_SEED" "${#HI_TARGETS[@]}"
}

# _hi_median <events> <python expression over events e>: median of values.
_hi_median() {
    python3 -c '
import json, statistics, sys
events = [json.loads(l) for l in open(sys.argv[1]) if l.strip()]
values = eval(sys.argv[2], {"events": events})
print(round(statistics.median(values), 3))
' "$1" "$2"
}

# _hi_in_range <value> <lo> <hi> <name>
_hi_in_range() {
    if python3 -c 'import sys; v, lo, hi = map(float, sys.argv[1:4]); sys.exit(0 if lo <= v <= hi else 1)' "$1" "$2" "$3"; then
        echo "  OK: $4 = $1 (expected $2-$3)"
        return 0
    fi
    echo "  FAIL: $4 = $1 (expected $2-$3)"
    return 1
}

test_humanized_mouse() {
    local log=/tmp/hi-mouse.jsonl index cx cy w h robot="" sequence targets
    _hi_logger "$log" "hi mouse" || return 1
    read -r -a sequence <<<"$(_hi_click_sequence)"
    targets="$HI_RESULTS_DIR/mouse-targets.json"
    for index in "${sequence[@]}"; do
        echo "${HI_TARGETS[$index]}"
    done | python3 -c 'import json, sys; print(json.dumps([list(map(int, l.split())) for l in sys.stdin]))' >"$targets"

    _hi_reset "$log"
    for index in "${sequence[@]}"; do
        read -r cx cy w h <<<"${HI_TARGETS[$index]}"
        assert_success "$(post "{\"action\":\"system_click\",\"x\":$cx,\"y\":$cy,\"w\":$w,\"h\":$h}")" "system_click target $index" >/dev/null || return 1
    done
    sleep 0.3
    _hi_fetch "$log" "$HI_RESULTS_DIR/mouse-human.jsonl"
    _hi_judge mouse "$HI_RESULTS_DIR/mouse-human.jsonl" human --targets "$targets" || return 1

    # Robotic control: straight constant-speed moves, zero-hold clicks at dead centre.
    for index in "${sequence[@]}"; do
        read -r cx cy _ _ <<<"${HI_TARGETS[$index]}"
        robot+="pyautogui.moveTo($cx, $cy, duration=0.3); pyautogui.click(); "
    done
    _hi_reset "$log"
    _hi_robot "$robot" || return 1
    sleep 0.3
    _hi_fetch "$log" "$HI_RESULTS_DIR/mouse-robot.jsonl"
    _hi_judge mouse "$HI_RESULTS_DIR/mouse-robot.jsonl" robot --targets "$targets"
}

test_humanized_typing() {
    local log=/tmp/hi-typing.jsonl resp backspaces
    _hi_logger "$log" "hi typing" || return 1

    # Capitals, symbols, a newline and non-ASCII characters, exactly as asked.
    resp=$(_hi_type "$HI_TYPED_TEXT")
    assert_success "$resp" "system_type mixed text" || return 1
    sleep 0.3
    _hi_fetch "$log" "$HI_RESULTS_DIR/typing-human.jsonl"
    assert_eq "$(_hi_content "$HI_RESULTS_DIR/typing-human.jsonl")" "$(python3 -c 'import json, sys; print(json.dumps(sys.argv[1], ensure_ascii=False))' "$HI_TYPED_TEXT")" "exact text incl. unicode" || return 1
    _hi_judge typing "$HI_RESULTS_DIR/typing-human.jsonl" human || return 1

    # Typos: corrected with BackSpace, final text exact.
    _hi_clear_field
    _hi_reset "$log"
    resp=$(_hi_type "$HI_TYPO_TEXT" "{\"typos\": true, \"interval\": $HI_TYPO_INTERVAL}")
    assert_success "$resp" "system_type typos" || return 1
    assert_eq "$(echo "$resp" | json_get "['data']['typos']")" "True" "typos applied on the screen surface" || return 1
    sleep 0.3
    _hi_fetch "$log" "$HI_RESULTS_DIR/typing-typos.jsonl"
    assert_eq "$(_hi_content "$HI_RESULTS_DIR/typing-typos.jsonl")" "\"$HI_TYPO_TEXT\"" "typos: final text exact" || return 1
    backspaces=$(grep -c '"type": "key", "keysym": "BackSpace"' "$HI_RESULTS_DIR/typing-typos.jsonl" || true)
    if [ "$backspaces" -lt 1 ]; then
        echo "  FAIL: typos: no BackSpace corrections in ${#HI_TYPO_TEXT} characters"
        return 1
    fi
    echo "  OK: typos corrected with $backspaces BackSpace presses"

    # Robotic control: pyautogui.write, fixed interval and zero-hold keys.
    _hi_clear_field
    _hi_reset "$log"
    _hi_robot "pyautogui.write('Hello World, THIS is a robotic TEST of typing.', interval=0.05)" || return 1
    sleep 0.3
    _hi_fetch "$log" "$HI_RESULTS_DIR/typing-robot.jsonl"
    _hi_judge typing "$HI_RESULTS_DIR/typing-robot.jsonl" robot
}

test_humanized_input_off_event_loop() {
    local log=/tmp/hi-loop.jsonl typing_pid i elapsed slow=0
    _hi_logger "$log" "hi loop" || return 1
    _hi_type "$HI_LONG_TEXT" >/dev/null &
    typing_pid=$!
    sleep 1
    for ((i = 0; i < HI_HEALTH_POLLS; i += 1)); do
        if ! kill -0 "$typing_pid" 2>/dev/null; then
            echo "  FAIL: typing finished before health polling ended; text too short to prove anything"
            return 1
        fi
        elapsed=$(curl -sf -o /dev/null -w '%{time_total}' "$BASE/health")
        echo "  /health answered in ${elapsed}s while typing"
        if ! python3 -c 'import sys; sys.exit(0 if float(sys.argv[1]) <= float(sys.argv[2]) else 1)' "$elapsed" "$HI_HEALTH_MAX_SECONDS"; then
            slow=$((slow + 1))
        fi
        sleep 0.5
    done
    wait "$typing_pid"
    assert_eq "$slow" "0" "health stays responsive during system_type" || return 1
    sleep 0.3
    _hi_fetch "$log" "$HI_RESULTS_DIR/loop.jsonl"
    assert_eq "$(_hi_content "$HI_RESULTS_DIR/loop.jsonl")" "\"$HI_LONG_TEXT\"" "long text typed exactly"
}

test_humanized_scroll() {
    local log=/tmp/hi-scroll.jsonl
    _hi_logger "$log" "hi scroll" || return 1
    assert_success "$(post '{"action":"mouse_move","x":960,"y":540,"w":400,"h":200}')" "pointer over the window" >/dev/null || return 1
    _hi_reset "$log"
    assert_success "$(post "{\"action\":\"scroll\",\"amount\":-$HI_SCROLL_NOTCHES}")" "scroll" >/dev/null || return 1
    sleep 0.5
    _hi_fetch "$log" "$HI_RESULTS_DIR/scroll-human.jsonl"
    _hi_judge scroll "$HI_RESULTS_DIR/scroll-human.jsonl" human --notches "$HI_SCROLL_NOTCHES" || return 1

    # Robotic control: every notch in one burst.
    _hi_reset "$log"
    _hi_robot "pyautogui.moveTo(960, 540); pyautogui.scroll(-$HI_SCROLL_NOTCHES)" || return 1
    sleep 0.5
    _hi_fetch "$log" "$HI_RESULTS_DIR/scroll-robot.jsonl"
    _hi_judge scroll "$HI_RESULTS_DIR/scroll-robot.jsonl" robot --notches "$HI_SCROLL_NOTCHES"
}

test_humanized_overrides() {
    local log=/tmp/hi-overrides.jsonl index cx cy w h median
    _hi_logger "$log" "hi overrides" || return 1

    # click_hold: the X client sees the requested hold. Bounds are ~3
    # standard deviations of the sample median.
    _hi_reset "$log"
    for index in 0 4 2 6 5 1 7 3 0 5 2 6; do
        read -r cx cy w h <<<"${HI_TARGETS[$index]}"
        assert_success "$(post "{\"action\":\"system_click\",\"x\":$cx,\"y\":$cy,\"w\":$w,\"h\":$h,\"click_hold\":0.5,\"speed\":1.5}")" "system_click with overrides" >/dev/null || return 1
    done
    sleep 0.3
    _hi_fetch "$log" "$HI_RESULTS_DIR/overrides-click.jsonl"
    median=$(_hi_median "$HI_RESULTS_DIR/overrides-click.jsonl" "[u['xt'] - d['xt'] for d, u in zip([e for e in events if e['type'] in ('down', 'double') and e.get('button') == 1], [e for e in events if e['type'] == 'up' and e.get('button') == 1])]")
    _hi_in_range "$median" 330 760 "median click hold ms with click_hold=0.5" || return 1

    # key_hold: every key is held around the requested time. A wide interval
    # keeps 0.25 s holds from colliding with the next key.
    _hi_clear_field
    _hi_reset "$log"
    assert_success "$(_hi_type "override check text" '{"key_hold": 0.25, "interval": 0.6}')" "system_type with overrides" >/dev/null || return 1
    sleep 0.3
    _hi_fetch "$log" "$HI_RESULTS_DIR/overrides-typing.jsonl"
    assert_eq "$(_hi_content "$HI_RESULTS_DIR/overrides-typing.jsonl")" '"override check text"' "typed exactly with overrides" || return 1
    median=$(python3 -c '
import json, statistics, sys
sys.path.insert(0, sys.argv[2])
from input_checks import key_holds, load_events
holds = key_holds(load_events(__import__("pathlib").Path(sys.argv[1])))[0]
print(round(statistics.median(holds), 1))
' "$HI_RESULTS_DIR/overrides-typing.jsonl" "$WORKDIR/tests")
    _hi_in_range "$median" 180 340 "median key hold ms with key_hold=0.25" || return 1

    # instant: send_key falls back to a raw press with no hold.
    _hi_reset "$log"
    assert_success "$(post '{"action":"send_key","key":"x","instant":true}')" "send_key instant" >/dev/null || return 1
    sleep 0.3
    _hi_fetch "$log" "$HI_RESULTS_DIR/overrides-instant.jsonl"
    median=$(_hi_median "$HI_RESULTS_DIR/overrides-instant.jsonl" "(lambda d, u: [b['xt'] - a['xt'] for a, b in zip(d, u)])([e for e in events if e['type'] == 'key'], [e for e in events if e['type'] == 'keyup'])")
    _hi_in_range "$median" 0 15 "key hold ms with instant=true" || return 1

    # notch_gap: wheel notches arrive around the requested spacing.
    post '{"action":"mouse_move","x":960,"y":540,"w":400,"h":200}' >/dev/null
    _hi_reset "$log"
    for _ in 1 2 3; do
        assert_success "$(post '{"action":"scroll","amount":-4,"notch_gap":0.3}')" "scroll with notch_gap" >/dev/null || return 1
        sleep 1.2
    done
    _hi_fetch "$log" "$HI_RESULTS_DIR/overrides-scroll.jsonl"
    # Gaps over 1 s are the breaks between the three requests.
    median=$(_hi_median "$HI_RESULTS_DIR/overrides-scroll.jsonl" "(lambda w: [b - a for a, b in zip(w, w[1:]) if b - a < 1000])([e['xt'] for e in events if e['type'] == 'down' and e.get('button') == 5])")
    _hi_in_range "$median" 190 480 "median notch gap ms with notch_gap=0.3" || return 1

    # Out-of-range overrides are rejected before any input happens.
    assert_eq "$(post '{"action":"system_click","x":10,"y":10,"speed":50}' | json_get "['error']")" "speed must be between 0.1 and 10.0" "speed out of range rejected"
}

test_human_pause_motion() {
    local log=/tmp/hi-pause.jsonl resp
    _hi_logger "$log" "hi pause" || return 1
    _hi_reset "$log"
    resp=$(post "{\"action\":\"human_pause\",\"duration\":$HI_PAUSE_SECONDS,\"x\":960,\"y\":540,\"w\":700,\"h\":400,\"drift_interval\":$HI_PAUSE_DRIFT_INTERVAL,\"drift_distance\":$HI_PAUSE_DRIFT_DISTANCE}")
    assert_success "$resp" "human_pause session" >/dev/null || return 1
    _hi_fetch "$log" "$HI_RESULTS_DIR/pause-human.jsonl"
    _hi_judge pause "$HI_RESULTS_DIR/pause-human.jsonl" human --duration "$HI_PAUSE_SECONDS" || return 1

    # Robotic control: a periodic jiggle.
    _hi_reset "$log"
    _hi_robot "import time; x, y = 960, 540; pyautogui.moveTo(x, y); [(time.sleep($HI_ROBOT_JIGGLE_INTERVAL), pyautogui.moveTo(x + (4 if i % 2 else -4), y)) for i in range(int($HI_PAUSE_SECONDS / $HI_ROBOT_JIGGLE_INTERVAL))]" || return 1
    _hi_fetch "$log" "$HI_RESULTS_DIR/pause-robot.jsonl"
    _hi_judge pause "$HI_RESULTS_DIR/pause-robot.jsonl" robot --duration "$HI_PAUSE_SECONDS"
}

ALL_TESTS+=(
    test_humanized_mouse
    test_humanized_typing
    test_humanized_input_off_event_loop
    test_humanized_scroll
    test_humanized_overrides
    test_human_pause_motion
)
