"""Tests for display detection parsing and its failure modes.

``osascript`` is monkeypatched throughout, so every branch runs on any machine and the
suite never touches real hardware.
"""

import json
import subprocess

import pytest

from span.algorithm import displays as disp
from span.algorithm.displays import DisplayDetectionError, detect_displays, signature


class _Proc:
    def __init__(self, stdout, returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def _patch(monkeypatch, proc):
    monkeypatch.setattr(disp.subprocess, "run", lambda *a, **k: proc)
    # EDID lookup goes through ctypes; keep it out of the parsing tests.
    monkeypatch.setattr(disp, "_screen_size_mm", lambda did: (None, None))


def _entry(**kw):
    base = {"index": 0, "name": "A", "x": 0, "y": 0, "w": 1920, "h": 1080,
            "scale": 1, "displayID": 1}
    base.update(kw)
    return base


def test_displays_are_sorted_left_to_right(monkeypatch):
    """Ordering is load-bearing: the leftmost panel is the calibration datum."""
    _patch(monkeypatch, _Proc(json.dumps([
        _entry(index=0, name="B", x=1920, w=2560, h=1440, scale=1, displayID=2),
        _entry(index=1, name="A", x=0, w=1920, h=1080, scale=2, displayID=1),
    ])))
    ds = detect_displays()
    assert [d.name for d in ds] == ["A", "B"]
    assert ds[0].native_w == 3840   # 1920 points at scale 2


def test_physical_size_is_attached_from_core_graphics(monkeypatch):
    monkeypatch.setattr(disp.subprocess, "run",
                        lambda *a, **k: _Proc(json.dumps([_entry(w=2560, h=1440)])))
    monkeypatch.setattr(disp, "_screen_size_mm", lambda did: (602.07, 329.51))
    d = detect_displays()[0]
    assert d.width_mm == pytest.approx(602.07)
    assert d.ppi == pytest.approx(108.0, abs=0.05)


def test_missing_edid_leaves_ppi_unknown(monkeypatch):
    _patch(monkeypatch, _Proc(json.dumps([_entry()])))
    assert detect_displays()[0].ppi is None


def test_valid_json_wrong_shape_raises(monkeypatch):
    _patch(monkeypatch, _Proc('{"oops": 1}'))
    with pytest.raises(DisplayDetectionError):
        detect_displays()


def test_missing_keys_raise(monkeypatch):
    _patch(monkeypatch, _Proc(json.dumps([{"index": 0, "name": "A"}])))
    with pytest.raises(DisplayDetectionError):
        detect_displays()


def test_invalid_json_raises_with_the_raw_output(monkeypatch):
    _patch(monkeypatch, _Proc("not json at all"))
    with pytest.raises(DisplayDetectionError, match="not json at all"):
        detect_displays()


def test_empty_list_raises(monkeypatch):
    _patch(monkeypatch, _Proc("[]"))
    with pytest.raises(DisplayDetectionError, match="No displays"):
        detect_displays()


def test_nonzero_exit_reports_stderr(monkeypatch):
    _patch(monkeypatch, _Proc("", returncode=1, stderr="osascript blew up"))
    with pytest.raises(DisplayDetectionError, match="osascript blew up"):
        detect_displays()


def test_timeout_raises(monkeypatch):
    def _boom(*a, **k):
        raise subprocess.TimeoutExpired(cmd="osascript", timeout=15)
    monkeypatch.setattr(disp.subprocess, "run", _boom)
    with pytest.raises(DisplayDetectionError, match="timed out"):
        detect_displays()


def test_signature_is_stable_across_reconnects(monkeypatch):
    """display_id is deliberately excluded — macOS reassigns it when you replug."""
    _patch(monkeypatch, _Proc(json.dumps([
        _entry(index=0, name="A", displayID=1),
        _entry(index=1, name="B", x=1920, displayID=2),
    ])))
    first = signature(detect_displays())

    _patch(monkeypatch, _Proc(json.dumps([
        _entry(index=0, name="A", displayID=77),
        _entry(index=1, name="B", x=1920, displayID=88),
    ])))
    assert signature(detect_displays()) == first


def test_signature_changes_when_a_different_monitor_appears(monkeypatch):
    _patch(monkeypatch, _Proc(json.dumps([_entry(name="A")])))
    a = signature(detect_displays())
    _patch(monkeypatch, _Proc(json.dumps([_entry(name="Different")])))
    assert signature(detect_displays()) != a
