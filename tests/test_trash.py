import os
import subprocess

import pytest

from disk_analyzer import trash


def test_move_to_trash_manual_fallback(tmp_path, monkeypatch):
    """Force the osascript path to fail so we exercise the manual fallback,
    then verify the file lands in a Trash dir and is gone from the source."""
    src_dir = tmp_path / "home"
    src_dir.mkdir()
    target = src_dir / "victim.txt"
    target.write_text("bye")

    fake_trash = tmp_path / "FakeTrash"

    monkeypatch.setattr(trash, "_volume_trash_dir", lambda path: str(fake_trash))
    monkeypatch.setattr(
        trash,
        "_osascript_move_to_trash",
        lambda path: (_ for _ in ()).throw(trash.TrashError("no Finder in tests")),
    )

    trash.move_to_trash(str(target))

    assert not target.exists()
    assert (fake_trash / "victim.txt").exists()
    assert (fake_trash / "victim.txt").read_text() == "bye"


def test_move_to_trash_name_collision_manual(tmp_path, monkeypatch):
    src = tmp_path / "dupe.txt"
    src.write_text("first")
    fake_trash = tmp_path / "Trash"
    fake_trash.mkdir()
    (fake_trash / "dupe.txt").write_text("already here")

    monkeypatch.setattr(trash, "_volume_trash_dir", lambda path: str(fake_trash))
    monkeypatch.setattr(
        trash,
        "_osascript_move_to_trash",
        lambda path: (_ for _ in ()).throw(trash.TrashError("skip finder")),
    )

    trash.move_to_trash(str(src))

    assert not src.exists()
    assert (fake_trash / "dupe.txt").read_text() == "already here"
    assert (fake_trash / "dupe 2.txt").read_text() == "first"


def test_move_to_trash_missing_path_raises(tmp_path):
    missing = tmp_path / "nope.txt"
    with pytest.raises(trash.TrashError):
        trash.move_to_trash(str(missing))


def test_permanently_delete_file(tmp_path):
    f = tmp_path / "gone.txt"
    f.write_text("x")
    trash.permanently_delete(str(f))
    assert not f.exists()


def test_permanently_delete_directory(tmp_path):
    d = tmp_path / "gonedir"
    d.mkdir()
    (d / "inner.txt").write_text("x")
    trash.permanently_delete(str(d))
    assert not d.exists()


def test_unique_destination_increments():
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        open(os.path.join(td, "a.txt"), "w").close()
        open(os.path.join(td, "a 2.txt"), "w").close()
        dest = trash._unique_destination(td, "a.txt")
        assert dest == os.path.join(td, "a 3.txt")


def test_move_to_trash_uses_finder_when_available(tmp_path, monkeypatch):
    target = tmp_path / "via_finder.txt"
    target.write_text("hi")

    called = {}

    def fake_osascript(path):
        called["path"] = path
        # Simulate Finder actually removing the file.
        os.remove(path)

    monkeypatch.setattr(trash, "_osascript_move_to_trash", fake_osascript)

    trash.move_to_trash(str(target))

    assert called["path"] == str(target)
    assert not target.exists()
