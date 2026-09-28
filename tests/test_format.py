from disk_analyzer.format import bar, human_size


def test_human_size_bytes():
    assert human_size(0) == "0 B"
    assert human_size(500) == "500 B"


def test_human_size_kb_mb_gb():
    assert human_size(1024) == "1.0 KB"
    assert human_size(1536) == "1.5 KB"
    assert human_size(1024 * 1024) == "1.0 MB"
    assert human_size(1024 ** 3) == "1.0 GB"


def test_human_size_precision():
    assert human_size(1024 * 1500, precision=2) == "1.46 MB"


def test_bar_bounds():
    assert bar(0.0, width=10) == "-" * 10
    assert bar(1.0, width=10) == "#" * 10
    assert bar(2.0, width=10) == "#" * 10  # clamps above 1
    assert bar(-1.0, width=10) == "-" * 10  # clamps below 0


def test_bar_partial():
    result = bar(0.5, width=10)
    assert result.count("#") == 5
    assert result.count("-") == 5
