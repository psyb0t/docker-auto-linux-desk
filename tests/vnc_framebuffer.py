"""Grab a region of a VNC server's framebuffer as raw RGB.

Usage: vnc_framebuffer.py <host> <port> <x> <y> <w> <h> <out.png>

A minimal RFB 3.8 client: no authentication, raw encoding only and no cursor
pseudo-encodings, so the server must draw any cursor into the framebuffer
itself. That is what the integration tests check VNC_SHOW_CURSOR against.
"""

from __future__ import annotations

import socket
import struct
import sys

from PIL import Image

_TIMEOUT_S = 15
_VERSION = b"RFB 003.008\n"
_SECURITY_NONE = 1
_MSG_SET_ENCODINGS = 2
_MSG_UPDATE_REQUEST = 3
_SERVER_UPDATE = 0
_SERVER_COLOURMAP = 1
_SERVER_BELL = 2
_SERVER_CUT_TEXT = 3
_ENCODING_RAW = 0


def _recv(sock: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("VNC server closed the connection")
        data += chunk
    return data


def _handshake(sock: socket.socket) -> tuple[int, bool, int, int, int]:
    """Return bytes per pixel, big-endian flag and the colour shifts."""
    _recv(sock, 12)
    sock.sendall(_VERSION)
    count = _recv(sock, 1)[0]
    if _SECURITY_NONE not in _recv(sock, count):
        raise ConnectionError("VNC server requires authentication")
    sock.sendall(bytes([_SECURITY_NONE]))
    if struct.unpack(">I", _recv(sock, 4))[0] != 0:
        raise ConnectionError("VNC security handshake failed")
    sock.sendall(b"\x01")
    _recv(sock, 4)
    pixel_format = _recv(sock, 16)
    name_length = struct.unpack(">I", _recv(sock, 4))[0]
    _recv(sock, name_length)
    bpp, _, big_endian, _ = pixel_format[:4]
    red_shift, green_shift, blue_shift = pixel_format[10:13]
    return bpp // 8, bool(big_endian), red_shift, green_shift, blue_shift


def grab(host: str, port: int, x: int, y: int, w: int, h: int) -> Image.Image:
    with socket.create_connection((host, port), _TIMEOUT_S) as sock:
        sock.settimeout(_TIMEOUT_S)
        size, big_endian, rs, gs, bs = _handshake(sock)
        sock.sendall(struct.pack(">BxHi", _MSG_SET_ENCODINGS, 1, _ENCODING_RAW))
        sock.sendall(struct.pack(">BBHHHH", _MSG_UPDATE_REQUEST, 0, x, y, w, h))
        return _read_update(sock, size, big_endian, rs, gs, bs, x, y, w, h)


def _read_update(
    sock: socket.socket,
    size: int,
    big_endian: bool,
    rs: int,
    gs: int,
    bs: int,
    x: int,
    y: int,
    w: int,
    h: int,
) -> Image.Image:
    image = Image.new("RGB", (w, h))
    while True:
        kind = _recv(sock, 1)[0]
        if kind == _SERVER_BELL:
            continue
        if kind == _SERVER_CUT_TEXT:
            _recv(sock, 3)
            _recv(sock, struct.unpack(">I", _recv(sock, 4))[0])
            continue
        if kind == _SERVER_COLOURMAP:
            _recv(sock, 3)
            _recv(sock, struct.unpack(">H", _recv(sock, 2))[0] * 6)
            continue
        if kind != _SERVER_UPDATE:
            raise ConnectionError(f"unexpected VNC message {kind}")
        _recv(sock, 1)
        for _ in range(struct.unpack(">H", _recv(sock, 2))[0]):
            rx, ry, rw, rh, encoding = struct.unpack(">HHHHi", _recv(sock, 12))
            if encoding != _ENCODING_RAW:
                raise ConnectionError(f"unexpected encoding {encoding}")
            raw = _recv(sock, rw * rh * size)
            order = "big" if big_endian else "little"
            for index in range(rw * rh):
                value = int.from_bytes(raw[index * size : (index + 1) * size], order)
                pixel = ((value >> rs) & 255, (value >> gs) & 255, (value >> bs) & 255)
                px, py = rx + index % rw - x, ry + index // rw - y
                if 0 <= px < w and 0 <= py < h:
                    image.putpixel((px, py), pixel)
        return image


def main() -> None:
    host, port, x, y, w, h, out = sys.argv[1:8]
    grab(host, int(port), int(x), int(y), int(w), int(h)).save(out)


if __name__ == "__main__":
    main()
