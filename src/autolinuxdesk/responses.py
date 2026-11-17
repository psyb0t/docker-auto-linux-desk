"""Response envelopes and PNG resizing shared by actions and routes."""

from __future__ import annotations

import io
import time
from collections.abc import Mapping
from typing import Any

from PIL import Image

CONTENT_TYPE_IMAGE_PNG = "image/png"
BINARY_KEY = "_binary"


class ActionError(Exception):
    """An action was rejected or failed. The message is returned to the caller."""

    def __init__(self, message: str, data: dict | None = None) -> None:
        super().__init__(message)
        self.data = data


def make_response(success: bool, data: dict | None = None, error: str | None = None) -> dict:
    """Build the {success, timestamp, data?, error?} envelope every action returns."""
    resp: dict = {"success": success, "timestamp": time.time()}
    if data:
        resp["data"] = data
    if error:
        resp["error"] = error
    return resp


def ok(data: dict | None = None) -> dict:
    return make_response(True, data)


def fail(error: str, data: dict | None = None) -> dict:
    return make_response(False, data, error)


def _int_param(value: Any, name: str) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError) as error:
        raise ActionError(f"{name} must be an integer") from error
    if number < 1 or number > 20_000:
        raise ActionError(f"{name} must be between 1 and 20000")
    return number


def resize_png(data: bytes, params: Mapping[str, Any]) -> bytes:
    """Resize PNG bytes by width, height or whLargest. Returns data unchanged without them."""
    w_raw = params.get("width")
    h_raw = params.get("height")
    largest_raw = params.get("whLargest")
    if not w_raw and not h_raw and not largest_raw:
        return data

    img = Image.open(io.BytesIO(data))
    orig_w, orig_h = img.size
    if largest_raw:
        largest = _int_param(largest_raw, "whLargest")
        if orig_w >= orig_h:
            new_w, new_h = largest, int(orig_h * largest / orig_w)
        else:
            new_w, new_h = int(orig_w * largest / orig_h), largest
    elif w_raw and h_raw:
        new_w, new_h = _int_param(w_raw, "width"), _int_param(h_raw, "height")
    elif w_raw:
        new_w = _int_param(w_raw, "width")
        new_h = int(orig_h * new_w / orig_w)
    else:
        new_h = _int_param(h_raw, "height")
        new_w = int(orig_w * new_h / orig_h)

    img = img.resize((max(new_w, 1), max(new_h, 1)), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
