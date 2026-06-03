"""Unit tests for the pure coordinate math in span.geometry."""

import pytest

from span.geometry import (
    Box,
    Display,
    aspect_resize,
    clamp_pos,
    seed_layout,
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
