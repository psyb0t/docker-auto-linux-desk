#!/bin/bash
# Sourced by test.sh, which owns strict mode and container cleanup.

test_sudo_policy() {
    docker run --rm -i --name "${CONTAINER_NAME}-sudo-policy" \
        --entrypoint bash "$IMAGE_NAME:$TEST_TAG" -se <<'BASH'
set -euo pipefail
trap 'echo "sudo regression failed at line $LINENO" >&2' ERR
policy=/etc/sudoers.d/auto-linux-desk
entrypoint=/usr/local/bin/auto-linux-desk-entrypoint

# Stop after privilege setup, before desktop services start.
startup() {
    local status=0
    VNC_SHOW_CURSOR=invalid "$entrypoint" >/tmp/startup.log 2>&1 || status=$?
    test "$status" -ne 0
    grep -q 'VNC_SHOW_CURSOR must be true or false' /tmp/startup.log
}
denied() {
    if gosu "$1" sudo -n id -u; then
        echo "unexpected sudo access for $1" >&2
        exit 1
    fi
}
export DESK_SUDO_ENABLED=true
startup
test "$(gosu 1000 sudo -n id -u)" = 0
test "$(gosu 1000 sudo -n -u nobody id -u)" = 65534
test "$(stat -c '%u:%g:%a' "$policy")" = 0:0:440
visudo -cf /etc/sudoers
if gosu 1000 test -w "$policy"; then exit 1; fi
useradd --uid 1501 --no-create-home other-desktop
denied 1501
printf '# unrelated policy\n' >/etc/sudoers.d/unrelated
chmod 440 /etc/sudoers.d/unrelated
for value in true 1 yes on; do
    export DESK_SUDO_ENABLED="$value"
    startup
    test "$(gosu 1000 sudo -n id -u)" = 0
done
for value in false 0 no off; do
    export DESK_SUDO_ENABLED="$value"
    startup
    test ! -e "$policy"
    denied 1000
    test -f /etc/sudoers.d/unrelated
done
unset DESK_SUDO_ENABLED
startup
denied 1000
for value in '' ' ' TRUE maybe 'true; touch /tmp/injected' 'trüe' "$(printf '%04096d' 0)"; do
    if DESK_SUDO_ENABLED="$value" "$entrypoint" >/tmp/startup.log 2>&1; then exit 1; fi
    test "$(cat /tmp/startup.log)" = 'ERROR: DESK_SUDO_ENABLED must be true/1/yes/on or false/0/no/off'
    test ! -e "$policy"
done
test ! -e /tmp/injected
export DESK_SUDO_ENABLED=true
for uid in 0 -1 nobody '1000 ALL=ALL' 4294967295 999999999999999999999 01000; do
    if PUID="$uid" "$entrypoint" >/tmp/startup.log 2>&1; then exit 1; fi
    grep -q 'PUID must be' /tmp/startup.log
    test ! -e "$policy"
done
export PUID=1500 PGID=1600
startup
test "$(gosu 1500:1600 sudo -n id -u)" = 0
denied 1000
unset PGID
export PUID=1501
startup
test "$(gosu 1501 sudo -n id -u)" = 0
denied 1500
export PUID=2000
startup
test "$(gosu 2000:2000 sudo -n id -u)" = 0
test "$(getent group 2000 | cut -d: -f3)" = 2000
for uid in 1 4294967294; do
    export PUID="$uid" PGID=1600
    startup
    test "$(gosu "$uid:1600" sudo -n id -u)" = 0
done
export PUID=1501 PGID=1501
startup

# Direct --user needs an existing grant matching PUID.
startup_log=$(gosu 1501 env VNC_SHOW_CURSOR=invalid "$entrypoint" 2>&1) || :
grep -q 'VNC_SHOW_CURSOR must be true or false' <<<"$startup_log"
rm "$policy"
if gosu 1501 "$entrypoint" >/tmp/startup.log 2>&1; then exit 1; fi
grep -q 'DESK_SUDO_ENABLED requires' /tmp/startup.log

printf 'preserve me\n' >/tmp/policy-target
ln -s /tmp/policy-target "$policy"
for value in true false; do
    if DESK_SUDO_ENABLED="$value" "$entrypoint" >/tmp/startup.log 2>&1; then exit 1; fi
    test "$(cat /tmp/policy-target)" = 'preserve me'
    test -L "$policy"
done
rm "$policy"
mkdir "$policy"
if "$entrypoint" >/tmp/startup.log 2>&1; then exit 1; fi
test -d "$policy"
rmdir "$policy"

# Broken global policy must prevent installation, not just fail at sudo time.
printf 'not a valid sudoers directive\n' >/etc/sudoers.d/unrelated
if "$entrypoint" >/tmp/startup.log 2>&1; then exit 1; fi
test ! -e "$policy"
printf '# unrelated policy\n' >/etc/sudoers.d/unrelated

# Force a write failure without touching the host's policy.
mv /etc/sudoers.d /etc/sudoers.saved
ln -s /proc /etc/sudoers.d
if "$entrypoint" >/tmp/startup.log 2>&1; then exit 1; fi
test ! -e /proc/auto-linux-desk
rm /etc/sudoers.d
mv /etc/sudoers.saved /etc/sudoers.d
echo 'sudo policy matrix passed'
BASH
}

test_sudo_api() {
    local name="${CONTAINER_NAME}-sudo-api" base response status=0
    response=$(post '{"action":"run_command","command":"sudo -n true"}')
    echo "$response" | python3 -c '
import json, sys
r = json.load(sys.stdin)
assert r["success"], r
assert r["data"]["exit_code"] != 0, r
' || return 1
    docker run -d --name "$name" -e DESK_SUDO_ENABLED=true \
        -e PUID=1500 -e PGID=1600 "$IMAGE_NAME:$TEST_TAG" >/dev/null
    base="http://$(container_ip "$name"):8080"
    if wait_for_api "$base" 60; then
        response=$(post_to "$base" '{"action":"run_command","command":"id -u; id -g; sudo -n id -u; sudo -n touch /root/sudo-proof; sudo -n test -f /root/sudo-proof"}')
        echo "$response" | python3 -c '
import json, sys
r = json.load(sys.stdin)
assert r["success"], r
assert r["data"]["exit_code"] == 0, r
assert r["data"]["stdout"] == "1500\n1600\n0\n", r
' || status=1
    else
        docker logs "$name"
        status=1
    fi
    docker rm -f "$name" >/dev/null
    return "$status"
}

test_sudo_docker_boundaries() {
    local output option
    for option in '--security-opt=no-new-privileges' '--cap-drop=SETUID'; do
        if output=$(docker run --rm --name "${CONTAINER_NAME}-sudo-boundary" \
            "$option" -e DESK_SUDO_ENABLED=true -e VNC_SHOW_CURSOR=invalid \
            "$IMAGE_NAME:$TEST_TAG" 2>&1); then
            echo 'sudo unexpectedly bypassed Docker restrictions'
            return 1
        fi
        if grep -q 'VNC_SHOW_CURSOR must be true or false' <<<"$output"; then
            echo "sudo check incorrectly succeeded: $output"
            return 1
        fi
    done
    if output=$(docker run --rm --name "${CONTAINER_NAME}-sudo-direct" \
        --user 1000:1000 -e DESK_SUDO_ENABLED=true \
        "$IMAGE_NAME:$TEST_TAG" 2>&1); then
        echo 'non-root startup unexpectedly created a sudo grant'
        return 1
    fi
    grep -q 'DESK_SUDO_ENABLED requires' <<<"$output"
}

ALL_TESTS+=(test_sudo_policy test_sudo_api test_sudo_docker_boundaries)
