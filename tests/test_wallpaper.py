"""Tests for setting the desktop image.

``osascript`` is monkeypatched throughout — these verify the request we build and how we
read the reply, never that a real desktop changed.
"""

import json
import subprocess

import pytest

from span.calibration import wallpaper as wp
from span.calibration.wallpaper import (
    Assignment,
    WallpaperError,
    assignments_from_exports,
    current_wallpapers,
    set_wallpapers,
)


class _Proc:
    def __init__(self, stdout="", returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


@pytest.fixture
def two_files(tmp_path):
    a, b = tmp_path / "left.png", tmp_path / "right.png"
    a.write_bytes(b"x")
    b.write_bytes(b"x")
    return [Assignment("ED270U P2", a), Assignment("Sceptre F24", b)]


def _reply(assignments, ok=True, error=""):
    return json.dumps([{"name": a.display_name, "path": str(a.path), "ok": ok,
                        "error": error} for a in assignments])


def test_each_display_is_set_to_its_own_file(monkeypatch, two_files):
    captured = {}

    def _run(cmd, **kw):
        captured["script"] = cmd[-1]
        return _Proc(_reply(two_files))

    monkeypatch.setattr(wp.subprocess, "run", _run)
    results = set_wallpapers(two_files)

    assert [r.ok for r in results] == [True, True]
    assert {r.display_name for r in results} == {"ED270U P2", "Sceptre F24"}
    # The mapping must reach the script, keyed by the same name detection reports.
    assert "ED270U P2" in captured["script"]
    assert "left.png" in captured["script"]


def _capture_script(monkeypatch, assignments) -> dict:
    """Run set_wallpapers with osascript stubbed, returning what we would have run."""
    captured = {}

    def _run(cmd, **kw):
        captured["script"] = cmd[-1]
        return _Proc(_reply(assignments))

    monkeypatch.setattr(wp.subprocess, "run", _run)
    set_wallpapers(assignments)
    return captured


def test_scaling_is_pinned_explicitly(monkeypatch, two_files):
    """Left to itself macOS might rescale a native-resolution crop and undo the maths."""
    script = _capture_script(monkeypatch, two_files)["script"]
    assert "NSWorkspaceDesktopImageScalingKey" in script
    assert "NSWorkspaceDesktopImageAllowClippingKey" in script


def test_paths_are_absolute_in_the_request(monkeypatch, tmp_path, two_files):
    """macOS keeps a reference to the file, so a relative path would be meaningless."""
    script = _capture_script(monkeypatch, two_files)["script"]
    assert str(tmp_path.resolve()) in script


def test_a_missing_file_is_refused_before_touching_the_os(monkeypatch, tmp_path):
    called = {"ran": False}

    def _run(*a, **k):
        called["ran"] = True
        return _Proc("[]")

    monkeypatch.setattr(wp.subprocess, "run", _run)
    with pytest.raises(WallpaperError, match="do not exist"):
        set_wallpapers([Assignment("X", tmp_path / "ghost.png")])
    assert not called["ran"]


def test_one_failed_display_does_not_hide_the_others(monkeypatch, two_files):
    payload = json.loads(_reply(two_files))
    payload[1]["ok"] = False
    payload[1]["error"] = "screen went away"
    monkeypatch.setattr(wp.subprocess, "run", lambda *a, **k: _Proc(json.dumps(payload)))

    results = set_wallpapers(two_files)
    assert [r.ok for r in results] == [True, False]
    assert results[1].error == "screen went away"


def test_a_display_no_screen_matched_is_reported(monkeypatch, two_files):
    """Unplugged mid-run: the reply omits it, so we synthesise a failure rather than
    silently succeeding."""
    payload = json.loads(_reply(two_files))[:1]
    monkeypatch.setattr(wp.subprocess, "run", lambda *a, **k: _Proc(json.dumps(payload)))

    results = set_wallpapers(two_files)
    missing = [r for r in results if r.display_name == "Sceptre F24"]
    assert missing and not missing[0].ok
    assert "no matching screen" in missing[0].error


def test_nonzero_exit_raises_with_stderr(monkeypatch, two_files):
    monkeypatch.setattr(wp.subprocess, "run",
                        lambda *a, **k: _Proc("", returncode=1, stderr="denied"))
    with pytest.raises(WallpaperError, match="denied"):
        set_wallpapers(two_files)


def test_unreadable_reply_raises(monkeypatch, two_files):
    monkeypatch.setattr(wp.subprocess, "run", lambda *a, **k: _Proc("not json"))
    with pytest.raises(WallpaperError, match="Unreadable"):
        set_wallpapers(two_files)


def test_wrong_reply_shape_raises(monkeypatch, two_files):
    monkeypatch.setattr(wp.subprocess, "run", lambda *a, **k: _Proc('{"a": 1}'))
    with pytest.raises(WallpaperError, match="Unexpected response"):
        set_wallpapers(two_files)


def test_timeout_raises(monkeypatch, two_files):
    def _boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="osascript", timeout=20)
    monkeypatch.setattr(wp.subprocess, "run", _boom)
    with pytest.raises(WallpaperError, match="timed out"):
        set_wallpapers(two_files)


def test_setting_nothing_is_a_no_op(monkeypatch):
    monkeypatch.setattr(wp.subprocess, "run",
                        lambda *a, **k: pytest.fail("should not shell out"))
    assert set_wallpapers([]) == []


def test_current_wallpapers_parses_the_reply(monkeypatch):
    monkeypatch.setattr(wp.subprocess, "run",
                        lambda *a, **k: _Proc('{"A": "/a.png", "B": null}'))
    assert current_wallpapers() == {"A": "/a.png"}   # nulls dropped


def test_current_wallpapers_degrades_quietly(monkeypatch):
    """Read-only helper — a failure here must not break an export."""
    monkeypatch.setattr(wp.subprocess, "run", lambda *a, **k: _Proc("garbage"))
    assert current_wallpapers() == {}


def test_assignments_from_exports_accepts_plain_tuples(tmp_path):
    out = assignments_from_exports([("A", tmp_path / "a.png")])
    assert out[0].display_name == "A"
    assert out[0].path.name == "a.png"


# --- capture / restore ------------------------------------------------------------

@pytest.fixture
def span_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SPAN_HOME", str(tmp_path))
    return tmp_path


def test_capture_writes_a_snapshot_that_loads_back(monkeypatch, span_home):
    monkeypatch.setattr(wp.subprocess, "run",
                        lambda *a, **k: _Proc('{"A": "/a.png", "B": "/b.png"}'))
    captured = wp.capture()
    assert captured == {"A": "/a.png", "B": "/b.png"}
    assert wp.load_snapshot() == captured
    assert wp.snapshot_path().name == wp.SNAPSHOT_NAME


def test_capture_survives_an_unwritable_directory(monkeypatch, tmp_path):
    """A snapshot that cannot be written must not block the set — the in-memory copy is
    what the confirmation dialog uses."""
    monkeypatch.setenv("SPAN_HOME", str(tmp_path / "nope"))
    monkeypatch.setattr(wp.subprocess, "run", lambda *a, **k: _Proc('{"A": "/a.png"}'))
    monkeypatch.setattr(wp.Path, "mkdir",
                        lambda self, **kw: (_ for _ in ()).throw(OSError("read-only")))
    assert wp.capture() == {"A": "/a.png"}


def test_load_snapshot_is_empty_when_there_is_none(span_home):
    assert wp.load_snapshot() == {}


def test_load_snapshot_survives_a_corrupt_file(span_home):
    wp.snapshot_path().parent.mkdir(parents=True, exist_ok=True)
    wp.snapshot_path().write_text("{not json", encoding="utf-8")
    assert wp.load_snapshot() == {}


def test_restore_puts_the_recorded_files_back(monkeypatch, span_home, tmp_path):
    original = tmp_path / "before.png"
    original.write_bytes(b"x")
    captured = {}

    def _run(cmd, **kw):
        captured["script"] = cmd[-1]
        return _Proc(json.dumps([{"name": "A", "path": str(original), "ok": True}]))

    monkeypatch.setattr(wp.subprocess, "run", _run)
    results = wp.restore({"A": str(original)})
    assert [r.ok for r in results] == [True]
    assert "before.png" in captured["script"]


def test_restore_reports_an_original_that_has_since_been_deleted(monkeypatch, span_home,
                                                                 tmp_path):
    monkeypatch.setattr(wp.subprocess, "run",
                        lambda *a, **k: pytest.fail("should not shell out"))
    results = wp.restore({"A": str(tmp_path / "deleted.png")})
    assert len(results) == 1
    assert not results[0].ok
    assert "gone" in results[0].error


def test_restoring_nothing_is_a_no_op(monkeypatch, span_home):
    monkeypatch.setattr(wp.subprocess, "run",
                        lambda *a, **k: pytest.fail("should not shell out"))
    assert wp.restore({}) == []


# --- clearing the view ------------------------------------------------------------

def test_hide_and_unhide_degrade_quietly_without_appkit():
    """Outside a Qt app NSApplication is not registered; that must not raise."""
    assert wp.hide_other_applications() in (True, False)
    assert wp.unhide_all_applications() in (True, False)


def test_objc_bridge_returns_none_when_the_class_is_missing(monkeypatch):
    monkeypatch.setattr(wp.ctypes.util, "find_library", lambda name: None)
    assert wp._objc() is None


def test_send_is_a_no_op_without_a_bridge(monkeypatch):
    monkeypatch.setattr(wp, "_objc", lambda: None)
    assert wp._send(b"hideOtherApplications:") is False
