"""Unit tests for the pure coordinate math in span.geometry."""

import pytest

from span.geometry import (
    Box,
    Display,
    align_boxes,
    aspect_resize,
    clamp_pos,
    fit_into_image,
    seed_layout,
    target_sizes,
    to_native_boxes,
)


# --- Display -------------------------------------------------------------------

def test_native_size_and_aspect_retina():
    d = Display(0, "Studio", 0, 0, 2560, 1440, 2.0)
    assert d.native_w == 5120
    assert d.native_h == 2880
    assert d.aspect == pytest.approx(16 / 9)
    assert d.native_label == "5120×2880"


def test_native_aspect_matches_points_aspect():
    # The locked aspect (native) must equal the points-space aspect used for seeding.
    d = Display(0, "X", 0, 0, 1920, 1080, 1.0)
    assert d.aspect == pytest.approx(1920 / 1080)


# --- seed_layout ---------------------------------------------------------------

def _within_image(box: Box, img_w, img_h, tol=1e-6):
    return (
        box.x >= -tol
        and box.y >= -tol
        and box.right <= img_w + tol
        and box.bottom <= img_h + tol
    )


def test_seed_two_displays_edge_to_edge_seam_lines_up():
    displays = [
        Display(0, "Left", 0, 0, 1000, 1000, 1.0),
        Display(1, "Right", 1000, 0, 1000, 1000, 1.0),
    ]
    img_w, img_h = 2000, 1000  # same aspect as the combined canvas → exact fit, k=1
    boxes = seed_layout(displays, img_w, img_h)

    assert boxes[0].right == pytest.approx(boxes[1].x)  # seam matches
    assert all(_within_image(b, img_w, img_h) for b in boxes.values())
    # aspect preserved per display
    for d in displays:
        b = boxes[d.index]
        assert b.w / b.h == pytest.approx(d.aspect)


def test_seed_honors_vertical_offset_and_differing_heights():
    # The real rig: top-aligned, right display taller and offset down (y=-360).
    displays = [
        Display(0, "Sceptre F24", 0, 0, 1920, 1080, 1.0),
        Display(1, "ED270U P2", 1920, -360, 2560, 1440, 1.0),
    ]
    img_w, img_h = 4480, 1440  # exact canvas aspect → k=1
    boxes = seed_layout(displays, img_w, img_h)

    # Both displays are top-aligned in this arrangement.
    assert boxes[0].y == pytest.approx(boxes[1].y)
    # Right display is taller.
    assert boxes[1].h > boxes[0].h
    # Seam lines up and everything stays in the image.
    assert boxes[0].right == pytest.approx(boxes[1].x)
    assert all(_within_image(b, img_w, img_h) for b in boxes.values())


def test_seed_fits_and_centers_when_aspect_differs():
    displays = [Display(0, "Mono", 0, 0, 1000, 1000, 1.0)]
    # Wide image: a square canvas should fit by height and be horizontally centered.
    img_w, img_h = 2000, 1000
    boxes = seed_layout(displays, img_w, img_h)
    b = boxes[0]
    assert b.h == pytest.approx(1000)          # fit by height
    assert b.w == pytest.approx(1000)
    assert b.x == pytest.approx(500)           # centered: (2000-1000)/2
    assert b.y == pytest.approx(0)
    assert _within_image(b, img_w, img_h)


def test_seed_single_display_fills_within_bounds():
    displays = [Display(0, "Solo", 0, 0, 1600, 900, 1.0)]
    img_w, img_h = 1600, 900
    boxes = seed_layout(displays, img_w, img_h)
    b = boxes[0]
    assert b.x == pytest.approx(0)
    assert b.y == pytest.approx(0)
    assert b.w == pytest.approx(1600)
    assert b.h == pytest.approx(900)


def test_seed_empty():
    assert seed_layout([], 100, 100) == {}


# --- clamp_pos -----------------------------------------------------------------

@pytest.mark.parametrize(
    "x,y,expected",
    [
        (-50, -50, (0, 0)),                 # off top-left
        (5000, 5000, (900, 800)),           # off bottom-right → clamp to max
        (100, 100, (100, 100)),             # inside → unchanged
    ],
)
def test_clamp_pos(x, y, expected):
    # rect 100x200 inside a 1000x1000 image → max pos (900, 800)
    assert clamp_pos(x, y, 100, 200, 1000, 1000) == pytest.approx(expected)


def test_clamp_pos_oversized_rect_pins_to_origin():
    # rect bigger than image → pinned to (0, 0)
    assert clamp_pos(50, 50, 2000, 2000, 1000, 1000) == pytest.approx((0, 0))


# --- aspect_resize -------------------------------------------------------------

def test_aspect_resize_locks_aspect():
    w, h = aspect_resize(100, 100, 400, 150, aspect=2.0, img_w=1000, img_h=1000)
    assert w / h == pytest.approx(2.0)
    assert (w, h) == pytest.approx((300, 150))


def test_aspect_resize_driven_by_larger_axis():
    # Pulling mostly downward should still grow the aspect-locked rect.
    w, h = aspect_resize(0, 0, 50, 300, aspect=2.0, img_w=10000, img_h=10000)
    assert w / h == pytest.approx(2.0)
    assert h == pytest.approx(300)   # vertical pull dominates → h follows the drag
    assert w == pytest.approx(600)


def test_aspect_resize_clamps_to_image_bounds():
    # Anchored near the right edge; a huge drag must be clamped to stay inside.
    w, h = aspect_resize(900, 100, 5000, 5000, aspect=2.0, img_w=1000, img_h=1000)
    assert w == pytest.approx(100)         # only 100px to the right edge
    assert h == pytest.approx(50)
    assert 900 + w <= 1000 + 1e-6
    assert 100 + h <= 1000 + 1e-6


def test_aspect_resize_min_size():
    w, h = aspect_resize(100, 100, 101, 101, aspect=2.0, img_w=1000, img_h=1000, min_w=24.0)
    assert w == pytest.approx(24.0)
    assert h == pytest.approx(12.0)


# --- PPI / physical size --------------------------------------------------------

def test_ppi_from_physical_size():
    # 1920px over 530mm ≈ 92 ppi
    d = Display(0, "S", 0, 0, 1920, 1080, 1.0, width_mm=530.0, height_mm=298.0)
    assert d.ppi == pytest.approx(92.0, abs=0.5)


def test_ppi_none_without_size():
    assert Display(0, "S", 0, 0, 1920, 1080, 1.0).ppi is None


def test_unit_size_modes():
    d = Display(0, "S", 0, 0, 1920, 1080, 1.0, width_mm=530.0, height_mm=298.0)  # ~92 ppi
    assert d.unit_size(native_mode=True, ppi_aware=False) == (1920.0, 1080.0)
    # PPI unit keeps native aspect exactly, proportional to physical size (inches).
    uw, uh = d.unit_size(native_mode=False, ppi_aware=True)
    assert uw / uh == pytest.approx(1920 / 1080, rel=1e-6)
    assert uw == pytest.approx(1920 / d.ppi)
    assert d.unit_size(native_mode=False, ppi_aware=False) == (1920.0, 1080.0)


# --- target_sizes ---------------------------------------------------------------

def _two_displays():
    return [
        Display(0, "L", 0, 0, 1920, 1080, 1.0),
        Display(1, "R", 1920, -360, 2560, 1440, 1.0),  # top-aligned, taller, offset down
    ]


def _two_displays_ppi():
    return [
        Display(0, "L", 0, 0, 1920, 1080, 1.0, width_mm=530.0, height_mm=298.0),    # ~92 ppi
        Display(1, "R", 1920, -360, 2560, 1440, 1.0, width_mm=602.0, height_mm=339.0),  # ~108 ppi
    ]


def test_target_sizes_native():
    displays = _two_displays()
    sizes = target_sizes(displays, {}, native_mode=True)
    assert sizes[0] == pytest.approx((1920, 1080))
    assert sizes[1] == pytest.approx((2560, 1440))


def test_target_sizes_ppi_densest_is_native_others_downsample():
    displays = _two_displays_ppi()
    current = {0: Box(0, 0, 100, 56), 1: Box(0, 0, 100, 56)}
    sizes = target_sizes(displays, current, ppi_aware=True)
    # Densest (R, ~108 ppi) lands at native size, keeping native aspect.
    assert sizes[1] == pytest.approx((2560, 1440), rel=2e-3)
    # Lower-PPI L gets a larger-than-native crop (→ downsampled, never upscaled).
    assert sizes[0][0] > 1920
    assert sizes[0][0] / sizes[0][1] == pytest.approx(1920 / 1080, rel=1e-6)  # no distortion


# --- align_boxes / shift / to_native -------------------------------------------

def test_align_vertical_only_changes_y():
    displays = _two_displays()
    current = {0: Box(0, 500, 1920, 1080), 1: Box(1920, 0, 2560, 1440)}
    out = align_boxes(displays, current, "v")
    assert out[0].x == pytest.approx(0)        # X preserved
    assert out[1].x == pytest.approx(1920)
    assert out[1].w == pytest.approx(2560)     # size preserved
    assert out[0].y == pytest.approx(500)
    assert out[1].y == pytest.approx(500)      # tops aligned for this rig


def test_align_horizontal_makes_edge_to_edge():
    displays = _two_displays()
    current = {0: Box(0, 0, 1920, 1080), 1: Box(3000, 0, 2560, 1440)}  # gap
    out = align_boxes(displays, current, "h")
    assert out[1].x == pytest.approx(out[0].right)   # gap closed, seam continuous


def test_align_both_ppi_seam_continuous_and_no_distortion():
    displays = _two_displays_ppi()
    current = {0: Box(0, 0, 1920, 1080), 1: Box(1920, 0, 2560, 1440)}
    out = align_boxes(displays, current, "both", ppi_aware=True)
    assert out[1].x == pytest.approx(out[0].right, rel=1e-3)  # seam continuous
    for b, d in ((out[0], displays[0]), (out[1], displays[1])):
        assert b.w / b.h == pytest.approx(d.aspect, rel=1e-6)  # native aspect kept


def test_fit_into_image_shifts_group_that_fits():
    boxes = {0: Box(-100, 50, 500, 300), 1: Box(400, 50, 500, 300)}
    out = fit_into_image(boxes, img_w=2000, img_h=1000)
    assert out[0].x == pytest.approx(0)         # shifted right by 100
    assert out[1].x == pytest.approx(500)       # relative gap preserved
    assert out[1].x - out[0].x == pytest.approx(boxes[1].x - boxes[0].x)


def test_fit_into_image_oversized_keeps_size_anchors_topleft():
    # Group (4000 wide) is wider than the image (2000): keep sizes (no scaling),
    # anchor the top-left on-screen, let the far edge overflow.
    boxes = {0: Box(0, 0, 2000, 1000), 1: Box(2000, 0, 2000, 1000)}
    out = fit_into_image(boxes, img_w=2000, img_h=1000)
    assert out[0].w == pytest.approx(2000)             # not shrunk
    assert out[1].x == pytest.approx(out[0].right)     # seam preserved
    assert min(b.x for b in out.values()) >= -1e-6     # left edge on-screen
    assert max(b.right for b in out.values()) > 2000   # far edge allowed to overflow


def test_fit_into_image_negative_group_shifts_right():
    boxes = {0: Box(-500, 0, 1000, 500), 1: Box(500, 0, 1000, 500)}  # 2000 wide == image
    out = fit_into_image(boxes, img_w=2000, img_h=1000)
    assert out[0].x == pytest.approx(0)                # left edge anchored at 0
    assert out[1].x == pytest.approx(out[0].right)     # seam preserved
    assert out[0].w == pytest.approx(1000)             # not scaled


def test_to_native_boxes():
    displays = [Display(0, "S", 0, 0, 1920, 1080, 2.0)]  # native 3840x2160
    out = to_native_boxes(displays, {0: Box(100, 100, 800, 450)})
    assert (out[0].w, out[0].h) == pytest.approx((3840, 2160))
    assert (out[0].x, out[0].y) == pytest.approx((100, 100))  # top-left preserved
