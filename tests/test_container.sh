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

test_resolution() {
    local name="${CONTAINER_NAME}-res" base out="$RESULTS_DIR/res.png"
    base=$(start_extra_container "$name" -e XVFB_RESOLUTION=1280x2000)
    if ! wait_for_api "$base" 60; then
        stop_extra_container "$name"
        return 1
    fi
    curl -sf -o "$out" "$base/screenshot/desktop"
    assert_eq "$(png_dimensions "$out")" "1280x2000" "screen allocated at XVFB_RESOLUTION" || {
        stop_extra_container "$name"
        return 1
    }
    assert_eq "$(post_to "$base" '{"action":"get_resolution"}' | json_get "['data']['height']")" "2000" "get_resolution" || {
        stop_extra_container "$name"
        return 1
    }
    stop_extra_container "$name"
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

test_recording() {
    local resp slug
    resp=$(post '{"action":"start_recording","mode":"desktop","fps":10}')
    assert_success "$resp" "start recording" || return 1
    assert_eq "$(post '{"action":"recording_status"}' | json_get "['data']['active']")" "True" "recording active" || return 1
    post '{"action":"mouse_move","x":300,"y":300}' >/dev/null
    sleep 2
    slug="itest-$$"
    resp=$(post "{\"action\":\"stop_recording\",\"slug\":\"$slug\"}")
    assert_success "$resp" "stop recording" || return 1
    desk_sh "test -s /recordings/$slug.mp4 && echo present" | grep -q present || {
        echo "  FAIL: recording file missing: $resp"
        return 1
    }
    echo "  OK: recording written"
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
    test_resolution
    test_vnc_web
    test_recording
    test_script_mode
)
