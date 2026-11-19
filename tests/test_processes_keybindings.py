"""Unit tests for run_command, launched programs, windows parsing and key bindings."""

from __future__ import annotations

import asyncio
import importlib.machinery
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
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


def _configure(target: str, keymap: str | None = None) -> None:
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "docker" / "configure-openbox.py"),
            _STOCK_RC,
            keymap or str(ROOT / "docker" / "keymap.json"),
            target,
        ],
        check=True,
    )


def test_openbox_notation_round_trips_to_send_key() -> None:
    spec = importlib.util.spec_from_file_location(
        "configure_openbox", ROOT / "docker" / "configure-openbox.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for send_key in (
        "ctrl+alt+shift+left",
        "alt+f4",
        "ctrl+alt+1",
        "ctrl+alt+esc",
        "alt+shift+tab",
        "ctrl+alt+space",
    ):
        assert keybindings.to_send_key(module.openbox_key(send_key)) == send_key, send_key
    assert module.openbox_key("shift+alt+ctrl+t") == "C-A-S-t"


def test_custom_key_map_validation_and_metadata() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "stock.xml"
        source.write_text(
            '<openbox_config xmlns="http://openbox.org/3.4/rc">'
            "<desktops><number>4</number></desktops><keyboard>"
            "<chainQuitKey>C-g</chainQuitKey>"
            '<keybind key="W-x"><action name="Close"/></keybind>'
            "</keyboard></openbox_config>",
            encoding="utf-8",
        )
        keymap = Path(tmp) / "custom.json"
        target = Path(tmp) / "rc.xml"

        def configure(data: object) -> subprocess.CompletedProcess:
            keymap.write_text(json.dumps(data), encoding="utf-8")
            return subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "docker" / "configure-openbox.py"),
                    str(source),
                    str(keymap),
                    str(target),
                ],
                capture_output=True,
                text=True,
            )

        binding = {
            "key": "alt+ctrl+escape",
            "description": "custom description",
            "group": "Custom",
            "actions": [{"name": "Close"}],
        }
        result = configure({"bindings": [binding]})
        assert result.returncode == 0, result.stderr
        listing = keybindings.list_keybindings(str(target))
        assert listing["count"] == 1
        assert listing["keybindings"][0]["description"] == "custom description"
        assert listing["keybindings"][0]["group"] == "Custom"
        keyboard = ET.parse(target).getroot().find("o:keyboard", keybindings.NS)
        assert [child.tag.split("}")[-1] for child in keyboard] == ["keybind"]
        valid_xml = target.read_bytes()
        for data in (
            [],
            None,
            {},
            {"bindings": {}},
            {"bindings": None},
            {"bindings": [None]},
            {"bindings": [{**binding, "key": "ctrl+ctrl+x"}]},
            {"bindings": [{**binding, "description": "   "}]},
            {"bindings": [{**binding, "group": 1}]},
            {"bindings": [{**binding, "actions": [None]}]},
            {"bindings": [{**binding, "actions": [{"name": ""}]}]},
            {"bindings": [{**binding, "actions": [{"name": "Close", "options": []}]}]},
            {"bindings": [{**binding, "actions": [{"name": "Close", "options": {"a<b": "x"}}]}]},
            {"bindings": [{**binding, "actions": [{"name": "Close", "options": {"x": 1}}]}]},
        ):
            result = configure(data)
            assert result.returncode != 0, data
            assert "Traceback" not in result.stderr, result.stderr
            assert target.read_bytes() == valid_xml
        assert configure({"bindings": []}).returncode == 0
        assert keybindings.list_keybindings(str(target))["count"] == 0


def test_desk_focus_handles_classes_slots_and_absent_matches() -> None:
    loader = importlib.machinery.SourceFileLoader("desk_focus", str(ROOT / "docker" / "desk-focus"))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    module = importlib.util.module_from_spec(spec)
    loader.exec_module(module)
    rows = [
        {"id": "0x01", "desktop": 0, "wm_class": "tk.Tk"},
        {"id": "0x02", "desktop": -1, "wm_class": "panel.Panel"},
        {"id": "0x03", "desktop": 0, "wm_class": "tk #2.Tk"},
    ]
    with (
        patch.object(module, "list_windows", return_value=rows),
        patch.object(module, "focus") as focus,
    ):
        for args, wanted in (
            (["--class", r"tk #2\.Tk"], "0x03"),
            (["--class", "tk"], "0x03"),
            (["--slot", "1"], "0x01"),
            (["--slot", "2"], "0x03"),
        ):
            with patch.object(sys, "argv", ["desk-focus", *args]):
                assert module.main() == 0
                focus.assert_called_with(wanted)
        focus.reset_mock()
        for args in (["--class", "browser"], ["--slot", "3"]):
            with patch.object(sys, "argv", ["desk-focus", *args]):
                assert module.main() == 1
                focus.assert_not_called()
        with (
            patch.object(sys, "argv", ["desk-focus", "--class", "browser", "--launch", "app"]),
            patch.object(module.subprocess, "Popen") as launch,
        ):
            assert module.main() == 0
            launch.assert_called_once_with(
                ["app"],
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        for args in (["--slot", "0"], ["--class", "["]):
            with patch.object(sys, "argv", ["desk-focus", *args]):
                try:
                    module.main()
                except SystemExit as error:
                    assert error.code == 2
                else:
                    raise AssertionError(f"accepted {args}")


def test_the_key_map_is_the_whole_keyboard_section() -> None:
    if not os.path.isfile(_STOCK_RC):
        print("skip: no stock Openbox rc.xml")
        return
    keymap = json.loads((ROOT / "docker" / "keymap.json").read_text(encoding="utf-8"))["bindings"]
    with tempfile.TemporaryDirectory() as tmp:
        target = os.path.join(tmp, "rc.xml")
        _configure(target)
        listing = keybindings.list_keybindings(target)
        assert os.path.isfile(os.path.join(tmp, "keymap.json"))
    listed = [item["send_key"][0] for item in listing["keybindings"]]
    assert sorted(listed) == sorted(binding["key"] for binding in keymap), (
        "stock bindings must not survive"
    )
    assert not [key for key in listed if "win" in key], "no binding may use the Super key"
    by_key = {item["send_key"][0]: item for item in listing["keybindings"]}
    assert by_key["ctrl+alt+left"]["description"] == "tile the focused window to the left half"
    assert (
        by_key["ctrl+alt+t"]["description"] == "focus the terminal, or open one if none is running"
    )
    assert by_key["ctrl+alt+t"]["group"] == "Focus"
    assert all(item["description"] for item in listing["keybindings"])


def test_a_bad_key_map_is_refused() -> None:
    if not os.path.isfile(_STOCK_RC):
        print("skip: no stock Openbox rc.xml")
        return
    with tempfile.TemporaryDirectory() as tmp:
        bad = os.path.join(tmp, "bad.json")
        for bindings in (
            [{"key": "ctrl+alt+x", "description": "x", "actions": [{"name": "Close"}]}] * 2,
            [{"key": "hyper+x", "description": "x", "actions": [{"name": "Close"}]}],
            [{"key": "ctrl+alt+x", "description": "", "actions": [{"name": "Close"}]}],
        ):
            Path(bad).write_text(json.dumps({"bindings": bindings}), encoding="utf-8")
            result = subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "docker" / "configure-openbox.py"),
                    _STOCK_RC,
                    bad,
                    os.path.join(tmp, "rc.xml"),
                ],
                capture_output=True,
                text=True,
            )
            assert result.returncode != 0, bindings


def test_the_keyboard_doc_lists_exactly_the_key_map() -> None:
    table = subprocess.run(
        [
            sys.executable,
            str(ROOT / "docker" / "configure-openbox.py"),
            "--markdown",
            str(ROOT / "docker" / "keymap.json"),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    doc = (ROOT / "docs" / "keyboard.md").read_text(encoding="utf-8")
    assert table in doc, (
        "docs/keyboard.md is out of date: paste the output of configure-openbox.py --markdown docker/keymap.json"
    )


def main() -> None:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for test in tests:
        test()
    print(json.dumps({"result": "process and keybinding tests passed", "tests": len(tests)}))


if __name__ == "__main__":
    main()
