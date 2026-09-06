"""Tests for the runtime path layout and tmp pruning."""

import os
import pathlib

import pytest

from span import paths


@pytest.fixture
def span_home(tmp_path, monkeypatch):
    monkeypatch.setenv("SPAN_HOME", str(tmp_path))
    monkeypatch.delenv("SPAN_DIAG_LOG", raising=False)
    return tmp_path


def test_everything_hangs_off_one_base_directory(span_home):
    assert paths.home() == span_home
    assert paths.tmp_dir() == span_home / "tmp"
    assert paths.config_file() == span_home / "tmp" / "wall.json"
    assert paths.log_file() == span_home / "logs" / "span.log"


def test_home_expands_a_tilde(monkeypatch):
    monkeypatch.setenv("SPAN_HOME", "~/somewhere")
    assert "~" not in str(paths.home())


def test_log_path_can_be_overridden_outright(span_home, monkeypatch, tmp_path):
    monkeypatch.setenv("SPAN_DIAG_LOG", str(tmp_path / "elsewhere.log"))
    assert paths.log_file() == tmp_path / "elsewhere.log"


def test_ensure_dirs_creates_the_layout(span_home):
    paths.ensure_dirs()
    assert paths.tmp_dir().is_dir()
    assert paths.log_dir().is_dir()


def test_ensure_dirs_is_idempotent(span_home):
    paths.ensure_dirs()
    paths.ensure_dirs()
    assert paths.tmp_dir().is_dir()


def test_prune_keeps_the_newest_and_removes_the_rest(span_home):
    paths.ensure_dirs()
    for i in range(10):
        f = paths.tmp_dir() / f"f{i}.png"
        f.write_bytes(b"x")
        os.utime(f, (i, i))          # f9 is newest
    removed = paths.prune_tmp(keep=3)

    assert len(removed) == 7
    remaining = sorted(p.name for p in paths.tmp_dir().iterdir() if p.is_file())
    assert remaining == ["f7.png", "f8.png", "f9.png"]


def test_prune_does_nothing_when_under_the_limit(span_home):
    paths.ensure_dirs()
    (paths.tmp_dir() / "only.png").write_bytes(b"x")
    assert paths.prune_tmp(keep=5) == []
    assert (paths.tmp_dir() / "only.png").exists()


def test_prune_on_a_missing_directory_is_harmless(span_home):
    assert paths.prune_tmp() == []


def test_describe_names_every_location(span_home):
    text = paths.describe()
    for key in ("home", "calibration", "tmp", "log", "tail -f"):
        assert key in text


def test_pruning_never_touches_state_files(span_home):
    """wall.json and the wallpaper snapshot live beside the images and must survive."""
    paths.ensure_dirs()
    for name in ("wall.json", "wallpaper-before.json"):
        (paths.tmp_dir() / name).write_text("{}", encoding="utf-8")
    for i in range(5):
        f = paths.tmp_dir() / f"img{i}.png"
        f.write_bytes(b"x")
        os.utime(f, (i, i))

    removed = paths.prune_tmp(keep=1)

    assert all(p.suffix == ".png" for p in removed)
    assert (paths.tmp_dir() / "wall.json").exists()
    assert (paths.tmp_dir() / "wallpaper-before.json").exists()


def test_protected_files_survive_pruning_regardless_of_age(span_home):
    """A file currently serving as wallpaper must never be deleted — macOS only holds a
    reference to it."""
    paths.ensure_dirs()
    oldest = paths.tmp_dir() / "in-use.png"
    oldest.write_bytes(b"x")
    os.utime(oldest, (0, 0))
    for i in range(1, 6):
        f = paths.tmp_dir() / f"img{i}.png"
        f.write_bytes(b"x")
        os.utime(f, (i, i))

    paths.prune_tmp(keep=2, protect=[oldest])
    assert oldest.exists()


def test_base_is_the_checkout_when_running_from_source(monkeypatch):
    """Working in the repo, the files belong beside the code — visible and tailable."""
    monkeypatch.delenv("SPAN_HOME", raising=False)
    root = paths.project_root()
    assert root is not None and (root / "pyproject.toml").is_file()
    assert paths.home() == root
    assert paths.tmp_dir() == root / "tmp"
    assert paths.log_file() == root / "logs" / "span.log"


def test_base_falls_back_to_dot_span_when_installed(monkeypatch):
    """No checkout to write into — an installed package uses the home directory."""
    monkeypatch.delenv("SPAN_HOME", raising=False)
    monkeypatch.setattr(paths, "project_root", lambda: None)
    assert paths.home() == pathlib.Path("~/.span").expanduser()


def test_span_home_wins_over_everything(monkeypatch, tmp_path):
    monkeypatch.setenv("SPAN_HOME", str(tmp_path))
    assert paths.home() == tmp_path


def test_last_image_dir_round_trips(span_home, tmp_path):
    paths.ensure_dirs()
    pics = tmp_path / "somewhere" / "photos"
    pics.mkdir(parents=True)
    paths.remember_image_dir(pics / "shot.jpg")     # a file: its folder is remembered
    assert paths.last_image_dir() == pics


def test_last_image_dir_is_none_before_anything_is_picked(span_home):
    assert paths.last_image_dir() is None


def test_last_image_dir_forgets_a_folder_that_has_gone(span_home, tmp_path):
    paths.ensure_dirs()
    gone = tmp_path / "removable"
    gone.mkdir()
    paths.remember_image_dir(gone)
    gone.rmdir()
    assert paths.last_image_dir() is None


def test_the_three_wallpaper_folders_are_distinct(span_home):
    """current / pending / revert are separate so no operation can confuse them."""
    root = paths.tmp_dir() / "desktop_wallpaper_do_not_remove"
    assert paths.wallpaper_root() == root
    assert paths.wallpaper_dir() == root / "current"
    assert paths.pending_dir() == root / "pending"
    assert paths.revert_dir() == root / "revert"
    assert len({paths.wallpaper_dir(), paths.pending_dir(), paths.revert_dir()}) == 3


def test_ensure_dirs_creates_all_of_them(span_home):
    paths.ensure_dirs()
    for d in (paths.wallpaper_dir(), paths.pending_dir(), paths.revert_dir()):
        assert d.is_dir()


def test_pruning_tmp_never_reaches_the_wallpaper_folders(span_home):
    """These files are what macOS references; deleting one blanks a display."""
    paths.ensure_dirs()
    live = paths.wallpaper_dir() / "on-screen.png"
    live.write_bytes(b"x")
    os.utime(live, (0, 0))                       # oldest thing on disk
    for i in range(1, 6):
        f = paths.tmp_dir() / f"img{i}.png"
        f.write_bytes(b"x")
        os.utime(f, (i, i))

    paths.prune_tmp(keep=1)
    assert live.exists()


def test_clear_pending_cannot_reach_the_live_wallpaper(span_home):
    """The guarantee that makes the old bug impossible: Revert is never given the paths
    of `current` or `revert`, so no amount of wrong logic can delete them."""
    paths.ensure_dirs()
    live = paths.wallpaper_dir() / "on-screen.png"
    backup = paths.revert_dir() / "previous.png"
    rejected = paths.pending_dir() / "candidate.png"
    for f in (live, backup, rejected):
        f.write_bytes(b"x")

    removed = paths.clear_pending()

    assert removed == [rejected]
    assert live.exists() and backup.exists()


def test_promote_pending_moves_a_confirmed_set_into_current(span_home):
    paths.ensure_dirs()
    candidate = paths.pending_dir() / "new.png"
    candidate.write_bytes(b"x")

    promoted = paths.promote_pending([candidate])

    assert promoted == [paths.wallpaper_dir() / "new.png"]
    assert promoted[0].exists()
    assert list(paths.pending_dir().iterdir()) == []


def test_promote_replaces_the_set_it_supersedes(span_home):
    paths.ensure_dirs()
    superseded = paths.wallpaper_dir() / "old.png"
    superseded.write_bytes(b"x")
    candidate = paths.pending_dir() / "new.png"
    candidate.write_bytes(b"x")

    paths.promote_pending([candidate])

    assert not superseded.exists()               # nothing references it any more
    assert (paths.wallpaper_dir() / "new.png").exists()


def test_promote_copies_the_content_not_just_the_name(span_home):
    """Copy before delete: a half-finished move must not leave a referenced file nowhere."""
    paths.ensure_dirs()
    candidate = paths.pending_dir() / "new.png"
    candidate.write_bytes(b"payload")

    assert paths.promote_pending([candidate])[0].read_bytes() == b"payload"


def test_promote_skips_a_file_that_vanished(span_home):
    paths.ensure_dirs()
    assert paths.promote_pending([paths.pending_dir() / "ghost.png"]) == []
