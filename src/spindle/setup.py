"""Install Spindle's standing instructions (prompts/system-blurb.md) for a harness.

Where they go, per harness:
- claude-code: its own file, ~/.claude/rules/spindle.md. User rules load in
  every session, like ~/.claude/CLAUDE.md, without touching that file.
- omp: its own file, ~/.omp/agent/rules/spindle.md, marked alwaysApply so it
  goes into the system prompt. omp keeps only one user-level AGENTS.md-style
  file (whichever provider wins), so writing one of those could hide the
  user's own; rules aren't deduplicated that way.
- pi: a marked block appended to ~/.pi/agent/AGENTS.md. pi has no rules
  directory; it joins every AGENTS.md it finds, so appending is safe.

Setup replaces its own file or block, so running it again updates the
instructions after a Spindle upgrade. The harness hooks call `status` at
session start and mention setup when it's missing or out of date.
"""

from __future__ import annotations

import os
from pathlib import Path

from .store import ThreadError, atomic_text as _atomic_text

HARNESSES = ("claude-code", "pi", "omp")
BEGIN = "<!-- spindle:begin (managed by `thread setup`; edits here are replaced) -->"
END = "<!-- spindle:end -->"
BLURB = Path(__file__).resolve().parents[2] / "prompts" / "system-blurb.md"


def atomic_text(path: Path, text: str) -> None:
    """Write atomically without changing the file's permissions. These are the user's
    harness config files; a temp-file write alone would leave them owner-only (0600)."""
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o644
    _atomic_text(path, text)
    path.chmod(mode)


def blurb() -> str:
    try:
        return BLURB.read_text(encoding="utf-8").strip() + "\n"
    except FileNotFoundError as exc:
        raise ThreadError(f"Spindle's instructions are missing from this install ({BLURB})") from exc


def target(harness: str) -> Path:
    if harness == "claude-code":
        base = os.environ.get("CLAUDE_CONFIG_DIR") or "~/.claude"
        return Path(base).expanduser() / "rules" / "spindle.md"
    if harness == "omp":
        base = os.environ.get("PI_CODING_AGENT_DIR") or "~/.omp/agent"
        return Path(base).expanduser() / "rules" / "spindle.md"
    if harness == "pi":
        base = os.environ.get("PI_CODING_AGENT_DIR") or "~/.pi/agent"
        return Path(base).expanduser() / "AGENTS.md"
    raise ThreadError(f"unknown harness {harness!r}; choose one of: {', '.join(HARNESSES)}")


def _owned(harness: str) -> bool:
    """Spindle owns the whole file (rules), rather than a block inside the user's file."""
    return harness in ("claude-code", "omp")


def expected(harness: str) -> str:
    """What setup writes: the whole file for rules, the block for pi."""
    body = f"{BEGIN}\n{blurb()}{END}\n"
    if harness == "omp":
        return f"---\ndescription: Spindle, memory across sessions (threads)\nalwaysApply: true\n---\n{body}"
    return body


def _block(text: str) -> str | None:
    start = text.find(BEGIN)
    end = text.find(END, start + 1) if start >= 0 else -1
    if start < 0 or end < 0:
        return None
    return text[start : end + len(END)] + "\n"


def status(harness: str) -> str:
    """'current', 'outdated' (an older Spindle wrote it), or 'missing'."""
    path = target(harness)
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "missing"
    if _owned(harness):
        return "current" if text == expected(harness) else "outdated"
    found = _block(text)
    if found is None:
        return "missing"
    return "current" if found == expected(harness) else "outdated"


def install(harness: str) -> tuple[Path, str]:
    """Write or refresh the instructions. Returns the path and what changed."""
    path = target(harness)
    before = status(harness)
    if before == "current":
        return path, "already current"
    if _owned(harness):
        atomic_text(path, expected(harness))
    else:
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        found = _block(text)
        if found is not None:
            text = text.replace(found, expected(harness), 1)
        else:
            text = (text.rstrip("\n") + "\n\n" if text.strip() else "") + expected(harness)
        atomic_text(path, text)
    return path, "updated" if before == "outdated" else "installed"


def remove(harness: str) -> tuple[Path, bool]:
    """Take the instructions out again. Returns the path and whether anything was removed."""
    path = target(harness)
    if not path.exists():
        return path, False
    if _owned(harness):
        path.unlink()
        return path, True
    text = path.read_text(encoding="utf-8")
    found = _block(text)
    if found is None:
        return path, False
    rest = text.replace(found, "", 1).rstrip("\n")
    atomic_text(path, rest + "\n" if rest.strip() else "")
    return path, True


def reminder(harness: str) -> str | None:
    """One line for the session-start snapshot when setup is needed, else None."""
    try:
        state = status(harness)
    except ThreadError:
        return None
    if state == "current":
        return None
    what = ("Spindle is installed but not set up for this harness" if state == "missing"
            else "Spindle's standing instructions for this harness are from an older version")
    return (f"{what}. The spindle-setup skill fixes this in one step; suggest it to the user "
            "before doing Spindle work.")
