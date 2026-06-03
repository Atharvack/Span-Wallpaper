"""Tests for crop/resample/save and the offscreen GUI smoke-test."""

import pytest
from PIL import Image

from span.export import export_all, export_crop, safe_name
from span.geometry import Box, Display, seed_layout


def _solid_color(img: Image.Image):
    """Return the single RGB color of a solid image, or None if not solid."""
    colors = img.convert("RGB").getcolors(maxcolors=4)
    if colors and len(colors) == 1:
        return colors[0][1]
    return None


def test_safe_name():
    assert safe_name("Studio Display") == "Studio-Display"
    assert safe_name("DELL U2720Q") == "DELL-U2720Q"
    assert safe_name("///") == "display"


def test_export_picks_correct_region_per_display(tmp_path):
    # Left half red, right half blue; one display over each half.
    img = Image.new("RGB", (2000, 1000), (255, 0, 0))
    img.paste((0, 0, 255), (1000, 0, 2000, 1000))
    displays = [
        Display(0, "Left", 0, 0, 1000, 1000, 1.0),
        Display(1, "Right", 1000, 0, 1000, 1000, 1.0),
    ]
    boxes = seed_layout(displays, img.width, img.height)
    # Sanity: the seam must fall exactly on the color boundary.
    assert boxes[0].right == pytest.approx(1000)

    results = export_all(img, displays, boxes, tmp_path, "wall")
    assert len(results) == 2

    left_img = Image.open(results[0].path)
    right_img = Image.open(results[1].path)
    # Solid colors survive resampling exactly → crop math is verifiable.
    assert _solid_color(left_img) == (255, 0, 0)
    assert _solid_color(right_img) == (0, 0, 255)


def test_export_resamples_to_native_resolution(tmp_path):
    img = Image.new("RGB", (1280, 720), (10, 20, 30))
    d = Display(0, "Mono", 0, 0, 1920, 1080, 1.0)  # native 1920x1080
    box = Box(0, 0, 1280, 720)
    res = export_crop(img, d, box, tmp_path, "x.png")
    out = Image.open(res.path)
    assert out.size == (1920, 1080)
    assert res.upscaled is True  # 1280<1920 → flagged


def test_export_off_image_box_clamped_in_bounds(tmp_path):
    # A box entirely off the right edge must clamp to a valid in-bounds crop, not crop
    # past the edge (which previously produced a black strip).
    fill = (10, 20, 30)
    img = Image.new("RGB", (100, 100), fill)
    d = Display(0, "D", 0, 0, 50, 50, 1.0)  # native 50x50
    res = export_crop(img, d, Box(500, 10, 50, 50), tmp_path, "oob.png")
    out = Image.open(res.path).convert("RGB")
    assert out.size == (50, 50)
    assert out.getcolors(maxcolors=4) == [(50 * 50, fill)]  # in-bounds fill, not black


def test_export_not_upscaled_when_source_larger(tmp_path):
    img = Image.new("RGB", (4000, 4000), (1, 2, 3))
    d = Display(0, "Mono", 0, 0, 1920, 1080, 1.0)
    box = Box(0, 0, 3840, 2160)
    res = export_crop(img, d, box, tmp_path, "x.png")
    assert res.upscaled is False


def test_export_filenames_dedup_identical_displays(tmp_path):
    img = Image.new("RGB", (2000, 1000), (0, 0, 0))
    displays = [
        Display(0, "Mon", 0, 0, 1000, 1000, 1.0),
        Display(1, "Mon", 1000, 0, 1000, 1000, 1.0),  # same name + native res
    ]
    boxes = seed_layout(displays, img.width, img.height)
    results = export_all(img, displays, boxes, tmp_path, "wall")
    names = sorted(r.path.name for r in results)
    assert names == ["wall_Mon_1000x1000_0.png", "wall_Mon_1000x1000_1.png"]


def test_export_filename_no_suffix_when_unique(tmp_path):
    img = Image.new("RGB", (2000, 1000), (0, 0, 0))
    displays = [
        Display(0, "Left", 0, 0, 1000, 1000, 1.0),
        Display(1, "Right", 1000, 0, 1000, 1000, 1.0),
    ]
    boxes = seed_layout(displays, img.width, img.height)
    results = export_all(img, displays, boxes, tmp_path, "wall")
    names = sorted(r.path.name for r in results)
    assert names == ["wall_Left_1000x1000.png", "wall_Right_1000x1000.png"]


# --- offscreen GUI smoke-test --------------------------------------------------

@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    yield app


def test_dialog_builds_one_item_per_display(qapp):
    from span.gui import SpanDialog

    img = Image.new("RGB", (3000, 1000), (50, 50, 50))
    displays = [
        Display(0, "Left", 0, 0, 1920, 1080, 1.0),
        Display(1, "Right", 1920, 0, 2560, 1440, 1.0),
    ]
    dlg = SpanDialog(img, displays)
    try:
        boxes = dlg.collect_boxes()
        assert set(boxes) == {0, 1}
        for d in displays:
            b = boxes[d.index]
            # within image
            assert b.x >= -1e-6 and b.y >= -1e-6
            assert b.right <= img.width + 1e-6 and b.bottom <= img.height + 1e-6
            # aspect locked to native
            assert b.w / b.h == pytest.approx(d.aspect, rel=1e-3)
    finally:
        dlg.deleteLater()


def test_dialog_reset_restores_seed(qapp):
    from span.gui import SpanDialog

    img = Image.new("RGB", (3000, 1000), (50, 50, 50))
    displays = [Display(0, "Solo", 0, 0, 1920, 1080, 1.0)]
    dlg = SpanDialog(img, displays)
    try:
        seed = seed_layout(displays, img.width, img.height)[0]
        # Move the item, then reset.
        dlg._items[0].set_box(Box(10, 10, 200, 112))
        dlg._reset()
        after = dlg.collect_boxes()[0]
        assert (after.x, after.y, after.w, after.h) == pytest.approx(
            (seed.x, seed.y, seed.w, seed.h)
        )
    finally:
        dlg.deleteLater()
