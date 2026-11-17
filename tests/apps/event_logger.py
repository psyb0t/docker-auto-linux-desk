"""Full-screen tk window that logs X input events as JSON lines.

Usage: python3 event_logger.py <log path> [title]

The integration tests launch it with launch_app, drive it with the
humanized input actions and read the log back with run_command. Input
events carry "xt", the X server timestamp in milliseconds, which is the
clock to measure holds and gaps with: "t" is when tk got round to the event.
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

    # Tk binds ctrl+a to "line start"; give it select-all like GTK, Qt and
    # browser fields, which is what paste_text expects of a text field.
    def select_all(event: tk.Event) -> str:
        # The more specific binding replaces the <KeyPress> logger, so log here.
        write("key", keysym=event.keysym, char=event.char, keycode=event.keycode, xt=event.time)
        text.tag_add("sel", "1.0", "end-1c")
        text.mark_set("insert", "end-1c")
        return "break"

    text.bind("<Control-a>", select_all)

    def on_button(event: tk.Event, kind: str) -> None:
        write(kind, button=event.num, x=event.x_root, y=event.y_root, xt=event.time)

    text.bind("<ButtonPress>", lambda e: on_button(e, "down"), add="+")
    text.bind("<ButtonRelease>", lambda e: on_button(e, "up"), add="+")
    text.bind("<Double-Button-1>", lambda e: on_button(e, "double"), add="+")
    text.bind(
        "<Motion>",
        lambda e: write("move", x=e.x_root, y=e.y_root, xt=e.time),
        add="+",
    )

    def on_key(event: tk.Event, kind: str) -> None:
        write(kind, keysym=event.keysym, char=event.char, keycode=event.keycode, xt=event.time)

    def on_key_release(event: tk.Event) -> None:
        on_key(event, "keyup")
        # The widget's content after each key, so tests can see what a paste did.
        write("content", text=text.get("1.0", "end-1c"))

    text.bind("<KeyPress>", lambda e: on_key(e, "key"), add="+")
    text.bind("<KeyRelease>", on_key_release, add="+")
    root.bind("<Map>", lambda e: write("mapped"), add="+")
    root.mainloop()


if __name__ == "__main__":
    main()
