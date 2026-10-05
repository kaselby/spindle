"""The mid-session reminder: prompts/reminder.md, under one line about this session's threads.

Hosts decide when it fires (every REMINDER_TOKENS of context growth or
REMINDER_CALLS tool calls, whichever comes first) and call
`python -m spindle.reminder` to get the text. The header names the threads this
session has claimed (the session is resolved as `thread` resolves it), and adds
the count of events since the last checkpoint only when it's over the same
threshold doctor uses.
"""

from __future__ import annotations

from pathlib import Path

from . import events
from .context import _live_claims
from .limits import LIMITS
from .store import iter_threads, is_active

TEXT = Path(__file__).resolve().parents[2] / "prompts" / "reminder.md"


def header(root: Path, session: str) -> str:
    now = events.now()
    held = []
    for thread in iter_threads(root):
        if not is_active(thread):
            continue
        try:
            state = events.state(thread)
        except Exception:  # one unreadable thread must not cost the reminder
            continue
        # Expired claims don't count, the same cutoff `thread list` and the snapshot use.
        if not any(claim["by"]["session"] == session for claim in _live_claims(state, now)):
            continue
        identifier = thread.name.split("-", 1)[0]
        count = state.get("events-since-checkpoint", 0)
        if count > LIMITS["unsynced_nudge"]:
            last = state.get("last-checkpoint", {}).get("id")
            since = f"its last checkpoint ({last})" if last else "it was created, with no checkpoint yet"
            held.append(f"{identifier}: {count} events since {since}")
        else:
            held.append(identifier)
    if not held:
        return ("You haven't claimed a thread. If this work has grown past a few steps, "
                "create or claim one.")
    if all(":" not in item for item in held):
        return f"You hold {', '.join(held)}."
    return "You hold " + "; ".join(held) + "."


def text(root: Path | None, session: str) -> str:
    body = TEXT.read_text(encoding="utf-8").strip()
    if root is None or not root.is_dir():
        return body
    return f"{header(root, session)}\n\n{body}"


def main(argv: list[str] | None = None) -> int:
    """`python -m spindle.reminder [--wrap | --claude-hook EVENT] [--root PATH]`, for hosts only."""
    import argparse
    import json

    from . import identity
    from .context import wrap
    from .store import ThreadError, root_path

    parser = argparse.ArgumentParser(prog="python -m spindle.reminder")
    parser.add_argument("--root", type=Path)
    style = parser.add_mutually_exclusive_group()
    style.add_argument("--wrap", action="store_true", help="wrap in <system-reminder> tags")
    style.add_argument("--claude-hook", metavar="EVENT", help="emit Claude Code hook JSON")
    args = parser.parse_args(argv)
    session = identity.resolve()["session"]
    try:
        root = root_path(args.root)
    except ThreadError:
        root = None
    out = text(root, session)
    if args.claude_hook:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": args.claude_hook, "additionalContext": out}}))
    else:
        print(wrap(out) if args.wrap else out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
