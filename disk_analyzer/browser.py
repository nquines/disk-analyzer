"""Interactive terminal browser for a scanned tree (ncdu-style), built on
the standard-library ``curses`` module."""
from __future__ import annotations

import curses
import os
import subprocess
import sys
from typing import Optional

from . import trash
from .format import bar, human_size
from .scanner import Entry


class Browser:
    def __init__(self, root: Entry):
        self.root = root
        self.stack: list[Entry] = [root]
        self.selected: list[int] = [0]
        self.message: str = ""

    @property
    def current(self) -> Entry:
        return self.stack[-1]

    @property
    def current_children(self) -> list[Entry]:
        return self.current.sorted_children()

    @property
    def sel_index(self) -> int:
        return self.selected[-1]

    def set_sel_index(self, value: int) -> None:
        self.selected[-1] = value

    def enter(self) -> None:
        children = self.current_children
        if not children:
            return
        idx = self.sel_index
        if 0 <= idx < len(children):
            child = children[idx]
            if child.is_dir and not child.error:
                self.stack.append(child)
                self.selected.append(0)

    def back(self) -> bool:
        if len(self.stack) > 1:
            self.stack.pop()
            self.selected.pop()
            return True
        return False

    def path(self) -> str:
        return "/".join(e.name for e in self.stack).replace("//", "/")

    def full_path_of(self, entry: Entry) -> str:
        parts = [e.name for e in self.stack]
        if entry is not self.current:
            parts.append(entry.name)
        return "/".join(parts).replace("//", "/")


def _delete_entry(browser: Browser, entry: Entry, *, permanent: bool = False) -> Optional[str]:
    target = browser.full_path_of(entry)
    # Normalize path building: stack[0].name is already an absolute path.
    if browser.stack[0].name.startswith("/"):
        base = browser.stack[0].name
        rel_parts = [e.name for e in browser.stack[1:]]
        if entry is not browser.current:
            rel_parts.append(entry.name)
        target = os.path.join(base, *rel_parts) if rel_parts else base
    try:
        if permanent:
            trash.permanently_delete(target)
        else:
            trash.move_to_trash(target)
    except (trash.TrashError, OSError) as exc:
        return str(exc)
    # Remove from in-memory tree and fix up aggregates.
    parent = browser.current
    parent.children = [c for c in parent.children if c is not entry]
    for anc in reversed(browser.stack):
        anc.size -= entry.size
        if entry.is_dir:
            anc.dir_count -= 1 + entry.dir_count
        else:
            anc.file_count -= 1
        if anc is parent:
            break
    return None


def _reveal_in_finder(path: str) -> None:
    try:
        subprocess.run(["open", "-R", path], check=False)
    except Exception:
        pass


def _draw(stdscr, browser: Browser) -> None:
    stdscr.erase()
    height, width = stdscr.getmaxyx()
    header_lines = 3
    footer_lines = 2
    list_height = max(1, height - header_lines - footer_lines)

    current = browser.current
    children = browser.current_children

    path_display = browser.stack[0].name
    if len(browser.stack) > 1:
        path_display = os.path.join(
            browser.stack[0].name, *(e.name for e in browser.stack[1:])
        )

    title = f" disk-analyzer  —  {path_display} "
    stdscr.addstr(0, 0, title[: width - 1], curses.A_BOLD | curses.color_pair(1))
    summary = (
        f" {human_size(current.size)} total, "
        f"{current.file_count} files, {current.dir_count} dirs "
    )
    stdscr.addstr(1, 0, summary[: width - 1], curses.A_DIM)
    stdscr.addstr(2, 0, "-" * (width - 1))

    if not children:
        stdscr.addstr(header_lines, 2, "(empty directory)", curses.A_DIM)
    else:
        max_size = max((c.size for c in children), default=1) or 1
        # Scroll window around selection.
        sel = browser.sel_index
        top = max(0, min(sel - list_height // 2, max(0, len(children) - list_height)))
        for row, idx in enumerate(range(top, min(len(children), top + list_height))):
            child = children[idx]
            y = header_lines + row
            is_sel = idx == sel
            attr = curses.A_REVERSE if is_sel else curses.A_NORMAL
            frac = child.size / max_size if max_size else 0
            size_str = human_size(child.size).rjust(9)
            b = bar(frac, width=16)
            marker = "/" if child.is_dir else " "
            err_marker = " !" if child.error else "  "
            name = child.name + marker
            line = f" {size_str} [{b}]{err_marker} {name}"
            stdscr.addstr(y, 0, line[: width - 1].ljust(width - 1), attr)

    footer1 = "↑/k ↓/j move  →/l/Enter open  ←/h/Backspace up  d trash  D perm.delete  o reveal  q quit"
    footer2 = browser.message if browser.message else ""
    stdscr.addstr(height - 2, 0, footer1[: width - 1], curses.A_DIM)
    if footer2:
        stdscr.addstr(height - 1, 0, footer2[: width - 1], curses.color_pair(2))
    stdscr.refresh()


def _confirm(stdscr, prompt: str) -> bool:
    height, width = stdscr.getmaxyx()
    stdscr.addstr(height - 1, 0, (prompt + " [y/N]: ").ljust(width - 1), curses.A_BOLD)
    stdscr.refresh()
    curses.flushinp()
    ch = stdscr.getch()
    return ch in (ord("y"), ord("Y"))


def _run(stdscr, root: Entry) -> None:
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()
    try:
        curses.init_pair(1, curses.COLOR_CYAN, -1)
        curses.init_pair(2, curses.COLOR_YELLOW, -1)
    except curses.error:
        pass

    browser = Browser(root)
    while True:
        browser.message = browser.message  # keep until overwritten
        _draw(stdscr, browser)
        ch = stdscr.getch()
        children = browser.current_children

        if ch in (ord("q"), 27):  # q or ESC
            break
        elif ch in (curses.KEY_UP, ord("k")):
            if children:
                browser.set_sel_index(max(0, browser.sel_index - 1))
            browser.message = ""
        elif ch in (curses.KEY_DOWN, ord("j")):
            if children:
                browser.set_sel_index(min(len(children) - 1, browser.sel_index + 1))
            browser.message = ""
        elif ch in (curses.KEY_RIGHT, ord("l"), 10, 13, curses.KEY_ENTER):
            browser.enter()
            browser.message = ""
        elif ch in (curses.KEY_LEFT, ord("h"), curses.KEY_BACKSPACE, 127, 8):
            if not browser.back():
                break
            browser.message = ""
        elif ch == ord("o"):
            if children:
                entry = children[browser.sel_index]
                full = browser.full_path_of(entry)
                base = browser.stack[0].name
                rel_parts = [e.name for e in browser.stack[1:]]
                if entry is not browser.current:
                    rel_parts.append(entry.name)
                target = os.path.join(base, *rel_parts) if rel_parts else base
                _reveal_in_finder(target)
                browser.message = f"Revealed in Finder: {target}"
        elif ch == ord("d"):
            if children:
                entry = children[browser.sel_index]
                kind = "directory" if entry.is_dir else "file"
                if _confirm(
                    stdscr,
                    f"Move {kind} '{entry.name}' ({human_size(entry.size)}) to Trash?",
                ):
                    err = _delete_entry(browser, entry, permanent=False)
                    if err:
                        browser.message = f"Error moving to Trash: {err}"
                    else:
                        new_children = browser.current_children
                        browser.set_sel_index(min(browser.sel_index, max(0, len(new_children) - 1)))
                        browser.message = f"Moved to Trash: {entry.name}"
                else:
                    browser.message = "Cancelled"
        elif ch == ord("D"):
            if children:
                entry = children[browser.sel_index]
                kind = "directory" if entry.is_dir else "file"
                if _confirm(
                    stdscr,
                    f"PERMANENTLY delete {kind} '{entry.name}' "
                    f"({human_size(entry.size)})? This cannot be undone",
                ):
                    err = _delete_entry(browser, entry, permanent=True)
                    if err:
                        browser.message = f"Error deleting: {err}"
                    else:
                        new_children = browser.current_children
                        browser.set_sel_index(min(browser.sel_index, max(0, len(new_children) - 1)))
                        browser.message = f"Permanently deleted: {entry.name}"
                else:
                    browser.message = "Cancelled"


def run_browser(root: Entry) -> None:
    """Entry point: launch the interactive curses browser."""
    if not sys.stdout.isatty():
        print("Interactive mode requires a terminal (TTY).", file=sys.stderr)
        sys.exit(1)
    curses.wrapper(_run, root)
