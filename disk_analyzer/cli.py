"""Command-line interface for disk-analyzer."""
from __future__ import annotations

import argparse
import os
import shutil
import sys
from typing import Optional

from .export import write_csv, write_json
from .format import bar, human_size
from .scanner import Entry, ScanStats, iter_largest_files, scan

DEFAULT_TOP_N = 20
DEFAULT_WORKERS = min(8, (os.cpu_count() or 4) * 2)


def _default_targets() -> list[str]:
    return ["/"]


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="disk-analyzer",
        description="Analyze and browse disk usage on macOS (and other POSIX systems).",
    )
    p.add_argument(
        "path",
        nargs="?",
        default="~",
        help="Directory to scan (default: %(default)s)",
    )
    p.add_argument(
        "-n",
        "--top",
        type=int,
        default=DEFAULT_TOP_N,
        metavar="N",
        help="Show top N entries in the summary view (default: %(default)s)",
    )
    p.add_argument(
        "-d",
        "--max-depth",
        type=int,
        default=None,
        metavar="N",
        help="Limit how many levels of individual entries are kept in memory "
        "(totals stay correct beyond this depth; unset = unlimited)",
    )
    p.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Launch the interactive ncdu-style terminal browser",
    )
    p.add_argument(
        "-j",
        "--jobs",
        type=int,
        default=1,
        metavar="N",
        help="Scan top-level subdirectories concurrently using N threads "
        "(speeds up scans with several large sibling directories, e.g. "
        "your home directory or '/'). Default: 1 (serial). Try %(default_workers)s "
        "on this machine for a good starting point." % {"default_workers": DEFAULT_WORKERS},
    )
    p.add_argument(
        "-x",
        "--one-filesystem",
        dest="cross_mounts",
        action="store_false",
        default=False,
        help="(default) Do not cross filesystem/volume boundaries while scanning",
    )
    p.add_argument(
        "--cross-mounts",
        dest="cross_mounts",
        action="store_true",
        help="Allow crossing into other mounted volumes while scanning",
    )
    p.add_argument(
        "-L",
        "--follow-symlinks",
        action="store_true",
        help="Follow symbolic links (off by default to avoid cycles/double counting)",
    )
    p.add_argument(
        "--apparent-size",
        dest="use_disk_blocks",
        action="store_false",
        default=False,
        help="(default) Use apparent file size (st_size) rather than actual disk usage",
    )
    p.add_argument(
        "--disk-usage",
        dest="use_disk_blocks",
        action="store_true",
        help="Use actual disk block usage (st_blocks * 512) instead of apparent size",
    )
    p.add_argument(
        "--exclude",
        action="append",
        default=[],
        metavar="PATTERN",
        help="Glob pattern to exclude (name or relative path); can be repeated",
    )
    p.add_argument(
        "--exclude-common",
        action="store_true",
        help="Exclude common noise dirs: .git, node_modules, Library/Caches, "
        "Library/Containers, Trash, Spotlight/FSEvents metadata, etc.",
    )
    p.add_argument(
        "--largest-files",
        type=int,
        default=0,
        metavar="N",
        help="Also list the N largest individual files found",
    )
    p.add_argument(
        "--json",
        metavar="FILE",
        help="Write the full scanned tree as JSON to FILE ('-' for stdout)",
    )
    p.add_argument(
        "--csv",
        metavar="FILE",
        help="Write a flat CSV listing of every entry to FILE ('-' for stdout)",
    )
    p.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Suppress the live progress line",
    )
    return p


def _print_progress(current_path: str, stats: ScanStats) -> None:
    width = shutil.get_terminal_size((80, 20)).columns
    msg = f"\rScanning... {stats.files_scanned} files, {human_size(stats.bytes_scanned)}  {current_path}"
    sys.stderr.write(msg[: width - 1].ljust(width - 1))
    sys.stderr.flush()


def _clear_progress_line() -> None:
    width = shutil.get_terminal_size((80, 20)).columns
    sys.stderr.write("\r" + " " * (width - 1) + "\r")
    sys.stderr.flush()


def print_summary(root: Entry, stats: ScanStats, top_n: int, largest_files: int) -> None:
    print(f"\n{root.name}")
    print(
        f"  Total: {human_size(root.size)}  "
        f"({root.file_count} files, {root.dir_count} dirs, {stats.errors} errors, "
        f"{stats.elapsed:.1f}s)\n"
    )

    children = root.sorted_children()
    if not children:
        print("  (no accessible entries)")
    else:
        shown = children[:top_n]
        max_size = max((c.size for c in children), default=1) or 1
        name_width = min(40, max((len(c.name) for c in shown), default=10) + 1)
        for c in shown:
            frac = c.size / max_size if max_size else 0
            marker = "/" if c.is_dir else ""
            err = "  [!]" if c.error else ""
            print(
                f"  {human_size(c.size):>9}  [{bar(frac, 24)}]  "
                f"{(c.name + marker):<{name_width}}{err}"
            )
        remaining = len(children) - len(shown)
        if remaining > 0:
            print(f"  ... and {remaining} more entr{'y' if remaining == 1 else 'ies'}")

    if largest_files > 0:
        largest = iter_largest_files(root, limit=largest_files)
        if largest:
            print(f"\n  Largest files:")
            for path, size in largest:
                print(f"    {human_size(size):>9}  {path}")


def _open_output(path: str, mode: str = "w"):
    if path == "-":
        return sys.stdout
    return open(path, mode, newline="" if mode == "w" else None)


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    progress = None if args.quiet else _print_progress

    try:
        root, stats = scan(
            args.path,
            use_disk_blocks=args.use_disk_blocks,
            cross_mounts=args.cross_mounts,
            follow_symlinks=args.follow_symlinks,
            exclude=args.exclude,
            exclude_common=args.exclude_common,
            max_depth=args.max_depth,
            progress=progress,
            workers=args.jobs,
        )
    finally:
        if progress is not None:
            _clear_progress_line()

    if root.error and not root.children:
        print(f"Error scanning '{args.path}': {root.error}", file=sys.stderr)
        return 1

    if args.json:
        fh = _open_output(args.json)
        try:
            write_json(root, fh)
        finally:
            if fh is not sys.stdout:
                fh.close()

    if args.csv:
        fh = _open_output(args.csv)
        try:
            write_csv(root, fh)
        finally:
            if fh is not sys.stdout:
                fh.close()

    if args.interactive:
        from .browser import run_browser

        run_browser(root)
        return 0

    if not args.json and not args.csv:
        print_summary(root, stats, args.top, args.largest_files)
    elif not args.quiet:
        # Still show a brief summary even when exporting, unless quiet.
        print(
            f"Scanned {root.name}: {human_size(root.size)} total "
            f"({root.file_count} files, {root.dir_count} dirs, {stats.errors} errors) "
            f"in {stats.elapsed:.1f}s",
            file=sys.stderr,
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
