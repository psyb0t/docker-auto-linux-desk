# Base image pinned by digest. Tags are mutable, digests are not. Re-resolve
# with: docker buildx imagetools inspect python:3.12-slim-bookworm --format '{{.Manifest.Digest}}'
# Images built FROM this one (stealthy-auto-browse) assume Python 3.12 paths.
FROM python:3.12-slim-bookworm@sha256:d50fb7611f86d04a3b0471b46d7557818d88983fc3136726336b2a4c657aa30b

# MCP Registry ownership label. Images built on this one override it.
LABEL io.modelcontextprotocol.server.name="io.github.psyb0t/auto-linux-desk"

ENV DEBIAN_FRONTEND=noninteractive

# Timezone - override with -e TZ=Your/Timezone
ENV TZ=UTC

RUN apt-get update && apt-get install -y --no-install-recommends \
        tzdata \
        wget curl gnupg ca-certificates \
        gosu sudo \
    && rm -rf /var/lib/apt/lists/*

# X11 display, VNC, the window manager (title bars and resize handles) and the
# AT-SPI2 accessibility bus that desktop_accessibility_* reads.
RUN apt-get update && apt-get install -y --no-install-recommends \
        xvfb xauth dbus dbus-x11 x11-xserver-utils xcvt \
        x11vnc novnc websockify \
        openbox \
        at-spi2-core libatk-adaptor \
    && rm -rf /var/lib/apt/lists/*

# noVNC auto-connect redirect
RUN echo '<!DOCTYPE html><html><head><meta http-equiv="refresh" content="0;url=vnc.html?autoconnect=true&resize=scale"></head></html>' > /usr/share/novnc/index.html

# Fonts, UI automation tools, window control and screen recording.
RUN apt-get update && apt-get install -y --no-install-recommends \
        fonts-dejavu-core fonts-liberation fonts-urw-base35 \
        xdotool wmctrl xclip scrot python3-tk python3-dev \
        xterm \
        ffmpeg \
    && rm -rf /var/lib/apt/lists/*

# Python packages install system-wide as root, so the desktop user can read
# site-packages but not change it.
COPY pyproject.toml README.md /opt/auto-linux-desk/
COPY src/ /opt/auto-linux-desk/src/
RUN pip install --no-cache-dir /opt/auto-linux-desk \
    && rm -rf /opt/auto-linux-desk/build

# Non-root user and writable directories. Images built on this one may
# rename the user; keep UID/GID 1000.
RUN groupadd -g 1000 desk && useradd -u 1000 -g 1000 -m desk \
    && mkdir -p /userdata /recordings \
    && chown desk:desk /userdata /recordings

# Openbox config: one desktop and the key map in docker/keymap.json as the
# whole keyboard section. The generator stays in the image so the entrypoint
# can apply KEYBINDINGS_FILE at start. See docs/keyboard.md.
COPY docker/configure-openbox.py /usr/local/lib/auto-linux-desk/configure-openbox.py
COPY docker/keymap.json /etc/auto-linux-desk/keymap.json
COPY --chmod=755 docker/desk-focus /usr/local/bin/desk-focus
COPY docker/dark.Xresources /etc/auto-linux-desk/dark.Xresources
RUN install -d -o desk -g desk /home/desk/.config/openbox \
    && python3 /usr/local/lib/auto-linux-desk/configure-openbox.py \
        /etc/xdg/openbox/rc.xml /etc/auto-linux-desk/keymap.json /home/desk/.config/openbox/rc.xml \
    && chown desk:desk /home/desk/.config/openbox/rc.xml /home/desk/.config/openbox/keymap.json

# Root hooks run by the entrypoint before it drops privileges.
RUN install -d /etc/auto-linux-desk/entrypoint.d

COPY --chmod=755 entrypoint.sh /usr/local/bin/auto-linux-desk-entrypoint

ENV XVFB_RESOLUTION=1920x1080 \
    XVFB_DEPTH=24 \
    DESK_HOME=/home/desk \
    DESK_WRITABLE_DIRS="/userdata /recordings" \
    DESK_BANNER="AUTO-LINUX-DESK" \
    DESK_EXEC_ENABLED=true

WORKDIR /home/desk

# VNC (noVNC over websockify) and the HTTP/MCP API
EXPOSE 5900 8080

ENTRYPOINT ["/usr/local/bin/auto-linux-desk-entrypoint"]
