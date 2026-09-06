"""Unit tests for the millimetre layout maths in span.algorithm.wall.

These assert *properties* rather than golden numbers — the seam closes, nothing upscales,
physical scale matches across panels — so the layout can be refactored without rewriting
the suite, while anything that breaks continuity fails immediately.
"""

import pytest

from span.algorithm.displays import Display
from span.algorithm.wall import (
    Box,
    Panel,
    choose_scale,
    clamp_offset,
    estate,
    fit_scale,
    native_scale,
    panels_from_displays,
    plan_layout,
    seam_positions,
)

# The reference desk: a 108 ppi 1440p panel beside a 92 ppi 1080p one.
ED = Display(0, "ED270U", 0, 0, 2560, 1440, 1.0, 3, 602.0740650318287, 329.5135085647171)
SC = Display(1, "Sceptre", 2560, 60, 1920, 1080, 1.0, 2, 530.0869485606318, 301.45054492321646)


def _panels(**kw):
    return panels_from_displays([ED, SC], **kw)


# --- Display ---------------------------------------------------------------------

def test_native_size_uses_backing_scale():
    retina = Display(0, "Studio", 0, 0, 2560, 1440, 2.0)
    assert (retina.native_w, retina.native_h) == (5120, 2880)


def test_ppi_from_physical_size():
    assert ED.ppi == pytest.approx(108.0, abs=0.01)
    assert SC.ppi == pytest.approx(92.0, abs=0.01)


def test_ppi_is_none_without_edid():
    assert Display(0, "X", 0, 0, 1920, 1080, 1.0).ppi is None
    assert Display(0, "X", 0, 0, 1920, 1080, 1.0, 1, 0.0, 0.0).ppi is None


# --- Panel -----------------------------------------------------------------------

def test_panel_physical_size_matches_edid():
    ed, sc = _panels()
    assert ed.width_mm == pytest.approx(602.07, abs=0.05)
    assert sc.width_mm == pytest.approx(530.09, abs=0.05)


def test_one_pixel_is_a_different_length_on_each_panel():
    """The premise of the whole project: a pixel is a count, not a length."""
    ed, sc = _panels()
    assert 1 / ed.px_per_mm == pytest.approx(0.2352, abs=0.001)
    assert 1 / sc.px_per_mm == pytest.approx(0.2761, abs=0.001)


def test_panels_are_edge_to_edge_without_a_gap():
    ed, sc = _panels()
    assert sc.x_mm == pytest.approx(ed.right_mm)


def test_gap_pushes_the_next_panel_along_by_exactly_that_many_mm():
    ed, sc = _panels(gaps_mm=[18.0])
    assert sc.x_mm == pytest.approx(ed.right_mm + 18.0)


def test_y_offset_places_the_panel_lower():
    _, sc = _panels(y_offsets_mm=[0.0, 67.18])
    assert sc.y_mm == pytest.approx(67.18)


def test_panels_reject_a_display_without_physical_size():
    blind = Display(1, "NoEDID", 2560, 0, 1920, 1080, 1.0)
    with pytest.raises(ValueError, match="physical size"):
        panels_from_displays([ED, blind])


def test_wrong_length_inputs_are_rejected():
    with pytest.raises(ValueError, match="gaps_mm"):
        panels_from_displays([ED, SC], gaps_mm=[1.0, 2.0])
    with pytest.raises(ValueError, match="y_offsets_mm"):
        panels_from_displays([ED, SC], y_offsets_mm=[0.0])


# --- estate ----------------------------------------------------------------------

def test_estate_width_accumulates_but_height_does_not():
    """Panels in a row add up across; they overlap vertically, so height is an extent."""
    ed, sc = _panels()
    est = estate([ed, sc])
    assert est.w_mm == pytest.approx(ed.width_mm + sc.width_mm)
    assert est.h_mm == pytest.approx(max(ed.height_mm, sc.height_mm))


def test_estate_height_grows_with_a_vertical_offset():
    est = estate(_panels(y_offsets_mm=[0.0, 67.18]))
    # The shorter panel now hangs below the taller one's bottom edge.
    assert est.h_mm == pytest.approx(67.18 + 298.17, abs=0.05)


def test_estate_accounts_for_a_panel_placed_higher():
    est = estate(_panels(y_offsets_mm=[0.0, -40.0]))
    assert est.y_mm == pytest.approx(-40.0)
    assert est.h_mm > 338.0


def test_estate_of_one_panel_is_that_panel():
    (p,) = panels_from_displays([ED])
    est = estate([p])
    assert (est.w_mm, est.h_mm) == pytest.approx((p.width_mm, p.height_mm))


def test_estate_needs_a_panel():
    with pytest.raises(ValueError):
        estate([])


def test_seam_sits_in_the_middle_of_the_bezel():
    panels = _panels(gaps_mm=[20.0])
    assert seam_positions(panels, [20.0])[0] == pytest.approx(panels[0].right_mm + 10.0)


# --- scale -----------------------------------------------------------------------

def test_native_scale_is_the_densest_panel():
    assert native_scale(_panels()) == pytest.approx(108.0 / 25.4, abs=0.001)


def test_fit_scale_makes_the_image_exactly_cover_the_estate():
    panels = _panels()
    est = estate(panels)
    S = fit_scale(6000, 2000, est)
    assert 6000 / S == pytest.approx(est.w_mm) or 2000 / S == pytest.approx(est.h_mm)
    assert 6000 / S >= est.w_mm - 1e-6
    assert 2000 / S >= est.h_mm - 1e-6


def test_unknown_policy_is_rejected():
    with pytest.raises(ValueError, match="unknown policy"):
        choose_scale(6000, 2000, _panels(), policy="whatever")


# --- plan_layout -----------------------------------------------------------------

def test_crops_are_seam_continuous_in_image_pixels():
    """The left crop must end exactly where the right one begins."""
    panels = _panels(y_offsets_mm=[0.0, 67.18])
    plan = plan_layout(panels, 6000, 2000)
    left, right = plan.boxes[ED.index], plan.boxes[SC.index]
    assert left.right == pytest.approx(right.x)


def test_a_gap_opens_a_matching_hole_in_the_image():
    """Bezel compensation is not special-cased — it falls out of the mm geometry."""
    gap = 18.0
    panels = _panels(gaps_mm=[gap])
    plan = plan_layout(panels, 6000, 2000)
    skipped_px = plan.boxes[SC.index].x - plan.boxes[ED.index].right
    assert skipped_px == pytest.approx(gap * plan.scale)


def test_vertical_offset_reaches_the_crops_undiminished():
    """A wrong y_mm shows up as exactly that many mm of step — no attenuation."""
    plan_flush = plan_layout(_panels(), 6000, 2000)
    plan_offset = plan_layout(_panels(y_offsets_mm=[0.0, 40.0]), 6000, 2000, scale=plan_flush.scale)
    delta_px = (plan_offset.boxes[SC.index].y - plan_offset.boxes[ED.index].y)
    assert delta_px == pytest.approx(40.0 * plan_flush.scale)


def test_every_crop_carries_the_same_physical_scale():
    """Each panel's crop must be its own physical size at the shared density."""
    panels = _panels(y_offsets_mm=[0.0, 67.18])
    plan = plan_layout(panels, 6000, 2000)
    for p in panels:
        box = plan.boxes[p.index]
        assert box.w / plan.scale == pytest.approx(p.width_mm)
        assert box.h / plan.scale == pytest.approx(p.height_mm)


def test_native_policy_gives_the_densest_panel_an_exact_one_to_one_crop():
    panels = _panels()
    plan = plan_layout(panels, 6000, 2000, policy="native")
    box = plan.boxes[ED.index]
    assert (box.w, box.h) == pytest.approx((ED.native_w, ED.native_h))
    assert plan.upscaled == []


def test_fit_policy_does_not_upscale_a_large_image():
    plan = plan_layout(_panels(), 6000, 2000, policy="fit")
    assert plan.upscaled == []
    assert plan.ok


def test_a_small_image_is_reported_as_upscaled():
    plan = plan_layout(_panels(), 900, 300, policy="fit")
    assert plan.upscaled
    assert not plan.ok


def test_offset_moves_every_crop_together():
    """A drag is a global slide; it can never disturb continuity."""
    panels = _panels(y_offsets_mm=[0.0, 67.18])
    base = plan_layout(panels, 6000, 2000)
    moved = plan_layout(panels, 6000, 2000, scale=base.scale, offset_mm=(-30.0, 12.0))
    for p in panels:
        assert moved.boxes[p.index].x - base.boxes[p.index].x == pytest.approx(30.0 * base.scale)
        assert moved.boxes[p.index].y - base.boxes[p.index].y == pytest.approx(-12.0 * base.scale)
    assert moved.boxes[ED.index].right == pytest.approx(moved.boxes[SC.index].x)


def test_plan_needs_a_panel():
    with pytest.raises(ValueError):
        plan_layout([], 100, 100)


# --- clamp_offset ----------------------------------------------------------------

def test_clamp_allows_a_drag_up_to_the_slack():
    panels = _panels()
    S = native_scale(panels)     # image is wider than the estate at this density
    dx, _ = clamp_offset(panels, 6000, 2000, S, (10_000.0, 0.0))
    est = estate(panels)
    assert dx == pytest.approx((6000 / S - est.w_mm) / 2.0)


def test_clamp_pins_to_centre_when_there_is_no_slack():
    panels = _panels()
    S = fit_scale(6000, 2000, estate(panels))   # exactly covers on the limiting axis
    dx, _ = clamp_offset(panels, 6000, 2000, S, (500.0, 0.0))
    assert dx == pytest.approx(0.0)


def test_clamped_drag_keeps_every_crop_inside_the_image():
    panels = _panels(y_offsets_mm=[0.0, 67.18])
    S = native_scale(panels)
    offset = clamp_offset(panels, 6000, 2000, S, (9_999.0, 9_999.0))
    plan = plan_layout(panels, 6000, 2000, scale=S, offset_mm=offset)
    assert plan.out_of_bounds == []


# --- Box -------------------------------------------------------------------------

def test_box_as_crop_rounds_to_integers():
    assert Box(10.4, 20.6, 30.4, 40.6).as_crop() == (10, 21, 41, 61)


def test_panel_index_survives_into_the_plan():
    """Boxes are keyed by display index, which is what the exporter looks up."""
    panels = [Panel(7, "Solo", 1920, 1080, 96.0, 0.0, 0.0)]
    plan = plan_layout(panels, 3000, 2000)
    assert set(plan.boxes) == {7}
