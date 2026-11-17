#!/bin/bash
# tests/test_container.sh - entrypoint, users, display, VNC, recording, script mode.

# The image ships no procps, so scan /proc for the server's command line.
_server_pid() {
    docker exec "$1" python3 -c "
import os
for pid in filter(str.isdigit, os.listdir('/proc')):
    try:
        argv = open(f'/proc/{pid}/cmdline', 'rb').read().split(b'\\0')
    except OSError:
        continue
    if argv[1:3] == [b'-m', b'autolinuxdesk']:
        print(pid)
        break
"
}

test_default_user_and_banner() {
    assert_eq "$(docker exec "$CONTAINER_NAME" stat -c '%u' "/proc/$(_server_pid "$CONTAINER_NAME")")" "1000" "server runs as uid 1000" || return 1
    # The banner prints after the entrypoint sees /health answer, so it can
    # trail the first API response.
    for ((i = 0; i < 50; i += 1)); do
        grep -q "Ctrl+C to exit" <<<"$(docker logs "$CONTAINER_NAME" 2>&1)" && break
        sleep 0.2
    done
    grep -q "AUTO-LINUX-DESK" <<<"$(docker logs "$CONTAINER_NAME" 2>&1)" || {
        echo "  FAIL: banner missing"
        return 1
    }
    grep -q "WARNING: run_command and launch_app are enabled" <<<"$(docker logs "$CONTAINER_NAME" 2>&1)" || {
        echo "  FAIL: exec warning missing"
        return 1
    }
    # shellcheck disable=SC2016 # Expanded inside the container.
    assert_eq "$(desk_sh 'echo $HOME')" "/home/desk" "home directory" || return 1
    assert_eq "$(desk_sh 'grep -c "<number>1</number>" ~/.config/openbox/rc.xml')" "1" "one desktop"
}

test_puid_pgid_and_hooks() {
    local name="${CONTAINER_NAME}-puid" base hook_dir
    hook_dir="$RESULTS_DIR/hooks"
    mkdir -p "$hook_dir"
    # shellcheck disable=SC2016 # Expanded when the hook runs.
    printf '%s\n' 'echo "hook uid=$TARGET_UID home=$DESK_HOME" > /tmp/hook-ran' 'chmod 644 /tmp/hook-ran' >"$hook_dir/10-test.sh"
    base=$(start_extra_container "$name" -e PUID=1500 -e PGID=1600 \
        -e DESK_BANNER="CUSTOM BANNER" \
        -v "$hook_dir:/etc/auto-linux-desk/entrypoint.d:ro")
    if ! wait_for_api "$base" 60; then
        docker logs "$name" | tail -20
        stop_extra_container "$name"
        return 1
    fi
    local pid
    pid=$(_server_pid "$name")
    assert_eq "$(docker exec "$name" stat -c '%u' "/proc/$pid")" "1500" "PUID applied" || {
        stop_extra_container "$name"
        return 1
    }
    assert_eq "$(docker exec "$name" stat -c '%g' "/proc/$pid")" "1600" "PGID applied" || {
        stop_extra_container "$name"
        return 1
    }
    assert_eq "$(docker exec "$name" stat -c '%u:%g' /userdata /recordings /home/desk | sort -u)" "1500:1600" "writable directories chowned" || {
        stop_extra_container "$name"
        return 1
    }
    assert_eq "$(docker exec "$name" cat /tmp/hook-ran)" "hook uid=1500 home=/home/desk" "entrypoint.d hook ran as root before the drop" || {
        stop_extra_container "$name"
        return 1
    }
    grep -q "CUSTOM BANNER" <<<"$(docker logs "$name" 2>&1)" || {
        echo "  FAIL: DESK_BANNER ignored"
        stop_extra_container "$name"
        return 1
    }
    assert_success "$(post_to "$base" '{"action":"system_click","x":10,"y":10}')" "input works under PUID"
    stop_extra_container "$name"
}

# PGID defaults to PUID when only PUID is set.
test_puid_only() {
    local name="${CONTAINER_NAME}-puid-only" base pid
    base=$(start_extra_container "$name" -e PUID=2000)
    if ! wait_for_api "$base" 60; then
        docker logs "$name" | tail -20
        stop_extra_container "$name"
        return 1
    fi
    pid=$(_server_pid "$name")
    assert_eq "$(docker exec "$name" stat -c '%u:%g' "/proc/$pid")" "2000:2000" "server runs as 2000:2000" || {
        stop_extra_container "$name"
        return 1
    }
    assert_eq "$(docker exec "$name" stat -c '%u:%g' /userdata)" "2000:2000" "userdata owned by 2000:2000" || {
        stop_extra_container "$name"
        return 1
    }
    assert_success "$(post_to "$base" '{"action":"ping"}')" "API responds"
    stop_extra_container "$name"
}

# Each case: "label|WxH|whLargest=256 size". 1281x721 checks the even
# rounding libx264 needs for recordings.
RESOLUTION_CASES=(
    "1280x720|1280x720|256x144"
    "800x600|800x600|256x192"
    "375x812-phone|375x812|118x256"
    "800x800-square|800x800|256x256"
    "1280x2000-tall|1280x2000|163x256"
    "1281x721-odd|1281x721|256x144"
)

_resolution_case() {
    local label="$1" resolution="$2" small="$3"
    local name="${CONTAINER_NAME}-res-${label}" base out="$RESULTS_DIR/res-${label}.png"
    local w="${resolution%%x*}" h="${resolution##*x}" resp
    base=$(start_extra_container "$name" -e "XVFB_RESOLUTION=$resolution")
    if ! wait_for_api "$base" 60; then
        docker logs "$name" | tail -20
        stop_extra_container "$name"
        return 1
    fi
    curl -sf -o "$out" "$base/screenshot/desktop"
    assert_eq "$(png_dimensions "$out")" "$resolution" "[$label] screen allocated at XVFB_RESOLUTION" || {
        stop_extra_container "$name"
        return 1
    }
    curl -sf -o "$out" "$base/screenshot/desktop?whLargest=256"
    assert_eq "$(png_dimensions "$out")" "$small" "[$label] whLargest follows the longer side" || {
        stop_extra_container "$name"
        return 1
    }
    resp=$(post_to "$base" '{"action":"get_resolution"}')
    assert_eq "$(echo "$resp" | json_get "['data']['width']")x$(echo "$resp" | json_get "['data']['height']")" "$resolution" "[$label] get_resolution" || {
        stop_extra_container "$name"
        return 1
    }
    assert_eq "$(curl -sf "$base/state" | json_get "['resolution']['width']")" "$w" "[$label] state width" || {
        stop_extra_container "$name"
        return 1
    }
    resp=$(post_to "$base" '{"action":"start_recording","mode":"desktop","fps":5}')
    post_to "$base" '{"action":"stop_recording","slug":"res"}' >/dev/null
    assert_eq "$(echo "$resp" | json_get "['data']['capture_size']['width']")x$(echo "$resp" | json_get "['data']['capture_size']['height']")" "$((w - w % 2))x$((h - h % 2))" "[$label] recording size rounded down to even" || {
        stop_extra_container "$name"
        return 1
    }
    stop_extra_container "$name"
}

test_resolution() {
    local entry label resolution small
    for entry in "${RESOLUTION_CASES[@]}"; do
        IFS='|' read -r label resolution small <<<"$entry"
        _resolution_case "$label" "$resolution" "$small" || return 1
    done
}

# A /userdata volume reused at another resolution: the new size wins and the
# data survives.
test_userdata_survives_resolution_change() {
    local name1="${CONTAINER_NAME}-persist-1" name2="${CONTAINER_NAME}-persist-2"
    local dir="$RESULTS_DIR/persist-userdata" out="$RESULTS_DIR/persist.png" base
    rm -rf "$dir"
    mkdir -p "$dir"
    base=$(start_extra_container "$name1" -e XVFB_RESOLUTION=800x800 -v "$dir:/userdata")
    if ! wait_for_api "$base" 60; then
        stop_extra_container "$name1"
        return 1
    fi
    post_to "$base" '{"action":"run_command","command":"echo kept > /userdata/marker"}' >/dev/null
    curl -sf -o "$out" "$base/screenshot/desktop"
    assert_eq "$(png_dimensions "$out")" "800x800" "first run at 800x800" || {
        stop_extra_container "$name1"
        return 1
    }
    stop_extra_container "$name1"

    base=$(start_extra_container "$name2" -v "$dir:/userdata")
    if ! wait_for_api "$base" 60; then
        stop_extra_container "$name2"
        return 1
    fi
    curl -sf -o "$out" "$base/screenshot/desktop"
    assert_eq "$(png_dimensions "$out")" "1920x1080" "second run at the default resolution" || {
        stop_extra_container "$name2"
        return 1
    }
    assert_eq "$(post_to "$base" '{"action":"get_resolution"}' | json_get "['data']['width']")" "1920" "get_resolution after the change" || {
        stop_extra_container "$name2"
        return 1
    }
    assert_eq "$(post_to "$base" '{"action":"run_command","command":"cat /userdata/marker"}' | json_get "['data']['stdout']")" "kept" "userdata kept" || {
        stop_extra_container "$name2"
        return 1
    }
    stop_extra_container "$name2"
    rm -rf "$dir" 2>/dev/null || true
}

test_vnc_web() {
    local host
    host=$(container_ip "$CONTAINER_NAME")
    curl -sf "http://$host:5900/" | grep -q "autoconnect=true" || {
        echo "  FAIL: noVNC redirect page missing"
        return 1
    }
    curl -sf -o /dev/null "http://$host:5900/vnc.html" || {
        echo "  FAIL: noVNC client missing"
        return 1
    }
    echo "  OK: noVNC served"
}

VNC_CURSOR_SETTLE_SECONDS=2
VNC_NAP_IDLE_SECONDS=35
VNC_NAP_MIN_UPTIME_SECONDS=95
VNC_CURSOR_MIN_CHANGED_PIXELS=20
VNC_CURSOR_MAX_HIDDEN_CHANGED_PIXELS=4

# _vnc_grab <host> <out.png>: the framebuffer around (200, 200) as a VNC
# client without cursor-shape support sees it.
_vnc_grab() {
    python3 "$WORKDIR/tests/vnc_framebuffer.py" "$1" 5901 150 150 100 100 "$2"
}

_vnc_changed_pixels() {
    python3 - "$1" "$2" <<'PY'
import sys

from PIL import Image, ImageChops

before = Image.open(sys.argv[1]).convert("RGB")
after = Image.open(sys.argv[2]).convert("RGB")
print(sum(1 for pixel in ImageChops.difference(before, after).get_flattened_data() if max(pixel) > 8))
PY
}

# _vnc_cursor_case <label> <api base> <host> <expect visible>
_vnc_cursor_case() {
    local label="$1" base="$2" host="$3" visible="$4" changed
    local before="$RESULTS_DIR/vnc-$label-before.png" after="$RESULTS_DIR/vnc-$label-after.png"
    assert_success "$(post_to "$base" '{"action":"mouse_move","x":200,"y":200,"speed":2}')" "[$label] pointer at 200,200" || return 1
    sleep "$VNC_CURSOR_SETTLE_SECONDS"
    _vnc_grab "$host" "$before" || return 1
    assert_success "$(post_to "$base" '{"action":"mouse_move","x":1400,"y":700,"speed":2}')" "[$label] pointer away" || return 1
    sleep "$VNC_CURSOR_SETTLE_SECONDS"
    _vnc_grab "$host" "$after" || return 1
    changed=$(_vnc_changed_pixels "$before" "$after")
    if [ "$visible" = "true" ] && [ "$changed" -lt "$VNC_CURSOR_MIN_CHANGED_PIXELS" ]; then
        echo "  FAIL: [$label] pointer not in the VNC framebuffer ($changed changed pixels)"
        return 1
    fi
    if [ "$visible" = "false" ] && [ "$changed" -gt "$VNC_CURSOR_MAX_HIDDEN_CHANGED_PIXELS" ]; then
        echo "  FAIL: [$label] hidden pointer changed $changed framebuffer pixels"
        return 1
    fi
    echo "  OK: [$label] $changed changed framebuffer pixels"
}

# Each case gets a fresh container, as a viewer of a new desktop would.
test_vnc_remote_cursor() {
    local entry label setting visible name base args
    # Viewers that send no input for a while used to make x11vnc nap and stop
    # redrawing the cursor; a watcher saw it frozen. Idle past that point on
    # the long-running shared container, then check the cursor still moves.
    local started uptime wait_s
    started=$(date -d "$(docker inspect -f '{{.State.StartedAt}}' "$CONTAINER_NAME")" +%s)
    uptime=$(($(date +%s) - started))
    # x11vnc only starts napping a while after start, so idle until the
    # container is old enough and has been quiet long enough.
    wait_s=$((VNC_NAP_MIN_UPTIME_SECONDS - uptime))
    [ "$wait_s" -lt "$VNC_NAP_IDLE_SECONDS" ] && wait_s=$VNC_NAP_IDLE_SECONDS
    echo "  idle ${wait_s}s (container up ${uptime}s)"
    sleep "$wait_s"
    # shellcheck disable=SC2153 # BASE is the shared container's URL from tests/common.sh.
    _vnc_cursor_case "after-idle" "$BASE" "$(container_ip "$CONTAINER_NAME")" true || return 1
    for entry in "default||true" "true|true|true" "false|false|false"; do
        IFS='|' read -r label setting visible <<<"$entry"
        name="${CONTAINER_NAME}-vnc-$label"
        args=()
        [ -n "$setting" ] && args=(-e "VNC_SHOW_CURSOR=$setting")
        base=$(start_extra_container "$name" "${args[@]}")
        if ! wait_for_api "$base" 60; then
            stop_extra_container "$name"
            return 1
        fi
        _vnc_cursor_case "$label" "$base" "$(container_ip "$name")" "$visible" || {
            stop_extra_container "$name"
            return 1
        }
        stop_extra_container "$name"
    done
}

test_vnc_cursor_invalid_setting() {
    local name="${CONTAINER_NAME}-vnc-invalid"
    docker rm -f "$name" >/dev/null 2>&1 || true
    docker run -d --name "$name" -e VNC_SHOW_CURSOR=yes "$IMAGE_NAME:$TEST_TAG" >/dev/null
    EXTRA_CONTAINERS+=("$name")
    for ((i = 0; i < 40; i += 1)); do
        [ "$(docker inspect -f '{{.State.Running}}' "$name")" = "false" ] && break
        sleep 0.25
    done
    assert_eq "$(docker inspect -f '{{.State.ExitCode}}' "$name")" "1" "exit code" || {
        stop_extra_container "$name"
        return 1
    }
    assert_eq "$(docker logs "$name" 2>&1)" "VNC_SHOW_CURSOR must be true or false" "error message" || {
        stop_extra_container "$name"
        return 1
    }
    stop_extra_container "$name"
}

# _is_mp4 <slug>: the file starts with an MP4 ftyp box.
_is_mp4() {
    [ "$(desk_sh "dd if=/recordings/$1.mp4 bs=1 count=4 skip=4 2>/dev/null")" = "ftyp" ]
}

test_recording() {
    local resp slug size
    resp=$(post '{"action":"start_recording","mode":"desktop","fps":10}')
    assert_success "$resp" "start recording" || return 1
    assert_eq "$(post '{"action":"recording_status"}' | json_get "['data']['active']")" "True" "recording active" || return 1
    assert_eq "$(post '{"action":"recording_status"}' | json_get "['data']['mode']")" "desktop" "recording mode" || return 1
    post '{"action":"mouse_move","x":300,"y":300}' >/dev/null
    sleep 2
    slug="itest-$$"
    resp=$(post "{\"action\":\"stop_recording\",\"slug\":\"$slug\"}")
    assert_success "$resp" "stop recording" || return 1
    assert_eq "$(echo "$resp" | json_get "['data']['path']")" "/recordings/$slug.mp4" "recording path" || return 1
    assert_eq "$(post '{"action":"recording_status"}' | json_get "['data']['active']")" "False" "recording inactive after stop" || return 1
    size=$(desk_sh "stat -c %s /recordings/$slug.mp4 2>/dev/null || echo 0")
    if [ "$size" -lt 1024 ]; then
        echo "  FAIL: recording too small: $size bytes"
        return 1
    fi
    echo "  OK: recording written ($size bytes)"
    _is_mp4 "$slug" || {
        echo "  FAIL: recording is not an MP4 (no ftyp box)"
        return 1
    }
    echo "  OK: valid MP4 container"
}

test_recording_errors() {
    local resp
    resp=$(post '{"action":"stop_recording","slug":"noop"}')
    assert_failure "$resp" "stop without an active recording" || return 1
    assert_success "$(post '{"action":"start_recording","mode":"window","fps":5}')" "start" || return 1
    resp=$(post '{"action":"start_recording","mode":"window","fps":5}')
    assert_failure "$resp" "second concurrent start refused" || {
        post '{"action":"stop_recording","slug":"cleanup"}' >/dev/null
        return 1
    }
    resp=$(post '{"action":"stop_recording","slug":"../../etc/passwd"}')
    assert_failure "$resp" "path traversal slug refused" || {
        post '{"action":"stop_recording","slug":"cleanup"}' >/dev/null
        return 1
    }
    assert_eq "$(post '{"action":"recording_status"}' | json_get "['data']['active']")" "True" "recording survives a refused stop" || {
        post '{"action":"stop_recording","slug":"cleanup"}' >/dev/null
        return 1
    }
    assert_success "$(post '{"action":"stop_recording","slug":"cleanup"}')" "stop with a valid slug" || return 1
    assert_failure "$(post '{"action":"start_recording","mode":"bogus"}')" "unknown mode refused" || return 1
    assert_failure "$(post '{"action":"start_recording","fps":0}')" "fps out of range refused"
}

test_recording_viewport_and_cursor() {
    local resp slug="cursor-$$"
    # On the screen surface the viewport is the whole screen.
    resp=$(post '{"action":"start_recording","mode":"viewport","fps":5}')
    post '{"action":"stop_recording","slug":"viewport"}' >/dev/null
    assert_eq "$(echo "$resp" | json_get "['data']['capture_size']['width']")x$(echo "$resp" | json_get "['data']['capture_size']['height']")" "1920x1080" "viewport recording covers the screen" || return 1

    resp=$(post '{"action":"start_recording","mode":"window","fps":5,"show_cursor":false}')
    assert_eq "$(echo "$resp" | json_get "['data']['show_cursor']")" "False" "show_cursor=false echoed" || {
        post '{"action":"stop_recording","slug":"cleanup"}' >/dev/null
        return 1
    }
    sleep 0.8
    post "{\"action\":\"stop_recording\",\"slug\":\"$slug\"}" >/dev/null
    _is_mp4 "$slug" || {
        echo "  FAIL: show_cursor=false recording is not an MP4"
        return 1
    }
    echo "  OK: ffmpeg accepted show_cursor=false"
    resp=$(post '{"action":"start_recording","mode":"window","fps":5}')
    post '{"action":"stop_recording","slug":"with-cursor"}' >/dev/null
    assert_eq "$(echo "$resp" | json_get "['data']['show_cursor']")" "True" "show_cursor defaults to true"
}

test_recording_slug_collision() {
    local slug="coll-$$" path
    post '{"action":"start_recording","mode":"window","fps":5}' >/dev/null
    sleep 0.8
    path=$(post "{\"action\":\"stop_recording\",\"slug\":\"$slug\"}" | json_get "['data']['path']")
    assert_eq "$path" "/recordings/$slug.mp4" "first recording path" || return 1
    post '{"action":"start_recording","mode":"window","fps":5}' >/dev/null
    sleep 0.8
    path=$(post "{\"action\":\"stop_recording\",\"slug\":\"$slug\"}" | json_get "['data']['path']")
    assert_eq "$path" "/recordings/$slug-2.mp4" "second recording gets a suffix"
}

test_script_mode() {
    local out status
    set +e
    out=$(printf '%s\n' 'name: itest' 'steps:' '  - action: run_command' '    command: echo from-script' '    output_id: cmd' '  - action: get_resolution' '    output_id: res' |
        docker run --rm -i "$IMAGE_NAME:$TEST_TAG" --script 2>/dev/null)
    status=$?
    set -e
    assert_eq "$status" "0" "script exit code" || return 1
    echo "$out" | python3 -c "
import json, sys
result = json.load(sys.stdin)
assert result['success'], result
assert result['outputs']['cmd']['stdout'] == 'from-script\n', result['outputs']
assert result['outputs']['res']['width'] == 1920
" || {
        echo "  FAIL: script stdout is not one JSON document: $out"
        return 1
    }
    echo "  OK: script stdout"
    set +e
    printf '%s\n' 'steps:' '  - action: run_command' '    command: exit 1' '  - action: no_such_action' |
        docker run --rm -i "$IMAGE_NAME:$TEST_TAG" --script >/dev/null 2>&1
    status=$?
    set -e
    assert_eq "$status" "1" "failed script exits 1"
}

ALL_TESTS+=(
    test_default_user_and_banner
    test_puid_pgid_and_hooks
    test_puid_only
    test_resolution
    test_userdata_survives_resolution_change
    test_vnc_web
    test_vnc_remote_cursor
    test_vnc_cursor_invalid_setting
    test_recording
    test_recording_errors
    test_recording_viewport_and_cursor
    test_recording_slug_collision
    test_script_mode
)
