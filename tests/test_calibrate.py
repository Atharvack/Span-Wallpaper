"""Tests for the calibration grid and seam-offset math."""

from span.calibrate import calibration_shift, make_crop_grid, make_grid


def test_make_grid_dimensions():
    g = make_grid(800, 400, 100)
    assert g.size == (800, 400)
    assert g.mode == "RGB"


def test_make_crop_grid_renders_at_native_size():
    # Rendered directly at native resolution (crisp), whatever the source crop region.
    g = make_crop_grid(258.0, 205.0, 1555.0, 875.0, 1920, 1080, 120)
    assert g.size == (1920, 1080)
    assert g.mode == "RGB"


def test_shift_zero_when_numbers_match():
    # Aligned: same number meets same number → no correction.
    assert calibration_shift(row_l=5, row_r=5, col_l=3, col_r=3, cell=120) == (0, 0)


def test_shift_vertical_moves_right_up_when_it_reads_higher():
    # Right shows row 6 where left shows row 3 → right is cropping too low → move it up.
    dx, dy = calibration_shift(row_l=3, row_r=6, col_l=0, col_r=0, cell=120)
    assert dx == 0
    assert dy == -360  # -(6-3)*120


def test_shift_vertical_other_direction():
    dx, dy = calibration_shift(row_l=6, row_r=3, col_l=0, col_r=0, cell=120)
    assert dy == 360  # -(3-6)*120


def test_shift_horizontal():
    dx, dy = calibration_shift(row_l=0, row_r=0, col_l=8, col_r=6, cell=120)
    assert dy == 0
    assert dx == 240  # -(6-8)*120
