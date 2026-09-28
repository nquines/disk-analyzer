import json

from disk_analyzer.cli import build_parser, main
from disk_analyzer.scanner import scan
from disk_analyzer.export import entry_to_dict


def _make_tree(tmp_path):
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "big.bin").write_bytes(b"x" * 2000)
    (tmp_path / "root.txt").write_text("hi")
    return tmp_path


def test_parser_defaults():
    parser = build_parser()
    args = parser.parse_args([])
    assert args.path == "~"
    assert args.cross_mounts is False
    assert args.use_disk_blocks is False


def test_main_prints_summary(tmp_path, capsys):
    _make_tree(tmp_path)
    rc = main([str(tmp_path), "--quiet"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "a" in out
    assert "root.txt" in out


def test_main_json_export(tmp_path, capsys):
    _make_tree(tmp_path)
    rc = main([str(tmp_path), "--quiet", "--json", "-"])
    assert rc == 0
    out = capsys.readouterr().out
    data = json.loads(out)
    assert data["is_dir"] is True
    assert "children" in data


def test_entry_to_dict_matches_scan(tmp_path):
    _make_tree(tmp_path)
    root, _ = scan(str(tmp_path))
    d = entry_to_dict(root)
    assert d["size"] == root.size
    assert d["file_count"] == root.file_count
