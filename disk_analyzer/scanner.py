"""Core directory-scanning engine.

Design goals:
  * Standard-library only (no pip dependencies required).
  * Doesn't double-count hardlinks by default.
  * Doesn't cross filesystem/mount boundaries by default (so scanning "/"
    won't wander into other APFS volumes, network mounts, Time Machine
    backups, etc.).
  * Handles PermissionError / FileNotFoundError / OSError gracefully
    (very common on macOS for things like ~/Library/Containers or
    SIP-protected paths) instead of crashing.
"""
from __future__ import annotations

import fnmatch
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable, Optional

# Bump recursion limit: real filesystem paths are rarely more than a few
# hundred levels deep, but the default Python limit (1000) can be tight
# once you add the interpreter's own call overhead.
if sys.getrecursionlimit() < 10000:
    sys.setrecursionlimit(10000)

# Name/path patterns that are almost always noise on macOS.
# Only applied when the caller passes exclude_common=True.
COMMON_EXCLUDES = [
    ".git",
    ".svn",
    ".hg",
    "node_modules",
    ".Trash",
    ".Trashes",
    ".DS_Store",
    ".Spotlight-V100",
    ".fseventsd",
    ".DocumentRevisions-V100",
    ".TemporaryItems",
    "Library/Caches",
    "Library/Containers",
]


@dataclass
class Entry:
    """A single file or directory node in the scanned tree.

    For directories, ``size``/``file_count``/``dir_count`` are always the
    full aggregate for everything beneath it -- even if ``children`` is
    empty because ``max_depth`` collapsed that subtree.
    """

    name: str
    is_dir: bool
    size: int = 0
    file_count: int = 0
    dir_count: int = 0
    error: Optional[str] = None
    children: list["Entry"] = field(default_factory=list)

    def sorted_children(self) -> list["Entry"]:
        return sorted(self.children, key=lambda e: e.size, reverse=True)


@dataclass
class ScanStats:
    files_scanned: int = 0
    dirs_scanned: int = 0
    bytes_scanned: int = 0
    errors: int = 0
    elapsed: float = 0.0


ProgressCallback = Callable[[str, ScanStats], None]


def _matches_any(name: str, rel_path: str, patterns: Iterable[str]) -> bool:
    for pat in patterns:
        if fnmatch.fnmatch(name, pat) or fnmatch.fnmatch(rel_path, pat):
            return True
    return False


class _Scanner:
    def __init__(
        self,
        *,
        use_disk_blocks: bool,
        cross_mounts: bool,
        follow_symlinks: bool,
        dedupe_hardlinks: bool,
        patterns: list[str],
        max_depth: Optional[int],
        root_dev: int,
        progress: Optional[ProgressCallback],
        progress_interval: float,
    ) -> None:
        self.use_disk_blocks = use_disk_blocks
        self.cross_mounts = cross_mounts
        self.follow_symlinks = follow_symlinks
        self.dedupe_hardlinks = dedupe_hardlinks
        self.patterns = patterns
        self.max_depth = max_depth
        self.root_dev = root_dev
        self.progress = progress
        self.progress_interval = progress_interval
        self.stats = ScanStats()
        self.seen_inodes: set[tuple[int, int]] = set()
        self._start = time.monotonic()
        self._last_report = self._start

    def _maybe_report(self, current_path: str) -> None:
        if self.progress is None:
            return
        now = time.monotonic()
        if now - self._last_report >= self.progress_interval:
            self.stats.elapsed = now - self._start
            self.progress(current_path, self.stats)
            self._last_report = now

    def scan_dir(self, abs_path: str, rel_path: str, depth: int, keep_children: bool) -> Entry:
        entry = Entry(name=os.path.basename(abs_path) or abs_path, is_dir=True)
        self._maybe_report(abs_path)
        try:
            with os.scandir(abs_path) as it:
                entries = list(it)
        except OSError as exc:
            entry.error = str(exc)
            self.stats.errors += 1
            return entry

        total_size = 0
        file_count = 0
        dir_count = 0
        children: list[Entry] = []

        for de in entries:
            name = de.name
            child_rel = f"{rel_path}/{name}" if rel_path else name
            if self.patterns and _matches_any(name, child_rel, self.patterns):
                continue
            try:
                st = de.stat(follow_symlinks=self.follow_symlinks)
            except OSError as exc:
                self.stats.errors += 1
                if keep_children:
                    children.append(
                        Entry(name=name, is_dir=de.is_dir(follow_symlinks=False), error=str(exc))
                    )
                continue

            is_symlink = de.is_symlink()
            is_dir = de.is_dir(follow_symlinks=self.follow_symlinks) and (
                self.follow_symlinks or not is_symlink
            )

            if is_dir:
                if not self.cross_mounts and st.st_dev != self.root_dev:
                    if keep_children:
                        children.append(
                            Entry(name=name, is_dir=True, error="different filesystem (skipped)")
                        )
                    continue
                dir_count += 1
                self.stats.dirs_scanned += 1
                child_keep = keep_children and (self.max_depth is None or depth < self.max_depth)
                child = self.scan_dir(
                    os.path.join(abs_path, name), child_rel, depth + 1, child_keep
                )
                total_size += child.size
                file_count += child.file_count
                dir_count += child.dir_count
                if keep_children:
                    children.append(child)
            else:
                key = (st.st_dev, st.st_ino)
                if self.dedupe_hardlinks and st.st_nlink > 1:
                    if key in self.seen_inodes:
                        continue
                    self.seen_inodes.add(key)
                size = (st.st_blocks * 512) if self.use_disk_blocks else st.st_size
                total_size += size
                file_count += 1
                self.stats.files_scanned += 1
                self.stats.bytes_scanned += size
                if keep_children:
                    children.append(Entry(name=name, is_dir=False, size=size, file_count=1))

        entry.size = total_size
        entry.file_count = file_count
        entry.dir_count = dir_count
        if keep_children:
            entry.children = children
        return entry


def scan(
    root: str,
    *,
    use_disk_blocks: bool = False,
    cross_mounts: bool = False,
    follow_symlinks: bool = False,
    dedupe_hardlinks: bool = True,
    exclude: Optional[list[str]] = None,
    exclude_common: bool = False,
    max_depth: Optional[int] = None,
    progress: Optional[ProgressCallback] = None,
    progress_interval: float = 0.15,
) -> tuple[Entry, ScanStats]:
    """Scan ``root`` and return ``(tree, stats)``.

    ``max_depth`` limits how many levels of *individual children* are kept
    in the resulting tree; sizes/counts are still aggregated correctly for
    everything below that depth, this just bounds memory usage on very
    deep/wide trees while keeping totals correct.
    """
    root = os.path.abspath(os.path.expanduser(root))
    patterns = list(exclude or [])
    if exclude_common:
        patterns += COMMON_EXCLUDES

    try:
        root_stat = os.lstat(root)
    except OSError as exc:
        stats = ScanStats()
        return Entry(name=root, is_dir=True, error=str(exc)), stats

    scanner = _Scanner(
        use_disk_blocks=use_disk_blocks,
        cross_mounts=cross_mounts,
        follow_symlinks=follow_symlinks,
        dedupe_hardlinks=dedupe_hardlinks,
        patterns=patterns,
        max_depth=max_depth,
        root_dev=root_stat.st_dev,
        progress=progress,
        progress_interval=progress_interval,
    )
    entry = scanner.scan_dir(root, "", 0, keep_children=True)
    entry.name = root
    scanner.stats.elapsed = time.monotonic() - scanner._start
    if progress is not None:
        progress(root, scanner.stats)
    return entry, scanner.stats


def iter_largest_files(entry: Entry, limit: int = 20) -> list[tuple[str, int]]:
    """Return the ``limit`` largest files anywhere in the tree as
    ``(path, size)`` tuples, largest first. Only sees parts of the tree
    that still have per-file children (i.e. within ``max_depth``)."""
    results: list[tuple[str, int]] = []

    def walk(node: Entry, path: str) -> None:
        for child in node.children:
            child_path = f"{path}/{child.name}" if path else child.name
            if child.is_dir:
                walk(child, child_path)
            else:
                results.append((child_path, child.size))

    walk(entry, "")
    results.sort(key=lambda t: t[1], reverse=True)
    return results[:limit]
