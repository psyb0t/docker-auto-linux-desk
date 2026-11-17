"""Full-screen tk window that logs X input events as JSON lines.

Usage: python3 event_logger.py <log path> [title]

The integration tests launch it with launch_app, drive it with the
humanized input actions and read the log back with run_command.
"""

from __future__ import annotations

import json
import sys
import time
import tkinter as tk


def main() -> None:
    log_path = sys.argv[1]
    title = sys.argv[2] if len(sys.argv) > 2 else "event logger"
    log = open(log_path, "a", buffering=1, encoding="utf-8")  # noqa: SIM115

    def write(kind: str, **fields: object) -> None:
        log.write(json.dumps({"t": time.monotonic(), "type": kind, **fields}) + "\n")

    root = tk.Tk()
    root.title(title)
    width, height = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"{width // 2}x{height // 2}+{width // 4}+{height // 4}")
    text = tk.Text(root)
    text.pack(fill="both", expand=True)
    text.focus_set()

    def on_button(event: tk.Event, kind: str) -> None:
        write(kind, button=event.num, x=event.x_root, y=event.y_root)

    text.bind("<ButtonPress>", lambda e: on_button(e, "down"), add="+")
    text.bind("<ButtonRelease>", lambda e: on_button(e, "up"), add="+")
    text.bind("<Double-Button-1>", lambda e: on_button(e, "double"), add="+")
    text.bind("<Motion>", lambda e: write("move", x=e.x_root, y=e.y_root), add="+")
    text.bind("<KeyPress>", lambda e: write("key", keysym=e.keysym, char=e.char), add="+")
    root.bind("<Map>", lambda e: write("mapped"), add="+")
    root.mainloop()


if __name__ == "__main__":
    main()
