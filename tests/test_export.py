"""Tests for crop / resample / save, plus an offscreen smoke test of the wall app."""

import pytest
from PIL import Image
from PySide6.QtCore import Qt

from span.algorithm.displays import Display
from span.algorithm.wall import Box, panels_from_displays, plan_layout
from span.image_processing.export import export_all, export_crop, safe_name, unique_path

ED = Display(0, "ED270U", 0, 0, 2560, 1440, 1.0, 3, 602.0740650318287, 329.5135085647171)
SC = Display(1, "Sceptre", 2560, 60, 1920, 1080, 1.0, 2, 530.0869485606318, 301.45054492321646)


def _solid_color(img: Image.Image):
    """The single RGB colour of a solid image, or None if it is not solid."""
    colors = img.convert("RGB").getcolors(maxcolors=4)
    return colors[0][1] if colors and len(colors) == 1 else None


def test_safe_name():
    assert safe_name("Studio Display") == "Studio-Display"
    assert safe_name("DELL U2720Q") == "DELL-U2720Q"
    assert safe_name("///") == "display"


def test_each_panel_gets_the_region_behind_its_own_glass(tmp_path):
    """Left half red, right half blue, seam exactly on the colour boundary."""
    panels = panels_from_displays([ED, SC])
    plan = plan_layout(panels, 6000, 2000, policy="fit")
    seam_px = round(plan.boxes[ED.index].right)

    img = Image.new("RGB", (6000, 2000), (255, 0, 0))
    img.paste((0, 0, 255), (seam_px, 0, 6000, 2000))

    results = export_all(img, panels, plan.boxes, tmp_path, "wall")
    assert len(results) == 2
    assert _solid_color(Image.open(results[0].path)) == (255, 0, 0)
    assert _solid_color(Image.open(results[1].path)) == (0, 0, 255)


def test_output_is_always_the_panel_native_resolution(tmp_path):
    panels = panels_from_displays([ED, SC])
    plan = plan_layout(panels, 6000, 2000, policy="fit")
    img = Image.new("RGB", (6000, 2000), (40, 40, 40))
    for r in export_all(img, panels, plan.boxes, tmp_path, "wall"):
        assert Image.open(r.path).size == (r.panel.px_w, r.panel.px_h)


def test_a_native_sized_crop_is_saved_without_resampling(tmp_path):
    """The 1:1 fast path is what makes 'native' genuinely lossless."""
    (panel,) = panels_from_displays([ED])
    img = Image.new("RGB", (4000, 2000), (10, 200, 10))
    box = Box(0, 0, panel.px_w, panel.px_h)
    result = export_crop(img, panel, box, tmp_path, "one.png")
    assert not result.resampled
    assert not result.upscaled


def test_a_smaller_crop_is_reported_as_upscaled(tmp_path):
    (panel,) = panels_from_displays([ED])
    img = Image.new("RGB", (4000, 2000), (10, 10, 200))
    result = export_crop(img, panel, Box(0, 0, 800, 450), tmp_path, "small.png")
    assert result.upscaled
    assert result.resampled
    assert Image.open(result.path).size == (panel.px_w, panel.px_h)


def test_an_out_of_bounds_box_is_clamped_rather_than_padded_black(tmp_path):
    """Pillow would happily crop past the edge and fill with black."""
    (panel,) = panels_from_displays([ED])
    img = Image.new("RGB", (3000, 1600), (200, 120, 0))
    result = export_crop(img, panel, Box(2600, 1400, 2560, 1440), tmp_path, "edge.png")
    assert _solid_color(Image.open(result.path)) == (200, 120, 0)


def test_export_never_overwrites(tmp_path):
    (panel,) = panels_from_displays([ED])
    img = Image.new("RGB", (3000, 1600), (0, 0, 0))
    first = export_crop(img, panel, Box(0, 0, 1000, 562), tmp_path, "x.png")
    second = export_crop(img, panel, Box(0, 0, 1000, 562), tmp_path, "x.png")
    assert first.path.name == "x.png"
    assert second.path.name == "x (1).png"


def test_unique_path_counts_up(tmp_path):
    (tmp_path / "a.png").write_bytes(b"")
    (tmp_path / "a (1).png").write_bytes(b"")
    assert unique_path(tmp_path / "a.png").name == "a (2).png"


def test_identical_panels_get_an_index_suffix(tmp_path):
    twin_a = Display(0, "Twin", 0, 0, 1920, 1080, 1.0, 1, 530.0869485606318, 298.0)
    twin_b = Display(1, "Twin", 1920, 0, 1920, 1080, 1.0, 2, 530.0869485606318, 298.0)
    panels = panels_from_displays([twin_a, twin_b])
    plan = plan_layout(panels, 6000, 2000, policy="fit")
    img = Image.new("RGB", (6000, 2000), (5, 5, 5))
    names = [r.path.name for r in export_all(img, panels, plan.boxes, tmp_path, "w")]
    assert names == ["w_Twin_1920x1080_0.png", "w_Twin_1920x1080_1.png"]


def test_distinct_panels_get_clean_names(tmp_path):
    panels = panels_from_displays([ED, SC])
    plan = plan_layout(panels, 6000, 2000, policy="fit")
    img = Image.new("RGB", (6000, 2000), (5, 5, 5))
    names = [r.path.name for r in export_all(img, panels, plan.boxes, tmp_path, "w")]
    assert names == ["w_ED270U_2560x1440.png", "w_Sceptre_1920x1080.png"]


# --- offscreen GUI smoke test ----------------------------------------------------

@pytest.fixture
def qapp():
    from PySide6.QtWidgets import QApplication
    yield QApplication.instance() or QApplication([])


def test_wall_app_builds_one_window_per_display(qapp, tmp_path):
    from span.calibration import WallConfig
    from span.gui import AppState, WallApp, WallWindow

    state = AppState(
        displays=[ED, SC],
        config=WallConfig(y_offsets_mm=[0.0, 67.18], gaps_mm=[0.0]),
        image=Image.new("RGB", (6000, 2000), (30, 30, 30)),
        image_stem="t", out_dir=tmp_path,
    )
    app = WallApp(state)
    app.windows = [WallWindow(state, i, 1.0, app) for i in range(len(state.panels))]
    assert len(app.windows) == 2
    assert app.windows[1].panel.y_mm == pytest.approx(67.18)


def test_wall_app_plan_matches_what_the_window_would_paint(qapp, tmp_path):
    from span.calibration import WallConfig
    from span.gui import AppState

    state = AppState(
        displays=[ED, SC],
        config=WallConfig(y_offsets_mm=[0.0, 67.18], gaps_mm=[0.0]),
        image=Image.new("RGB", (6000, 2000), (30, 30, 30)),
        image_stem="t", out_dir=tmp_path,
    )
    plan = state.plan()
    assert plan is not None
    # WYSIWYG: the box the window draws from is the box the exporter cuts.
    assert plan.boxes[ED.index].right == pytest.approx(plan.boxes[SC.index].x)


def test_wall_app_without_an_image_has_no_plan(qapp, tmp_path):
    from span.calibration import WallConfig
    from span.gui import AppState

    state = AppState(displays=[ED, SC], config=WallConfig(y_offsets_mm=[0.0, 0.0], gaps_mm=[0.0]),
                     image=None, image_stem="t", out_dir=tmp_path)
    assert state.plan() is None


def test_wallpaper_is_refused_on_an_uncalibrated_wall(qapp, tmp_path, monkeypatch):
    """Without measured geometry the crops step at the seam — refuse and say so."""
    from span.calibration import WallConfig
    from span.gui import MODE_CALIBRATE, MODE_PLACE, AppState, WallApp

    monkeypatch.setattr("span.gui.set_wallpapers",
                        lambda *a, **k: pytest.fail("should not reach the OS"))
    state = AppState(
        displays=[ED, SC],
        config=WallConfig(y_offsets_mm=[0.0, 0.0], gaps_mm=[0.0]),   # all zeros
        image=Image.new("RGB", (6000, 2000), (30, 30, 30)),
        image_stem="t", out_dir=tmp_path, mode=MODE_PLACE,
    )
    app = WallApp(state)
    app.apply_wallpaper()

    assert state.mode == MODE_CALIBRATE
    assert "calibrate first" in state.message


def test_wallpaper_is_refused_without_an_image(qapp, tmp_path, monkeypatch):
    from span.calibration import WallConfig
    from span.gui import AppState, WallApp

    monkeypatch.setattr("span.gui.set_wallpapers",
                        lambda *a, **k: pytest.fail("should not reach the OS"))
    state = AppState(displays=[ED, SC],
                     config=WallConfig(y_offsets_mm=[0.0, 67.18], gaps_mm=[0.0]),
                     image=None, image_stem="t", out_dir=tmp_path)
    WallApp(state).apply_wallpaper()
    assert "press o" in state.message


def test_keep_dialog_counts_down_and_reverts_on_timeout(qapp):
    """Doing nothing must undo — that is the entire point of the timer."""
    from span.gui import KeepDialog

    dialog = KeepDialog(None, seconds=2)
    assert not dialog.keep
    dialog._tick()          # 2 -> 1
    assert not dialog.keep
    dialog._tick()          # 1 -> 0, rejects
    assert not dialog.keep


def test_picker_starts_where_you_last_opened_something(qapp, tmp_path, monkeypatch):
    """Not the Pictures folder — wallpapers live in Downloads and on the Desktop too."""
    from span.calibration import WallConfig
    from span.gui import AppState, WallApp

    last = tmp_path / "Downloads"
    last.mkdir()
    monkeypatch.setattr("span.gui.paths.last_image_dir", lambda: last)
    state = AppState(displays=[ED], config=WallConfig(y_offsets_mm=[0.0], gaps_mm=[]),
                     image=None, image_stem="t", out_dir=tmp_path)
    assert WallApp(state)._picker_start_dir(None) == str(last)


def test_picker_falls_back_to_the_current_image_folder(qapp, tmp_path, monkeypatch):
    from pathlib import Path
    from span.calibration import WallConfig
    from span.gui import AppState, WallApp

    monkeypatch.setattr("span.gui.paths.last_image_dir", lambda: None)
    here = tmp_path / "Shoots"
    here.mkdir()
    state = AppState(displays=[ED], config=WallConfig(y_offsets_mm=[0.0], gaps_mm=[]),
                     image=None, image_stem="t", out_dir=tmp_path,
                     image_path=here / "a.jpg")
    assert WallApp(state)._picker_start_dir(None) == str(here)


def test_picker_falls_back_to_home(qapp, tmp_path, monkeypatch):
    from pathlib import Path
    from span.calibration import WallConfig
    from span.gui import AppState, WallApp

    monkeypatch.setattr("span.gui.paths.last_image_dir", lambda: None)
    state = AppState(displays=[ED], config=WallConfig(y_offsets_mm=[0.0], gaps_mm=[]),
                     image=None, image_stem="t", out_dir=tmp_path)
    assert WallApp(state)._picker_start_dir(None) == str(Path.home())


# --- welcome screen / flow -------------------------------------------------------

def _state(tmp_path, calibrated=True, image=True):
    from PIL import Image as PILImage
    from span.calibration import WallConfig
    from span.gui import AppState
    return AppState(
        displays=[ED, SC],
        config=WallConfig(y_offsets_mm=[0.0, 67.18 if calibrated else 0.0],
                          gaps_mm=[0.0]),
        image=PILImage.new("RGB", (6000, 2000), (30, 30, 30)) if image else None,
        image_stem="t", out_dir=tmp_path,
    )


def test_welcome_explains_why_calibration_comes_first(qapp, tmp_path):
    from span.gui import WallApp, WelcomeWindow

    state = _state(tmp_path, calibrated=False)
    app = WallApp(state)
    w = WelcomeWindow(state, app)
    assert "not been calibrated" in w._status.text()
    assert w._calibrate.text() == "Start calibration"
    assert not w._place.isEnabled()      # placing would produce a stepped result


def test_welcome_offers_placement_once_calibrated(qapp, tmp_path):
    from span.gui import WallApp, WelcomeWindow

    state = _state(tmp_path, calibrated=True)
    w = WelcomeWindow(state, WallApp(state))
    assert w._place.isEnabled()
    assert "calibrated" in w._status.text()


def test_welcome_lists_the_detected_panels(qapp, tmp_path):
    from span.gui import WallApp, WelcomeWindow

    state = _state(tmp_path)
    text = WelcomeWindow(state, WallApp(state))._displays.text()
    assert "ED270U" in text and "Sceptre" in text
    assert "108.0 ppi" in text


def test_place_is_refused_without_an_image(qapp, tmp_path):
    from span.gui import MODE_PLACE, WallApp

    state = _state(tmp_path, image=False)
    app = WallApp(state)
    app.open_wall(MODE_PLACE)
    assert app.windows == []             # nothing opened
    assert "no image" in state.message


def test_escape_returns_to_welcome_instead_of_quitting(qapp, tmp_path, monkeypatch):
    from span.gui import MODE_CALIBRATE, WallApp, WelcomeWindow

    monkeypatch.setattr("span.gui.QApplication.quit",
                        staticmethod(lambda: pytest.fail("should not quit on escape")))
    state = _state(tmp_path)
    app = WallApp(state)
    app.welcome = WelcomeWindow(state, app)
    app.open_wall(MODE_CALIBRATE)
    assert app.windows
    app.close_wall()
    assert app.windows == []
    assert app.welcome.isVisible()


# --- action buttons on the placement view ----------------------------------------

def _wall(tmp_path, mode):
    from span.gui import WallApp, WallWindow
    state = _state(tmp_path)
    state.mode = mode
    app = WallApp(state)
    win = WallWindow(state, 0, 1.0, app)
    win.resize(2560, 1440)
    win._layout_buttons()
    return state, app, win


def test_three_action_buttons_are_shown_when_placing(qapp, tmp_path):
    from span.gui import MODE_PLACE
    _, _, win = _wall(tmp_path, MODE_PLACE)
    labels = [b.text() for b in win._buttons]
    assert labels == ["Set wallpaper", "Browse images", "Exit"]
    assert all(not b.isHidden() for b in win._buttons)


def test_buttons_are_hidden_while_calibrating(qapp, tmp_path):
    """Calibration is a millimetre-nudging keyboard job; the row would just cover the
    pattern being read."""
    from span.gui import MODE_CALIBRATE
    _, _, win = _wall(tmp_path, MODE_CALIBRATE)
    assert all(b.isHidden() for b in win._buttons)


def test_buttons_sit_along_the_bottom_and_inside_the_window(qapp, tmp_path):
    from span.gui import MODE_PLACE
    _, _, win = _wall(tmp_path, MODE_PLACE)
    for b in win._buttons:
        g = b.geometry()
        assert g.left() >= 0 and g.right() <= win.width()
        assert g.bottom() < win.height()
        assert g.top() > win.height() // 2      # bottom half, out of the picture's way


def test_buttons_do_not_steal_the_arrow_keys(qapp, tmp_path):
    """Focus would send ↑↓←→ to the button row instead of moving the image."""
    from span.gui import MODE_PLACE
    _, _, win = _wall(tmp_path, MODE_PLACE)
    assert all(b.focusPolicy() == Qt.FocusPolicy.NoFocus for b in win._buttons)


def test_set_wallpaper_button_goes_through_the_calibration_gate(qapp, tmp_path,
                                                                monkeypatch):
    from span.calibration import WallConfig
    from span.gui import MODE_CALIBRATE, MODE_PLACE

    monkeypatch.setattr("span.gui.set_wallpapers",
                        lambda *a, **k: pytest.fail("should not reach the OS"))
    state, app, win = _wall(tmp_path, MODE_PLACE)
    state.config = WallConfig(y_offsets_mm=[0.0, 0.0], gaps_mm=[0.0])   # uncalibrated
    win._set_btn.click()
    assert state.mode == MODE_CALIBRATE
    assert "calibrate first" in state.message


def test_confirming_a_wallpaper_hides_our_own_windows_first(qapp, tmp_path, monkeypatch):
    """Approving a preview is not approving the result — the wall has to come down."""
    from span.gui import MODE_PLACE, WallApp, WallWindow

    calls = []
    monkeypatch.setattr("span.gui.hide_other_applications",
                        lambda: calls.append("hide_others") or True)
    monkeypatch.setattr("span.gui.unhide_all_applications",
                        lambda: calls.append("unhide") or True)
    monkeypatch.setattr("span.gui.restore", lambda before: [])

    class _Dismissed:
        keep = False

        def __init__(self, *a, **k):
            pass

        def setWindowFlag(self, *a, **k):
            pass

        def exec(self):
            calls.append("dialog")
            return 0

    monkeypatch.setattr("span.gui.KeepDialog", _Dismissed)

    state = _state(tmp_path)
    state.mode = MODE_PLACE
    app = WallApp(state)
    app.windows = [WallWindow(state, 0, 1.0, app)]
    app.windows[0].show()

    app._confirm_wallpaper({}, [], [])

    # Others hidden before the question, restored after it.
    assert calls.index("hide_others") < calls.index("dialog") < calls.index("unhide")
    assert app.windows[0].isVisible()      # reverted, so the wall comes back
