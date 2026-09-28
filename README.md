# disk-analyzer

A fast, dependency-free disk usage analyzer for macOS with an interactive,
`ncdu`-style terminal browser. Pure Python standard library — no third-party
runtime dependencies.

## Features

- **Fast recursive scanning** of any directory (or the whole disk).
- **Interactive browser** (`-i`): navigate directories, see proportional size
  bars, delete files/folders, and reveal items in Finder — all from the
  terminal.
- **Safe by default**: doesn't cross filesystem/volume boundaries, doesn't
  follow symlinks, and de-dupes hardlinks so totals aren't inflated.
- **Handles permission errors gracefully** — things like SIP-protected paths
  or `~/Library/Containers` won't crash the scan; they're reported as errors
  and skipped.
- **Exports**: full tree as JSON, or a flat listing as CSV.
- **Largest files** report across the whole scanned tree.
- **Exclude patterns** (glob) plus a built-in `--exclude-common` preset for
  typical noise (`.git`, `node_modules`, `Library/Caches`, Trash, etc.).

## Install

```bash
cd disk-analyzer
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

This installs the `disk-analyzer` command into your virtualenv.

## Usage

```bash
# Summary of the largest entries in your home directory
disk-analyzer ~

# Interactive ncdu-style browser
disk-analyzer ~ -i

# Scan the whole disk (may need sudo for some system paths)
sudo disk-analyzer / -i

# Show the 30 largest individual files under Downloads
disk-analyzer ~/Downloads --largest-files 30

# Exclude common noise and export full tree as JSON
disk-analyzer ~/Projects --exclude-common --json tree.json

# Flat CSV of every file/dir found
disk-analyzer ~/Projects --csv usage.csv
```

### Interactive browser keys

| Key | Action |
| --- | --- |
| `↑`/`k`, `↓`/`j` | Move selection |
| `→`/`l`/`Enter` | Open selected directory |
| `←`/`h`/`Backspace` | Go up one level (or quit at root) |
| `d` | Delete selected file/directory (asks to confirm) |
| `o` | Reveal selected item in Finder |
| `q` / `Esc` | Quit |

### CLI options

```
usage: disk-analyzer [-h] [-n N] [-d N] [-i] [-x] [--cross-mounts] [-L]
                      [--apparent-size] [--disk-usage] [--exclude PATTERN]
                      [--exclude-common] [--largest-files N] [--json FILE]
                      [--csv FILE] [-q]
                      [path]
```

Run `disk-analyzer --help` for full details.

## Development

```bash
source .venv/bin/activate
python -m pytest -q
```

## How it works

- `disk_analyzer/scanner.py` — recursive scan engine (stdlib `os.scandir`),
  aggregates size/file/dir counts bottom-up, skips other filesystems by
  default, de-dupes hardlinks, and tolerates `OSError`s per-entry.
- `disk_analyzer/browser.py` — `curses`-based interactive tree browser.
- `disk_analyzer/export.py` — JSON/CSV exporters.
- `disk_analyzer/format.py` — human-readable size/bar formatting helpers.
- `disk_analyzer/cli.py` — argument parsing and the non-interactive summary
  view.

## Notes on macOS specifics

- Scanning `/` will hit many permission-restricted paths (SIP, other users'
  home directories, `.Spotlight-V100`, Time Machine local snapshots, etc.).
  These are counted as errors and skipped rather than aborting the whole
  scan. Run with `sudo` to see more of the system volume.
- By default the scanner uses **apparent size** (`st_size`); pass
  `--disk-usage` to use actual disk block usage instead (closer to what
  Finder's "on disk" size shows for sparse/compressed files).
- By default the scanner **does not cross mount points**, so scanning `/`
  won't wander into other APFS volumes or network shares. Pass
  `--cross-mounts` to include them.
