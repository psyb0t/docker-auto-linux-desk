#!/bin/bash

# Target user: PUID/PGID env vars, or the image user (1000).
TARGET_UID="${PUID:-1000}"
TARGET_GID="${PGID:-$TARGET_UID}"
DESK_HOME="${DESK_HOME:-/home/desk}"
DESK_WRITABLE_DIRS="${DESK_WRITABLE_DIRS:-/userdata /recordings}"
DESK_BANNER="${DESK_BANNER:-AUTO-LINUX-DESK}"
DESK_HOOK_DIR="${DESK_HOOK_DIR:-/etc/auto-linux-desk/entrypoint.d}"
export DESK_HOME TARGET_UID TARGET_GID

readonly SUDO_POLICY=/etc/sudoers.d/auto-linux-desk
readonly MAX_DESKTOP_UID=4294967294

case "${DESK_SUDO_ENABLED-false}" in
    true | 1 | yes | on) SUDO_ENABLED=true ;;
    false | 0 | no | off) SUDO_ENABLED=false ;;
    *)
        printf '%s\n' 'ERROR: DESK_SUDO_ENABLED must be true/1/yes/on or false/0/no/off' >&2
        exit 1
        ;;
esac

# DESK_DARK_MODE switches the whole desktop to dark: xterm colors, the
# Openbox theme, GTK applications (a browser's toolbar and the
# prefers-color-scheme it reports) and the root window.
case "${DESK_DARK_MODE-false}" in
    true | 1 | yes | on) DARK_MODE=true ;;
    false | 0 | no | off) DARK_MODE=false ;;
    *)
        printf '%s\n' 'ERROR: DESK_DARK_MODE must be true/1/yes/on or false/0/no/off' >&2
        exit 1
        ;;
esac
readonly DARK_OPENBOX_THEME=Onyx
readonly DARK_GTK_THEME=Adwaita:dark
readonly DARK_XRESOURCES=/etc/auto-linux-desk/dark.Xresources
readonly DARK_ROOT_COLOR='#121212'

if [ "$SUDO_ENABLED" = true ]; then
    if ! [[ "$TARGET_UID" =~ ^[1-9][0-9]{0,9}$ ]] ||
        ((TARGET_UID > MAX_DESKTOP_UID)); then
        printf '%s\n' 'ERROR: PUID must be a non-root decimal UID from 1 to 4294967294 when DESK_SUDO_ENABLED is enabled' >&2
        exit 1
    fi
fi

_configure_sudo() (
    local pending=""
    # A dot in the temporary filename keeps sudoers from loading it early.
    trap 'if [ -n "$pending" ]; then rm -f -- "$pending"; fi' EXIT
    if [ -L "$SUDO_POLICY" ] || { [ -e "$SUDO_POLICY" ] && [ ! -f "$SUDO_POLICY" ]; }; then
        printf '%s\n' 'ERROR: refusing unexpected sudo policy file type' >&2
        exit 1
    fi
    if [ "$SUDO_ENABLED" = false ]; then
        rm -f -- "$SUDO_POLICY" || exit 1
        exit 0
    fi
    if ! /usr/sbin/visudo -cqf /etc/sudoers; then
        printf '%s\n' 'ERROR: existing sudo policy is invalid' >&2
        exit 1
    fi
    pending=$(mktemp /etc/sudoers.d/.auto-linux-desk.XXXXXX) || exit 1
    if ! printf '#%s ALL=(ALL:ALL) NOPASSWD: ALL\n' "$TARGET_UID" >"$pending" ||
        ! chown 0:0 "$pending" || ! chmod 0440 "$pending" ||
        ! /usr/sbin/visudo -cqf "$pending"; then
        printf '%s\n' 'ERROR: could not prepare sudo policy' >&2
        exit 1
    fi
    if ! mv -fT -- "$pending" "$SUDO_POLICY"; then
        printf '%s\n' 'ERROR: could not install sudo policy' >&2
        exit 1
    fi
)

# Fix ownership of writable dirs (runs as root).
_fix_perms() {
    local dir
    read -ra dirs <<<"$DESK_WRITABLE_DIRS"
    for dir in "${dirs[@]}"; do
        [ -d "$dir" ] || continue

        # Skip only when nothing inside belongs to someone else. Checking the
        # directory alone missed files copied in by another user, such as a
        # saved profile, which the app then could not rewrite.
        if [ -z "$(find "$dir" \( ! -user "$TARGET_UID" -o ! -group "$TARGET_GID" \) -print -quit)" ]; then
            continue
        fi

        chown -R "$TARGET_UID:$TARGET_GID" "$dir"
    done

    # The home directory holds caches and window manager config, whichever
    # UID runs the app.
    if [ -d "$DESK_HOME" ] &&
        [ "$(stat -c '%u:%g' "$DESK_HOME")" != "$TARGET_UID:$TARGET_GID" ]; then
        chown -R "$TARGET_UID:$TARGET_GID" "$DESK_HOME"
    fi
}

# Root hooks from images built on this one, in filename order. They are
# sourced, so they see TARGET_UID, TARGET_GID and DESK_HOME.
_run_hooks() {
    local hook
    [ -d "$DESK_HOOK_DIR" ] || return 0
    for hook in "$DESK_HOOK_DIR"/*.sh; do
        [ -f "$hook" ] || continue
        # shellcheck disable=SC1090
        . "$hook"
    done
}

if [ "$(id -u)" = "0" ]; then
    # D-Bus requires a passwd entry for its UID, including a custom PUID.
    if ! getent passwd "$TARGET_UID" >/dev/null; then
        if ! getent group "$TARGET_GID" >/dev/null; then
            groupadd --gid "$TARGET_GID" "desk-$TARGET_GID" || exit 1
        fi
        useradd --uid "$TARGET_UID" --gid "$TARGET_GID" --no-create-home \
            --home-dir "$DESK_HOME" "desk-$TARGET_UID" || exit 1
    fi
    _fix_perms
    _run_hooks
    _configure_sudo || exit 1
    # Drop privileges and re-exec this script as the target user.
    exec gosu "$TARGET_UID:$TARGET_GID" env HOME="$DESK_HOME" "$0" "$@"
fi

# Already non-root (docker --user): ownership fixes and hooks were skipped.
export HOME="${HOME:-$DESK_HOME}"

if [ "$SUDO_ENABLED" = true ]; then
    if [ "$(id -u)" != "$TARGET_UID" ] || ! /usr/bin/sudo -n -- /usr/bin/true; then
        printf '%s\n' 'ERROR: DESK_SUDO_ENABLED requires a matching passwordless sudo grant and Docker permissions that allow sudo; start the entrypoint as root to configure the grant' >&2
        exit 1
    fi
    printf '%s\n' 'WARNING: DESK_SUDO_ENABLED grants the desktop user passwordless root access inside this container' >&2
fi

case "${VNC_SHOW_CURSOR:-true}" in
    true)
        VNC_CURSOR_ARGS=(-nocursorshape)
        ;;
    false)
        VNC_CURSOR_ARGS=(-nocursor)
        ;;
    *)
        echo "VNC_SHOW_CURSOR must be true or false" >&2
        exit 1
        ;;
esac

PIDS=()

cleanup() {
    local status=$?
    echo "" >&2
    echo "[*] Shutting down..." >&2
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null
    done
    wait
    echo "[*] Done." >&2
    exit "${EXIT_CODE:-$status}"
}

trap cleanup SIGINT SIGTERM SIGHUP EXIT

# Detect script mode before anything prints to stdout.
SCRIPT_MODE=false
for arg in "$@"; do
    if [ "$arg" = "--script" ]; then
        SCRIPT_MODE=true
        break
    fi
done

# --script reads YAML from stdin. Save it before background processes can
# consume stdin.
if [ "$SCRIPT_MODE" = "true" ]; then
    _STDIN_FILE=$(mktemp /tmp/script-stdin-XXXXXX.yaml)
    cat >"$_STDIN_FILE"
    set -- --script "$_STDIN_FILE"
    # Keep real stdout for the server's JSON; send shell noise to stderr.
    exec 3>&1 1>&2
fi

# Share one session bus with apps, the API and the activated AT-SPI2 bus,
# including when the display is supplied by the caller.
if [ -z "${DBUS_SESSION_BUS_ADDRESS:-}" ]; then
    DBUS_ENV=$(dbus-launch --sh-syntax) || {
        echo "ERROR: could not start the D-Bus session bus" >&2
        exit 1
    }
    eval "$DBUS_ENV"
    export DBUS_SESSION_BUS_ADDRESS
    PIDS+=("$DBUS_SESSION_BUS_PID")
fi
export NO_AT_BRIDGE=0 GNOME_ACCESSIBILITY=1 ACCESSIBILITY_ENABLED=1 \
    QT_ACCESSIBILITY=1 QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1

# KEYBINDINGS_FILE replaces the whole key map (docs/keyboard.md), and
# DESK_DARK_MODE picks the dark Openbox theme. rc.xml is written again when
# either asks for it, and when a dark rc.xml from an earlier start of this
# container has to go back to the stock theme.
OPENBOX_RC="$HOME/.config/openbox/rc.xml"
OPENBOX_ARGS=()
if [ "$DARK_MODE" = true ]; then
    OPENBOX_ARGS=(--theme "$DARK_OPENBOX_THEME")
fi
if [ -n "${KEYBINDINGS_FILE:-}" ] || [ "$DARK_MODE" = true ] ||
    grep -q "<name>$DARK_OPENBOX_THEME</name>" "$OPENBOX_RC" 2>/dev/null; then
    python3 /usr/local/lib/auto-linux-desk/configure-openbox.py "${OPENBOX_ARGS[@]}" \
        /etc/xdg/openbox/rc.xml "${KEYBINDINGS_FILE:-/etc/auto-linux-desk/keymap.json}" "$OPENBOX_RC" || {
        if [ -n "${KEYBINDINGS_FILE:-}" ]; then
            echo "ERROR: KEYBINDINGS_FILE=$KEYBINDINGS_FILE is not a valid key map" >&2
        else
            echo "ERROR: could not write $OPENBOX_RC" >&2
        fi
        exit 1
    }
fi

# GTK applications read the theme from the environment, which the server
# passes on to everything it launches.
if [ "$DARK_MODE" = true ]; then
    export GTK_THEME="$DARK_GTK_THEME"
fi

# The framebuffer MUST be allocated at XVFB_RESOLUTION up front. Xvfb's root
# framebuffer is fixed at the size given to `-screen 0 WxHxD`, and xrandr can
# only switch to modes that fit inside it. Recording and screenshots beyond
# that size would fail with "Capture area ... outside the screen size".
if [ -z "$DISPLAY" ] || [ "$DISPLAY" = ":99" ]; then
    DEPTH="${XVFB_DEPTH:-24}"
    RES="${XVFB_RESOLUTION:-1920x1080}"
    Xvfb :99 -screen 0 "${RES}x${DEPTH}" -ac +extension GLX +render -noreset &
    PIDS+=($!)
    export DISPLAY=:99
    sleep 0.5

    openbox &
    PIDS+=($!)
    sleep 0.3
fi

if [ "$DARK_MODE" = true ]; then
    xrdb -merge "$DARK_XRESOURCES" || {
        echo "ERROR: could not load $DARK_XRESOURCES" >&2
        exit 1
    }
    xsetroot -solid "$DARK_ROOT_COLOR" || echo "WARNING: could not set the root window color" >&2
fi

VNC_LISTEN_HOST="${VNC_LISTEN_HOST:-0.0.0.0}"
VNC_LISTEN_PORT="${VNC_LISTEN_PORT:-5900}"
HTTP_LISTEN_HOST="${HTTP_LISTEN_HOST:-0.0.0.0}"
HTTP_LISTEN_PORT="${HTTP_LISTEN_PORT:-8080}"

# -nonap: by default x11vnc "naps" when viewers send no input for a while and
# then stops redrawing the cursor, so someone watching automation over noVNC
# sees it frozen in the wrong place.
x11vnc -display :99 -rfbport 5901 -nopw -forever -shared -nonap \
    -listen "$VNC_LISTEN_HOST" "${VNC_CURSOR_ARGS[@]}" &
PIDS+=($!)
sleep 0.3

websockify --web /usr/share/novnc "$VNC_LISTEN_HOST:$VNC_LISTEN_PORT" localhost:5901 &
PIDS+=($!)
sleep 0.3

if [ "$SCRIPT_MODE" = "true" ]; then
    python -m autolinuxdesk "$@" 1>&3 &
else
    python -m autolinuxdesk "$@" &
fi
SESSION_PID=$!
PIDS+=("$SESSION_PID")

if [ "$SCRIPT_MODE" = "false" ]; then
    for ((attempt = 0; attempt < 30; attempt += 1)); do
        if curl -s "http://localhost:${HTTP_LISTEN_PORT}/health" >/dev/null 2>&1; then
            break
        fi
        sleep 0.2
    done

    echo ""
    echo "=============================================="
    echo "  ${DESK_BANNER}"
    echo "=============================================="
    echo ""
    echo "  VNC:  http://${VNC_LISTEN_HOST}:${VNC_LISTEN_PORT}/"
    echo "  API:  http://${HTTP_LISTEN_HOST}:${HTTP_LISTEN_PORT}"
    echo ""
    case "${DESK_EXEC_ENABLED:-true}" in
        1 | true | yes | on)
            if [ -z "${AUTH_TOKEN// /}" ]; then
                echo "  WARNING: run_command and launch_app are enabled"
                echo "  and AUTH_TOKEN is unset. Do not expose the API port."
                echo ""
            fi
            ;;
    esac
    echo "  Ctrl+C to exit"
    echo "=============================================="
    echo ""
fi

# Wait for the server to exit and keep its exit code.
wait $SESSION_PID
EXIT_CODE=$?
