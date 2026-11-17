"""Unit tests for run_command, launched programs, windows parsing and key bindings."""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from autolinuxdesk import keybindings, processes, windows  # noqa: E402

_STOCK_RC = "/etc/xdg/openbox/rc.xml"


def _run(cmd: dict) -> dict:
    return asyncio.run(processes.run_command(cmd))


def _refused(cmd: dict) -> str:
    try:
        _run(cmd)
    except processes.ProcessError as error:
        return str(error)
    raise AssertionError(f"accepted {cmd}")


def test_run_command_output_exit_code_and_stdin() -> None:
    result = _run({"command": "echo out; echo err >&2; exit 3"})
    assert (result["exit_code"], result["stdout"], result["stderr"]) == (3, "out\n", "err\n")
    assert result["timed_out"] is False
    assert _run({"command": ["wc", "-c"], "stdin": "hello"})["stdout"].strip() == "5"
    assert _run({"command": "echo $ALD_X", "env": {"ALD_X": "yes"}})["stdout"] == "yes\n"
    assert _run({"command": "pwd", "cwd": "/tmp"})["stdout"] == "/tmp\n"


def test_run_command_timeout_kills_the_group_and_keeps_output() -> None:
    result = _run({"command": "echo started; sleep 30", "timeout_s": 0.5})
    assert result["timed_out"] is True
    assert result["stdout"] == "started\n"
    assert result["duration"] < 5


def test_run_command_background_child_does_not_block() -> None:
    result = _run({"command": "sleep 30 & echo bg", "timeout_s": 10})
    assert result["timed_out"] is False
    assert result["stdout"] == "bg\n"
    assert result["duration"] < 5


def test_run_command_truncates_large_output() -> None:
    result = _run({"command": "head -c 1500000 /dev/zero", "timeout_s": 20})
    assert result["stdout_truncated"] is True
    assert len(result["stdout"]) == processes.OUTPUT_CAP_BYTES


def test_run_command_validation() -> None:
    assert "empty" in _refused({"command": "   "})
    assert "non-empty list" in _refused({"command": []})
    assert "non-empty list" in _refused({"command": 5})
    assert "timeout_s" in _refused({"command": "true", "timeout_s": 0})
    assert "timeout_s" in _refused({"command": "true", "timeout_s": 601})
    assert "timeout_s" in _refused({"command": "true", "timeout_s": True})
    assert "cwd does not exist" in _refused({"command": "true", "cwd": "/no/such/dir"})
    assert "env" in _refused({"command": "true", "env": {"A=B": "x"}})
    assert "env values" in _refused({"command": "true", "env": {"A": 1}})
    assert "stdin" in _refused({"command": "true", "stdin": 5})
    assert "failed to start" in _refused({"command": ["/no/such/program"]})


def test_redact_command_keeps_the_first_token() -> None:
    assert processes.redact_command("curl -H secret https://x") == "curl"
    assert processes.redact_command(["mysql", "-psecret"]) == "mysql"
    assert processes.redact_command(None) == ""


def test_launch_list_and_kill() -> None:
    manager = processes.ProcessManager()
    with tempfile.TemporaryDirectory() as log_dir:
        with patch.object(processes, "LAUNCH_LOG_DIR", log_dir):
            info = manager.launch({"command": ["sh", "-c", "echo launched; sleep 30"]})
            assert info["running"] is True and info["id"] == 1
            for _ in range(100):
                if Path(info["log_path"]).read_text() == "launched\n":
                    break
                time.sleep(0.02)
            killed = manager.kill(1)
            assert killed["running"] is False
            listed = manager.list(with_output=True)
            assert listed[0]["output_tail"] == "launched\n"
            assert manager.forget_finished() == 1
            assert manager.list() == []
    for bad in ({"id": 99}, {"id": "1"}):
        try:
            manager.kill(bad["id"])
        except processes.ProcessError:
            continue
        raise AssertionError(f"accepted {bad}")


def test_wmctrl_output_parsing() -> None:
    listing = (
        "0x01200004  0 0     102  140  400  300  host probe win\n"
        "0x01400003  0 4321  0    0    800  600  host \n"
        "0x01600005  0 0     10   20   300  200  N/A focus front\n"
    )
    # WM_CLASS may contain spaces: Tk names its second instance "tk #2".
    classes = (
        "0x01200004  0 tk.Tk  host probe win\n"
        "0x01400003  0 xterm.XTerm  host \n"
        "0x01600005  0 tk #2.Tk  N/A focus front\n"
    )

    def fake_run(argv: list[str]) -> str:
        if argv[0] == "xdotool":
            return "18874372\n"
        if "-x" in argv:
            return classes
        return listing

    with patch.object(windows, "_run", side_effect=fake_run):
        found = windows.list_windows()
        assert found[0] == {
            "id": "0x01200004",
            "desktop": 0,
            "pid": None,
            "x": 102,
            "y": 140,
            "width": 400,
            "height": 300,
            "wm_class": "tk.Tk",
            "title": "probe win",
            "active": True,
        }
        assert found[1]["pid"] == 4321 and found[1]["title"] == ""
        assert found[1]["wm_class"] == "xterm.XTerm"
        assert found[2]["wm_class"] == "tk #2.Tk" and found[2]["title"] == "focus front"
        assert windows.resolve_window({"title": "focus front"})["id"] == "0x01600005"
        assert windows.resolve_window({"title": "PROBE"})["id"] == "0x01200004"
        assert windows.resolve_window({"pid": 4321})["wm_class"] == "xterm.XTerm"
        assert windows.resolve_window({"id": "0x1400003"})["pid"] == 4321
        for bad in ({}, {"title": "a", "pid": 1}, {"id": "nope"}, {"title": "absent"}):
            try:
                windows.resolve_window(bad)
            except windows.WindowError:
                continue
            raise AssertionError(f"accepted {bad}")
        try:
            windows.move_resize(found[0], {})
        except windows.WindowError as error:
            assert "at least one" in str(error)
        try:
            windows.set_state(found[0], "spin")
        except windows.WindowError as error:
            assert "state must be one of" in str(error)


def test_send_key_names_from_openbox_notation() -> None:
    assert keybindings.to_send_key("C-A-t") == "ctrl+alt+t"
    assert keybindings.to_send_key("W-Return") == "win+enter"
    assert keybindings.to_send_key("W-S-Left") == "win+shift+left"
    assert keybindings.to_send_key("A-F4") == "alt+f4"
    assert keybindings.to_send_key("Print") == "printscreen"


def test_configured_rc_xml_has_the_desk_bindings() -> None:
    if not os.path.isfile(_STOCK_RC):
        print("skip: no stock Openbox rc.xml")
        return
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "rc.xml")
        subprocess.run(
            [sys.executable, str(ROOT / "docker" / "configure-openbox.py"), _STOCK_RC, target],
            check=True,
        )
        listing = keybindings.list_keybindings(target)
    by_key = {item["key"]: item for item in listing["keybindings"]}
    assert by_key["C-A-t"]["description"] == "run x-terminal-emulator"
    assert by_key["W-Return"]["send_key"] == ["win+enter"]
    assert by_key["W-Left"]["description"] == "tile the focused window to the left half"
    assert by_key["W-Right"]["description"] == "tile the focused window to the right half"
    assert by_key["W-Up"]["description"] == "maximize the focused window"
    assert by_key["A-F4"]["description"] == "close the focused window"
    assert by_key["W-S-Up"]["description"] == "focus the nearest window above"
    assert "C-A-Left" not in by_key, "desktop switching should be removed"
    assert "W-e" not in by_key and "Print" not in by_key
    assert all(item["description"] for item in listing["keybindings"])


def main() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
    print(json.dumps({"result": "process and keybinding tests passed", "tests": len(tests)}))


if __name__ == "__main__":
    main()
