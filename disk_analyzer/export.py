"""Export helpers for scanned trees (JSON, CSV)."""
from __future__ import annotations

import csv
import json
import sys
from dataclasses import asdict
from typing import IO

from .scanner import Entry


def entry_to_dict(entry: Entry, max_children: int | None = None) -> dict:
    d = {
        "name": entry.name,
        "is_dir": entry.is_dir,
        "size": entry.size,
        "file_count": entry.file_count,
        "dir_count": entry.dir_count,
    }
    if entry.error:
        d["error"] = entry.error
    if entry.children:
        children = entry.sorted_children()
        if max_children is not None:
            children = children[:max_children]
        d["children"] = [entry_to_dict(c, max_children) for c in children]
    return d


def write_json(entry: Entry, fh: IO[str], *, max_children: int | None = None, indent: int | None = 2) -> None:
    json.dump(entry_to_dict(entry, max_children=max_children), fh, indent=indent)
    fh.write("\n")


def write_csv(entry: Entry, fh: IO[str]) -> None:
    writer = csv.writer(fh)
    writer.writerow(["path", "type", "size_bytes"])

    def walk(node: Entry, path: str) -> None:
        for child in node.sorted_children():
            child_path = f"{path}/{child.name}" if path else child.name
            writer.writerow([child_path, "dir" if child.is_dir else "file", child.size])
            if child.is_dir:
                walk(child, child_path)

    walk(entry, entry.name)
