import os

from disk_analyzer.scanner import scan
from disk_analyzer.browser import Browser, _delete_entries, _delete_entry


def _make_tree(tmp_path):
    photos = tmp_path / "Photos"
    photos.mkdir()
    (photos / "keep.jpg").write_bytes(b"k" * 100)
    (photos / "junk1.jpg").write_bytes(b"j" * 200)
    (photos / "junk2.jpg").write_bytes(b"j" * 300)
    (photos / "Subalbum").mkdir()
    (photos / "Subalbum" / "inner.jpg").write_bytes(b"i" * 50)
    return tmp_path


def test_marks_are_scoped_to_current_directory(tmp_path):
    _make_tree(tmp_path)
    root, _ = scan(str(tmp_path))
    b = Browser(root)
    photos = next(c for c in b.current_children if c.name == "Photos")
    b.stack.append(photos)
    b.selected.append(0)

    b.toggle_mark("junk1.jpg")
    b.toggle_mark("junk2.jpg")
    assert b.marked == {"junk1.jpg", "junk2.jpg"}

    # Leaving the directory clears marks (scoped to current listing).
    b.back()
    assert b.marked == set()


def test_toggle_mark_all(tmp_path):
    _make_tree(tmp_path)
    root, _ = scan(str(tmp_path))
    b = Browser(root)
    photos = next(c for c in b.current_children if c.name == "Photos")
    b.stack.append(photos)
    b.selected.append(0)

    all_names = {c.name for c in b.current_children}
    b.toggle_mark_all()
    assert b.marked == all_names
    b.toggle_mark_all()  # toggling again clears since all were marked
    assert b.marked == set()


def test_marked_entries_returns_only_marked(tmp_path):
    _make_tree(tmp_path)
    root, _ = scan(str(tmp_path))
    b = Browser(root)
    photos = next(c for c in b.current_children if c.name == "Photos")
    b.stack.append(photos)
    b.selected.append(0)

    b.toggle_mark("junk1.jpg")
    b.toggle_mark("junk2.jpg")
    marked = b.marked_entries()
    assert {e.name for e in marked} == {"junk1.jpg", "junk2.jpg"}


def test_batch_delete_marked_entries_leaves_others_intact(tmp_path):
    _make_tree(tmp_path)
    root, _ = scan(str(tmp_path))
    b = Browser(root)
    photos_entry = next(c for c in b.current_children if c.name == "Photos")
    b.stack.append(photos_entry)
    b.selected.append(0)

    b.toggle_mark("junk1.jpg")
    b.toggle_mark("junk2.jpg")
    marked = b.marked_entries()
    assert len(marked) == 2

    failures = _delete_entries(b, marked, permanent=True)
    assert failures == []

    photos_dir = tmp_path / "Photos"
    assert not (photos_dir / "junk1.jpg").exists()
    assert not (photos_dir / "junk2.jpg").exists()
    assert (photos_dir / "keep.jpg").exists()
    assert (photos_dir / "Subalbum" / "inner.jpg").exists()

    # Aggregates updated correctly: only keep.jpg (100) + inner.jpg (50) remain.
    assert photos_entry.size == 150
    assert root.size == 150
    remaining_names = {c.name for c in photos_entry.children}
    assert remaining_names == {"keep.jpg", "Subalbum"}


def test_delete_updates_all_ancestor_aggregates_not_just_parent(tmp_path):
    """Regression test: deleting an item nested 2+ levels deep must update
    every ancestor's aggregate size up to the root, not just the immediate
    parent directory."""
    _make_tree(tmp_path)
    root, _ = scan(str(tmp_path))
    b = Browser(root)
    photos_entry = next(c for c in b.current_children if c.name == "Photos")
    b.stack.append(photos_entry)
    b.selected.append(0)
    subalbum_entry = next(c for c in b.current_children if c.name == "Subalbum")
    b.stack.append(subalbum_entry)
    b.selected.append(0)

    inner = next(c for c in b.current_children if c.name == "inner.jpg")
    err = _delete_entry(b, inner, permanent=True)
    assert err is None

    assert subalbum_entry.size == 0
    assert photos_entry.size == 600  # 100 + 200 + 300, minus the 50-byte inner.jpg
    assert root.size == 600


def test_batch_delete_partial_failure_reports_name(tmp_path, monkeypatch):
    _make_tree(tmp_path)
    root, _ = scan(str(tmp_path))
    b = Browser(root)
    photos_entry = next(c for c in b.current_children if c.name == "Photos")
    b.stack.append(photos_entry)
    b.selected.append(0)

    b.toggle_mark("junk1.jpg")
    b.toggle_mark("junk2.jpg")
    marked = b.marked_entries()

    from disk_analyzer import trash

    real_delete = trash.permanently_delete
    junk1_path = str(tmp_path / "Photos" / "junk1.jpg")

    def flaky_delete(path):
        if path == junk1_path:
            raise OSError("simulated failure")
        return real_delete(path)

    monkeypatch.setattr(trash, "permanently_delete", flaky_delete)

    failures = _delete_entries(b, marked, permanent=True)
    assert len(failures) == 1
    assert failures[0][0] == "junk1.jpg"
    # The one that succeeded should still be gone; the failed one remains.
    assert (tmp_path / "Photos" / "junk1.jpg").exists()
    assert not (tmp_path / "Photos" / "junk2.jpg").exists()
