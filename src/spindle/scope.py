"""Where the thread store is: one global store, or one per project.

`scope: global | project` in ~/.spindle/config.yml (no file means global).
global: ~/.spindle. project: <launch folder>/.spindle, where the launch folder
is SPINDLE_PROJECT (set by the harness plugins at session start), else the
current directory. --root and SPINDLE_ROOT outrank both.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import yaml

from .store import DEFAULT_ROOT as GLOBAL_ROOT, ThreadError, atomic_text

SCOPES = ("global", "project")
IGNORE_LINE = "**/.spindle/"


def config_path() -> Path:
    return (GLOBAL_ROOT / "config.yml").expanduser()


def scope() -> str:
    path = config_path()
    try:
        value = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("scope", "global")
    except FileNotFoundError:
        return "global"
    if value not in SCOPES:
        raise ThreadError(f"{path}: scope must be global or project; got {value!r}")
    return value


def write_scope(value: str) -> None:
    atomic_text(config_path(), f"scope: {value}\n")


def locate(value: str | Path | None = None) -> tuple[Path, str]:
    """(store path, 'explicit' | 'global' | 'project'). The path may not exist yet."""
    chosen = value or os.environ.get("SPINDLE_ROOT") or os.environ.get("THREADS_ROOT")
    if chosen:
        return Path(chosen).expanduser().resolve(), "explicit"
    if scope() == "project":
        folder = os.environ.get("SPINDLE_PROJECT") or os.getcwd()
        return Path(folder).expanduser().resolve() / ".spindle", "project"
    return GLOBAL_ROOT.expanduser().resolve(), "global"


def global_ignore_file() -> Path:
    """core.excludesfile, else $XDG_CONFIG_HOME/git/ignore, else ~/.config/git/ignore."""
    result = subprocess.run(["git", "config", "--global", "--get", "core.excludesfile"],
                            text=True, capture_output=True, check=False)
    if result.stdout.strip():
        return Path(result.stdout.strip()).expanduser()
    return Path(os.environ.get("XDG_CONFIG_HOME") or "~/.config").expanduser() / "git" / "ignore"


def ensure_global_ignore() -> Path | None:
    """Add `**/.spindle/` to the user's global git ignore, as Claude Code does for
    .claude/settings.local.json. Returns the file if a line was added."""
    path = global_ignore_file()
    text = path.read_text(encoding="utf-8") if path.exists() else ""
    if any(line.strip().strip("/").removeprefix("**/") == ".spindle" for line in text.splitlines()):
        return None
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(("" if not text or text.endswith("\n") else "\n") + IGNORE_LINE + "\n")
    return path


def start_project_store(path: Path) -> list[str]:
    """Create a project store and cover it in the global ignore; returns what was done."""
    from .store import initialize

    initialize(path)
    notes = [f"Started this project's thread store at {path}."]
    added = ensure_global_ignore()
    if added:
        notes.append(f"Added `{IGNORE_LINE}` to your global git ignore ({added}).")
    return notes
