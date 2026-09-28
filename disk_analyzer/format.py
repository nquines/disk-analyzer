"""Human-friendly formatting helpers."""
from __future__ import annotations

_UNITS = ["B", "KB", "MB", "GB", "TB", "PB"]


def human_size(num_bytes: int, precision: int = 1) -> str:
    """Format a byte count as a human-readable string (e.g. '1.2 GB')."""
    size = float(num_bytes)
    unit = _UNITS[0]
    for unit in _UNITS:
        if size < 1024.0 or unit == _UNITS[-1]:
            break
        size /= 1024.0
    if unit == "B":
        return f"{int(size)} {unit}"
    return f"{size:.{precision}f} {unit}"


def bar(fraction: float, width: int = 20, fill: str = "#", empty: str = "-") -> str:
    """Render a simple ASCII proportion bar, fraction in [0, 1]."""
    fraction = max(0.0, min(1.0, fraction))
    filled = int(round(fraction * width))
    return fill * filled + empty * (width - filled)
