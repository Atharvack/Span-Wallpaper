"""Tests for CLI helpers: output-dir confinement and EXIF-aware image loading."""

import io

import pytest
from PIL import Image

from span import cli


# --- resolve_out_dir confinement ----------------------------------------------

def test_out_dir_defaults_to_span_root(monkeypatch, tmp_path):
    monkeypatch.setenv("SPAN_ROOT", str(tmp_path))
    assert cli.resolve_out_dir(None) == tmp_path.resolve()


def test_out_dir_inside_root_ok(monkeypatch, tmp_path):
    monkeypatch.setenv("SPAN_ROOT", str(tmp_path))
    sub = tmp_path / "crops"
    assert cli.resolve_out_dir(str(sub)) == sub.resolve()


def test_out_dir_outside_root_rejected(monkeypatch, tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    outside = tmp_path / "elsewhere"
    monkeypatch.setenv("SPAN_ROOT", str(root))
    with pytest.raises(cli.OutDirError):
        cli.resolve_out_dir(str(outside))


def test_resolve_out_dir_does_not_create_directory(monkeypatch, tmp_path):
    # Cancelling the dialog must not leave an empty output directory behind.
    monkeypatch.setenv("SPAN_ROOT", str(tmp_path))
    sub = tmp_path / "crops"
    cli.resolve_out_dir(str(sub))
    assert not sub.exists()


def test_out_dir_no_root_uses_arg(monkeypatch, tmp_path):
    monkeypatch.delenv("SPAN_ROOT", raising=False)
    target = tmp_path / "anywhere"
    assert cli.resolve_out_dir(str(target)) == target.resolve()


# --- EXIF-aware loading --------------------------------------------------------

def test_load_image_applies_exif_orientation(tmp_path):
    # Orientation 6 = rotate 90°; a 40x20 image should become 20x40 after transpose.
    img = Image.new("RGB", (40, 20), (123, 222, 11))
    exif = img.getexif()
    exif[274] = 6  # 274 = Orientation tag
    path = tmp_path / "rot.jpg"
    img.save(path, exif=exif)

    loaded = cli._load_image(path)
    assert loaded.size == (20, 40)
    assert loaded.mode == "RGB"


def test_load_image_bad_file_exits(tmp_path):
    bad = tmp_path / "not-an-image.png"
    bad.write_bytes(b"this is not a PNG")
    with pytest.raises(SystemExit):
        cli._load_image(bad)
