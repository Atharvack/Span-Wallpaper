"""Tests for CLI helpers: output-dir confinement and EXIF-aware image loading."""

import pytest
from PIL import Image

from span import cli
from span.image_processing.loader import ImageLoadError, load_image


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
    monkeypatch.setenv("SPAN_ROOT", str(root))
    with pytest.raises(cli.OutDirError):
        cli.resolve_out_dir(str(tmp_path / "elsewhere"))


def test_traversal_out_of_root_is_rejected(monkeypatch, tmp_path):
    """Paths are resolved before comparison, so '..' cannot escape the boundary."""
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setenv("SPAN_ROOT", str(root))
    with pytest.raises(cli.OutDirError):
        cli.resolve_out_dir(str(root / ".." / "elsewhere"))


def test_sibling_prefix_is_not_treated_as_inside(monkeypatch, tmp_path):
    """Containment is a path-component test, not a string prefix test."""
    root = tmp_path / "span-root"
    root.mkdir()
    (tmp_path / "span-root-evil").mkdir()
    monkeypatch.setenv("SPAN_ROOT", str(root))
    with pytest.raises(cli.OutDirError):
        cli.resolve_out_dir(str(tmp_path / "span-root-evil"))


def test_resolve_does_not_create_the_directory(monkeypatch, tmp_path):
    """Quitting without exporting must not leave an empty directory behind."""
    monkeypatch.setenv("SPAN_ROOT", str(tmp_path))
    target = tmp_path / "not-yet"
    assert cli.resolve_out_dir(str(target)) == target.resolve()
    assert not target.exists()


def test_out_dir_without_root_uses_the_argument(monkeypatch, tmp_path):
    monkeypatch.delenv("SPAN_ROOT", raising=False)
    assert cli.resolve_out_dir(str(tmp_path)) == tmp_path.resolve()


# --- image loading -------------------------------------------------------------

def test_exif_orientation_is_applied_at_load(tmp_path):
    """Orientation is applied once, at the boundary, so preview and crop agree."""
    path = tmp_path / "rot.jpg"
    img = Image.new("RGB", (200, 100), (10, 20, 30))
    exif = img.getexif()
    exif[274] = 6  # rotate 90° CW
    img.save(path, exif=exif)

    loaded = load_image(path)
    assert (loaded.width, loaded.height) == (100, 200)


def test_a_file_that_is_not_an_image_raises(tmp_path):
    bad = tmp_path / "nope.png"
    bad.write_text("definitely not a png", encoding="utf-8")
    with pytest.raises(ImageLoadError):
        load_image(bad)


def test_a_missing_file_raises(tmp_path):
    with pytest.raises(ImageLoadError):
        load_image(tmp_path / "absent.png")


def test_loaded_images_are_rgb(tmp_path):
    path = tmp_path / "grey.png"
    Image.new("L", (50, 50), 128).save(path)
    assert load_image(path).mode == "RGB"


# --- argument parsing ----------------------------------------------------------

def test_parser_accepts_a_bare_calibrate_run():
    args = cli.build_parser().parse_args(["--calibrate"])
    assert args.calibrate and args.image is None


def test_parser_accepts_an_image_and_out_dir():
    args = cli.build_parser().parse_args(["pic.jpg", "--out", "/tmp/x"])
    assert args.image == "pic.jpg" and args.out == "/tmp/x"


def test_main_with_no_image_waits_on_the_welcome_screen(monkeypatch, tmp_path):
    """`span` with no arguments should ask for an image, not refuse to start."""
    monkeypatch.setenv("SPAN_ROOT", str(tmp_path))
    monkeypatch.setattr(cli, "detect_displays", lambda: [_display()])

    seen = {}

    def _fake_run(displays, config, image, **kw):
        seen.update(kw, image=image)
        return []

    monkeypatch.setattr("span.gui.run", _fake_run)
    assert cli.main([]) == 0
    assert seen["image"] is None
    # No image and no --calibrate: the welcome window waits for a click. Nothing is
    # auto-opened over it.
    assert seen["start_mode"] is None


def test_main_with_an_image_passes_its_path_through(monkeypatch, tmp_path):
    monkeypatch.setenv("SPAN_ROOT", str(tmp_path))
    monkeypatch.setattr(cli, "detect_displays", lambda: [_display()])
    path = tmp_path / "pic.png"
    Image.new("RGB", (400, 200), (1, 2, 3)).save(path)

    seen = {}

    def _fake_run(displays, config, image, **kw):
        seen.update(kw, image=image)
        return []

    monkeypatch.setattr("span.gui.run", _fake_run)
    assert cli.main([str(path)]) == 0
    assert seen["image"] is not None
    assert seen["image_path"] == path


def test_main_reports_a_missing_image(monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("SPAN_ROOT", str(tmp_path))
    monkeypatch.setattr(cli, "detect_displays", lambda: [_display()])
    assert cli.main([str(tmp_path / "ghost.png")]) == 1
    assert "image not found" in capsys.readouterr().err


def _display():
    from span.algorithm.displays import Display
    return Display(0, "X", 0, 0, 1920, 1080, 1.0, 1, 530.0869485606318, 298.0)


def test_exports_default_to_tmp_not_the_working_directory(monkeypatch, tmp_path):
    """Exporting used to scatter multi-megabyte PNGs wherever you ran the command."""
    from span import paths
    monkeypatch.delenv("SPAN_ROOT", raising=False)
    monkeypatch.setenv("SPAN_HOME", str(tmp_path))
    assert cli.resolve_out_dir(None) == paths.tmp_dir().resolve()
