"""Where the thread store is: one global store, or one per project.

`scope: global | project` in ~/.spindle/config.yml (no file means global).
global: ~/.spindle. project: <project>/.spindle, where the project is the git
repository the launch folder is in, or the launch folder itself outside git.
The launch folder is SPINDLE_PROJECT (set by the harness plugins at session
start), else the current directory. A linked worktree uses its main checkout,
so every worktree of a repository shares one store. --root and SPINDLE_ROOT
outrank all of it.
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
    chosen = value or os.environ.get("SPINDLE_ROOT")
    if chosen:
        return Path(chosen).expanduser().resolve(), "explicit"
    if scope() == "project":
        folder = Path(os.environ.get("SPINDLE_PROJECT") or os.getcwd()).expanduser().resolve()
        return project_of(folder) / ".spindle", "project"
    return GLOBAL_ROOT.expanduser().resolve(), "global"


def project_of(folder: Path) -> Path:
    """The repository ``folder`` is in (its main checkout, for a linked worktree),
    or ``folder`` itself when it isn't in one or git can't say."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--path-format=absolute", "--show-toplevel", "--git-common-dir"],
            cwd=folder, text=True, capture_output=True, check=False,
        )
    except OSError:  # no git, or the folder is gone
        return folder
    lines = result.stdout.splitlines()
    if result.returncode != 0 or len(lines) != 2:
        return folder  # not in a repository, or inside .git or a bare one
    top, common = Path(lines[0]), Path(lines[1])
    # A linked worktree's common dir is the main checkout's .git. A bare main
    # repository has no checkout to share, so each worktree keeps its own.
    if common.name == ".git" and common.parent != top:
        return common.parent.resolve()
    return top.resolve()


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
