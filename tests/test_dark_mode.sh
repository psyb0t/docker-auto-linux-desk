#!/bin/bash
# tests/test_dark_mode.sh - DESK_DARK_MODE switches xterm, Openbox, GTK and the root window.

# _server_env NAME VAR prints VAR from the server process's environment.
_server_env() {
    docker exec -u 1000 "$1" python3 -c "
import os, sys
for pid in filter(str.isdigit, os.listdir('/proc')):
    try:
        argv = open(f'/proc/{pid}/cmdline', 'rb').read().split(b'\\0')
        env = open(f'/proc/{pid}/environ', 'rb').read().split(b'\\0')
    except OSError:
        continue
    if argv[1:3] == [b'-m', b'autolinuxdesk']:
        for item in env:
            key, _, value = item.decode().partition('=')
            if key == sys.argv[1]:
                print(value)
        break
" "$2"
}

test_dark_mode_off_by_default() {
    assert_eq "$(desk_sh 'grep -c "<name>Onyx</name>" ~/.config/openbox/rc.xml')" "0" "stock Openbox theme" || return 1
    assert_eq "$(_server_env "$CONTAINER_NAME" GTK_THEME)" "" "no GTK theme override" || return 1
    assert_eq "$(desk_sh 'xrdb -query | grep -c "VT100.background"')" "0" "no dark xterm resources"
}

test_dark_mode_on() {
    local name="${CONTAINER_NAME}-dark" base
    base=$(start_extra_container "$name" -e DESK_DARK_MODE=true)
    if ! wait_for_api "$base" 60; then
        docker logs "$name" | tail -20
        stop_extra_container "$name"
        return 1
    fi
    local ok=0
    assert_eq "$(docker exec -u 1000 "$name" grep -c '<name>Onyx</name>' /home/desk/.config/openbox/rc.xml)" "1" "Onyx Openbox theme" || ok=1
    assert_eq "$(docker exec -u 1000 "$name" grep -c '<number>1</number>' /home/desk/.config/openbox/rc.xml)" "1" "key map and one desktop kept" || ok=1
    assert_eq "$(_server_env "$name" GTK_THEME)" "Adwaita:dark" "GTK dark theme passed to the server" || ok=1
    assert_eq "$(docker exec -u 1000 -e DISPLAY=:99 "$name" sh -c 'xrdb -query | grep "VT100.background"' | tr -d '[:space:]')" "*VT100.background:#121212" "dark xterm resources" || ok=1
    stop_extra_container "$name"
    return "$ok"
}

test_dark_mode_rejects_bad_values() {
    docker run --rm -i --name "${CONTAINER_NAME}-dark-values" \
        --entrypoint bash "$IMAGE_NAME:$TEST_TAG" -se <<'BASH'
set -euo pipefail
entrypoint=/usr/local/bin/auto-linux-desk-entrypoint
for value in '' TRUE maybe 'true; touch /tmp/injected'; do
    if DESK_DARK_MODE="$value" "$entrypoint" >/tmp/startup.log 2>&1; then exit 1; fi
    test "$(cat /tmp/startup.log)" = 'ERROR: DESK_DARK_MODE must be true/1/yes/on or false/0/no/off'
done
test ! -e /tmp/injected
BASH
}

ALL_TESTS+=(
    test_dark_mode_off_by_default
    test_dark_mode_on
    test_dark_mode_rejects_bad_values
)
