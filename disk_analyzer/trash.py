"""Safe deletion helpers for macOS: move files/directories to Trash instead
of permanently removing them, with a manual fallback if Finder scripting is
unavailable, plus an explicit "permanent delete" for when that's really
wanted.

Why not just ``shutil.move(path, "~/.Trash")``?
  * External/other volumes have their own per-volume Trash at
    ``/Volumes/<name>/.Trashes/<uid>``, not ``~/.Trash``. Moving into the
    wrong one can fail across filesystem boundaries or silently store the
    item somewhere the Finder Trash UI won't show it.
  * Finder's real "Move to Trash" also handles name collisions (renaming
    ``foo.txt`` to ``foo 2.txt`` etc.) and sets the metadata needed for
    "Put Back". Asking Finder to do it (via AppleScript) gets this for
    free.

So the primary path asks Finder to do it via ``osascript``. If that's
unavailable (non-interactive environments, Automation permission denied,
etc.) we fall back to a manual move into the correct per-volume Trash
directory, and only permanently delete if the caller explicitly asks for
that.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Optional


class TrashError(RuntimeError):
    pass


def _volume_trash_dir(path: str) -> str:
    """Return the appropriate Trash directory for the volume containing
    ``path`` (``~/.Trash`` for the boot volume, ``/Volumes/X/.Trashes/<uid>``
    for other mounted volumes)."""
    home_trash = os.path.expanduser("~/.Trash")
    try:
        path_dev = os.stat(path).st_dev
        home_dev = os.stat(os.path.expanduser("~")).st_dev
    except OSError:
        return home_trash
    if path_dev == home_dev:
        return home_trash

    # Find which /Volumes/* mount this path lives under.
    volumes_root = "/Volumes"
    if os.path.isdir(volumes_root):
        try:
            for name in os.listdir(volumes_root):
                vol_path = os.path.join(volumes_root, name)
                try:
                    if os.stat(vol_path).st_dev == path_dev:
                        return os.path.join(vol_path, ".Trashes", str(os.getuid()))
                except OSError:
                    continue
        except OSError:
            pass
    return home_trash


def _unique_destination(trash_dir: str, name: str) -> str:
    candidate = os.path.join(trash_dir, name)
    if not os.path.exists(candidate):
        return candidate
    base, ext = os.path.splitext(name)
    n = 2
    while True:
        candidate = os.path.join(trash_dir, f"{base} {n}{ext}")
        if not os.path.exists(candidate):
            return candidate
        n += 1


def _manual_move_to_trash(path: str) -> None:
    trash_dir = _volume_trash_dir(path)
    os.makedirs(trash_dir, exist_ok=True)
    dest = _unique_destination(trash_dir, os.path.basename(path))
    shutil.move(path, dest)


def _osascript_move_to_trash(path: str) -> None:
    script = (
        f'tell application "Finder" to delete (POSIX file "{path}" as alias)'
    )
    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        raise TrashError(result.stderr.strip() or "osascript failed")


def move_to_trash(path: str, *, use_finder: bool = True) -> None:
    """Move ``path`` to the Trash. Tries Finder (via AppleScript) first so
    it behaves exactly like dragging the item to the Trash in the Finder
    UI (per-volume Trash, name collision handling, "Put Back" support);
    falls back to a manual move into the right Trash directory if that
    fails or ``use_finder`` is False.

    Raises ``TrashError`` / ``OSError`` if both approaches fail.
    """
    path = os.path.abspath(path)
    if not os.path.exists(path) and not os.path.islink(path):
        raise TrashError(f"No such file or directory: {path}")

    if use_finder:
        try:
            _osascript_move_to_trash(path)
            return
        except (TrashError, subprocess.SubprocessError, FileNotFoundError, OSError):
            pass  # fall through to manual move

    _manual_move_to_trash(path)


def permanently_delete(path: str) -> None:
    """Irreversibly delete ``path``. Use only when the caller has been
    explicit about wanting a permanent delete (bypassing Trash)."""
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    else:
        os.remove(path)
