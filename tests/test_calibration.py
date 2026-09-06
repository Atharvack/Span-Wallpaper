"""Tests for the calibration maths, the config store, and the pattern geometry."""

import json

import pytest

from span.algorithm.wall import Estate
from span.calibration import pattern
from span.calibration.solve import line_depth_mm, normalize, offsets_from_rows
from span.calibration.store import WallConfig, config_path, load, save

ED_K = 108.0 / 25.4     # 4.252 px/mm
SC_K = 92.0 / 25.4      # 3.622 px/mm


# --- solve -----------------------------------------------------------------------

def test_line_depth_converts_rows_to_millimetres():
    assert line_depth_mm(1063, ED_K) == pytest.approx(250.0, abs=0.1)


def test_line_depth_rejects_a_nonsense_density():
    with pytest.raises(ValueError):
        line_depth_mm(100, 0)


def test_offsets_are_zero_when_the_lines_are_already_level():
    """Same physical depth on both panels means the panels are flush."""
    rows = [round(200 * ED_K), round(200 * SC_K)]
    offsets = offsets_from_rows(rows, [ED_K, SC_K])
    assert offsets[0] == pytest.approx(0.0)
    assert offsets[1] == pytest.approx(0.0, abs=0.2)


def test_a_higher_line_on_the_second_panel_means_it_sits_lower():
    """Reaching the same wall height nearer that panel's top edge = the panel is lower."""
    offsets = offsets_from_rows([720, 370], [ED_K, SC_K])
    assert offsets[1] == pytest.approx(720 / ED_K - 370 / SC_K, abs=1e-6)
    assert offsets[1] > 0


def test_the_measured_reference_setup_reproduces():
    """The real reading taken on the reference desk: rows 720 and 370 -> 67.18 mm."""
    offsets = offsets_from_rows([720, 370], [ED_K, SC_K])
    assert offsets[1] == pytest.approx(67.18, abs=0.05)


def test_datum_choice_only_shifts_the_whole_set():
    a = offsets_from_rows([720, 370], [ED_K, SC_K], datum=0)
    b = offsets_from_rows([720, 370], [ED_K, SC_K], datum=1)
    assert (a[1] - a[0]) == pytest.approx(b[1] - b[0])


def test_mismatched_input_lengths_are_rejected():
    with pytest.raises(ValueError):
        offsets_from_rows([100, 200], [ED_K])


def test_bad_datum_is_rejected():
    with pytest.raises(IndexError):
        offsets_from_rows([100, 200], [ED_K, SC_K], datum=5)


def test_offsets_from_no_displays_is_empty():
    assert offsets_from_rows([], []) == []


def test_normalize_rezeroes_on_the_datum():
    assert normalize([12.0, 79.18]) == [0.0, 67.18]


# --- store -----------------------------------------------------------------------

@pytest.fixture
def span_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SPAN_HOME", str(tmp_path))
    return tmp_path


def test_missing_config_returns_an_uncalibrated_default(span_home):
    cfg = load("whatever", 2)
    assert cfg.y_offsets_mm == [0.0, 0.0]
    assert cfg.gaps_mm == [0.0]
    assert not cfg.is_measured


def test_saved_config_round_trips(span_home):
    save("desk", WallConfig(y_offsets_mm=[0.0, 67.18], gaps_mm=[18.0]))
    cfg = load("desk", 2)
    assert cfg.y_offsets_mm == [0.0, 67.18]
    assert cfg.gaps_mm == [18.0]
    assert cfg.is_measured


def test_saving_one_setup_leaves_the_others_alone(span_home):
    save("desk-a", WallConfig(y_offsets_mm=[0.0, 10.0], gaps_mm=[1.0]))
    save("desk-b", WallConfig(y_offsets_mm=[0.0, 20.0], gaps_mm=[2.0]))
    assert load("desk-a", 2).y_offsets_mm == [0.0, 10.0]
    assert load("desk-b", 2).y_offsets_mm == [0.0, 20.0]


def test_a_stale_entry_is_resized_to_the_current_display_count(span_home):
    """Plugging in a third monitor must not crash on a two-monitor config."""
    save("desk", WallConfig(y_offsets_mm=[0.0, 67.18], gaps_mm=[18.0]))
    cfg = load("desk", 3)
    assert cfg.y_offsets_mm == [0.0, 67.18, 0.0]
    assert cfg.gaps_mm == [18.0, 0.0]


def test_a_corrupt_config_falls_back_instead_of_raising(span_home):
    config_path().parent.mkdir(parents=True, exist_ok=True)
    config_path().write_text("{not json", encoding="utf-8")
    assert load("desk", 2).y_offsets_mm == [0.0, 0.0]


def test_config_is_written_as_readable_json(span_home):
    path = save("desk", WallConfig(y_offsets_mm=[0.0, 67.18], gaps_mm=[18.0], note="hi"))
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["desk"]["note"] == "hi"


def test_all_zero_config_is_not_considered_measured(span_home):
    save("desk", WallConfig(y_offsets_mm=[0.0, 0.0], gaps_mm=[0.0]))
    assert not load("desk", 2).is_measured


# --- pattern ---------------------------------------------------------------------

EST = Estate(x_mm=0.0, y_mm=0.0, w_mm=1132.2, h_mm=365.4)


def test_pattern_places_circles_on_every_seam():
    pat = pattern.build(EST, [602.1], modes=("circles",))
    assert pat.circles
    assert all(c.cx_mm == pytest.approx(602.1) for c in pat.circles)


def test_pattern_rules_span_the_full_estate_width():
    pat = pattern.build(EST, [602.1], modes=("rules",))
    rules = [ln for ln in pat.lines if ln.role != pattern.SEAM]
    assert rules
    assert all(ln.x1_mm == EST.x_mm and ln.x2_mm == pytest.approx(EST.right_mm) for ln in rules)


def test_pattern_labels_appear_beside_the_seam():
    pat = pattern.build(EST, [602.1], modes=("rules",))
    assert any(abs(lb.x_mm - 602.1) < 40 for lb in pat.labels)


def test_pattern_modes_select_element_families():
    assert pattern.build(EST, [602.1], modes=("columns",)).rects
    assert not pattern.build(EST, [602.1], modes=("columns",)).circles
    assert not pattern.build(EST, [602.1], modes=("circles",)).rects


def test_seam_marker_is_always_drawn():
    pat = pattern.build(EST, [602.1], modes=())
    assert [ln for ln in pat.lines if ln.role == pattern.SEAM]


def test_pattern_with_no_seam_still_builds():
    pat = pattern.build(EST, [], modes=("rules", "circles"))
    assert pat.circles == []
    assert pat.lines
