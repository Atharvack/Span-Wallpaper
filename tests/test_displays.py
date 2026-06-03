"""Tests for display detection parsing/robustness (osascript is monkeypatched)."""

import json

import pytest

from span import displays as disp
from span.displays import DisplayDetectionError, detect_displays


class _Proc:
    def __init__(self, stdout, returncode=0, stderr=""):
        self.stdout = stdout
        self.returncode = returncode
        self.stderr = stderr


def _patch(monkeypatch, proc):
    monkeypatch.setattr(disp.subprocess, "run", lambda *a, **k: proc)


def test_valid_displays_parsed_and_sorted_left_to_right(monkeypatch):
    data = json.dumps(
        [
            {"index": 0, "name": "B", "x": 1920, "y": 0, "w": 2560, "h": 1440, "scale": 1},
            {"index": 1, "name": "A", "x": 0, "y": 0, "w": 1920, "h": 1080, "scale": 2},
        ]
    )
    _patch(monkeypatch, _Proc(data))
    ds = detect_displays()
    assert [d.name for d in ds] == ["A", "B"]  # sorted by global x
    assert ds[0].native_w == 3840  # 1920 * scale 2


def test_valid_json_wrong_shape_raises_detection_error(monkeypatch):
    _patch(monkeypatch, _Proc('{"oops": 1}'))  # valid JSON, but a dict not a list
    with pytest.raises(DisplayDetectionError):
        detect_displays()


def test_missing_keys_raises_detection_error(monkeypatch):
    _patch(monkeypatch, _Proc('[{"index": 0}]'))  # valid list, malformed entry
    with pytest.raises(DisplayDetectionError):
        detect_displays()


def test_invalid_json_raises_detection_error(monkeypatch):
    _patch(monkeypatch, _Proc("not json at all"))
    with pytest.raises(DisplayDetectionError):
        detect_displays()


def test_empty_list_raises_detection_error(monkeypatch):
    _patch(monkeypatch, _Proc("[]"))
    with pytest.raises(DisplayDetectionError):
        detect_displays()


def test_nonzero_exit_raises_detection_error(monkeypatch):
    _patch(monkeypatch, _Proc("", returncode=1, stderr="boom"))
    with pytest.raises(DisplayDetectionError):
        detect_displays()
