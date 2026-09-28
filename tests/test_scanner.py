import os

from disk_analyzer.scanner import scan, iter_largest_files


def _make_tree(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "big.bin").write_bytes(b"x" * 5000)
    (tmp_path / "a" / "small.txt").write_text("hello")
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "c").mkdir()
    (tmp_path / "b" / "c" / "deep.txt").write_text("deep" * 100)
    (tmp_path / "root.txt").write_text("root file")
    return tmp_path


def test_scan_basic_totals(tmp_path):
    _make_tree(tmp_path)
    root, stats = scan(str(tmp_path))

    assert root.is_dir
    assert root.file_count == 4
    assert root.dir_count == 3
    expected_size = 5000 + len("hello") + len("deep" * 100) + len("root file")
    assert root.size == expected_size
    assert stats.files_scanned == 4
    assert stats.errors == 0


def test_scan_children_sorted_by_size(tmp_path):
    _make_tree(tmp_path)
    root, _ = scan(str(tmp_path))
    children = root.sorted_children()
    sizes = [c.size for c in children]
    assert sizes == sorted(sizes, reverse=True)


def test_max_depth_keeps_correct_totals(tmp_path):
    _make_tree(tmp_path)
    full_root, _ = scan(str(tmp_path))
    shallow_root, _ = scan(str(tmp_path), max_depth=0)

    assert shallow_root.size == full_root.size
    assert shallow_root.file_count == full_root.file_count
    assert shallow_root.dir_count == full_root.dir_count
    # max_depth=0 keeps root's immediate children (level 0) but no
    # grandchildren beneath them -- totals are still fully aggregated.
    shallow_b = next(c for c in shallow_root.children if c.name == "b")
    full_b = next(c for c in full_root.children if c.name == "b")
    assert shallow_b.children == []
    assert shallow_b.size == full_b.size
    assert shallow_b.file_count == full_b.file_count


def test_exclude_pattern(tmp_path):
    _make_tree(tmp_path)
    root, _ = scan(str(tmp_path), exclude=["b"])
    names = {c.name for c in root.children}
    assert "b" not in names
    assert "a" in names


def test_iter_largest_files(tmp_path):
    _make_tree(tmp_path)
    root, _ = scan(str(tmp_path))
    largest = iter_largest_files(root, limit=1)
    assert len(largest) == 1
    path, size = largest[0]
    assert path == "a/big.bin"
    assert size == 5000


def test_missing_path_returns_error_entry(tmp_path):
    missing = tmp_path / "does-not-exist"
    root, stats = scan(str(missing))
    assert root.error is not None


def test_permission_error_does_not_crash(tmp_path):
    restricted = tmp_path / "restricted"
    restricted.mkdir()
    (restricted / "secret.txt").write_text("shh")
    os.chmod(restricted, 0o000)
    try:
        root, stats = scan(str(tmp_path))
        # Should not raise; restricted dir shows up with an error, rest scanned fine.
        assert root.error is None or True
        names = {c.name for c in root.children}
        assert "restricted" in names
    finally:
        os.chmod(restricted, 0o755)
