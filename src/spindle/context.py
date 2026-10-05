"""The startup snapshot: the active threads a session is told about when it starts.

Every harness hook (Claude Code, pi, omp) runs `python -m spindle.context`
and delivers the text it prints; none of them format anything.

Rules the integrations rely on:
- Snapshot once, at the start of a conversation. Never refresh it mid-session:
  a changing prefix breaks the prompt cache and shifts the agent's picture of
  the store under it. The adapters enforce *when*; this module only builds text.
- Every active thread is always listed; inactive ones are capped at
  LIMITS["context_inactive"], the most recently active first. Aim to stay under
  BUDGET characters: Claude Code swaps additionalContext longer than 10,000
  characters for a file path and a 2,000-character preview. Only a very large
  number of active threads can exceed it, and that is a signal to end some.
- State facts ("These threads are active: ..."), not commands. Text that reads as
  an out-of-band system instruction can trip prompt-injection defenses.
- Read-only: no doctor pass, no commits, no writes to any thread (state is folded
  from each log in memory; nothing is stored). It runs at every session start, possibly
  in several sessions at once.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import events, summary, tree
from .limits import LIMITS
from .store import iter_threads, is_active

BUDGET = 9_000  # under Claude Code's 10,000-character limit, with room for its label


def _live_claims(cache: dict, now: datetime) -> list[dict]:
    """Claims that haven't expired. Expiry is normally recorded by the next command
    that touches the thread; the snapshot writes nothing, so it applies the same
    cutoff for display only, or a crashed session would look present for days."""
    cutoff = now - timedelta(hours=LIMITS["stale_claim_hours"])
    return [claim for claim in cache.get("claims", []) if events.parse_time(claim["last-seen"]) > cutoff]


def _line(cache: dict, depth: int, *, orphan: bool, namespace: bool = False) -> str:
    extra = []
    if namespace and cache.get("namespace"):
        extra.append(f"namespace {cache['namespace']}")
    if orphan:
        # The parent isn't nested above this line: it has ended, is inactive,
        # or sits in another namespace.
        extra.append(f"subthread of {cache['parent']}")
    claims = ", ".join(c["by"]["session"] for c in cache.get("claims", []))
    if claims:
        extra.append(f"claimed by {claims}")
    suffix = f" ({'; '.join(extra)})" if extra else ""
    return f"{'  ' * depth}- {cache['id']}: {cache['title']}{suffix}"


def _active_lines(active: list[dict], seen: dict[str, str]) -> dict[str, list[str]]:
    """Per namespace, every active thread as an indented tree (see tree.py)."""
    return {
        name: [_line(row.cache, row.depth, orphan=row.orphan) for row in rows]
        for name, rows in tree.arrange(active, seen).items()
    }


def render(root: Path, *, now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    stamp = now.astimezone().strftime("%Y-%m-%d %H:%M")
    active: list[dict] = []
    inactive: list[dict] = []
    seen: dict[str, str] = {}
    unreadable = 0
    for path in iter_threads(root):
        if not is_active(path):
            continue
        # Read-only: metadata from thread.yml, state folded from the log in memory.
        # One damaged thread must not cost every session its snapshot.
        try:
            log = events.read_events(path)
            cache = summary.describe(path, log)
        except summary.UNREADABLE:
            unreadable += 1
            continue
        cache["claims"] = _live_claims(cache, now)
        seen[cache["id"]] = tree.last_activity(log, cache)
        (inactive if cache.get("state") == "inactive" else active).append(cache)

    out = [f"Spindle thread store {root}, as of {stamp}. Threads track ongoing work.", ""]
    if active:
        groups = _active_lines(active, seen)
        out.append(f"Active threads ({len(active)}; subthreads indented under their parent):")
        headed = any(groups)
        for name in sorted(groups, key=lambda k: (k != "", k)):
            if headed:
                out.append(f"Namespace {name or 'default'}:")
            out.extend(groups[name])
    else:
        out.append("No threads are active.")

    if inactive:
        cap = LIMITS["context_inactive"]
        recent = sorted(inactive, key=lambda c: seen[c["id"]], reverse=True)[:cap]
        shown = f"the {len(recent)} most recently active" if len(inactive) > len(recent) else "all"
        out += ["", (
            f"Inactive threads (no activity for {LIMITS['inactive_days']}+ days; "
            f"{len(inactive)} in all, {shown} shown):"
        )]
        spread = any(cache.get("namespace") for cache in [*active, *inactive])
        out.extend(_line(cache, 0, orphan=bool(cache.get("parent")), namespace=spread) for cache in recent)
        if len(inactive) > len(recent):
            out.append(f"- … {len(inactive) - len(recent)} more; `thread list` shows all")

    if unreadable:
        out += ["", (
            f"{unreadable} thread folder{'s' if unreadable != 1 else ''} couldn't be read and "
            f"{'are' if unreadable != 1 else 'is'} left out; `thread doctor` says which."
        )]
    if active or inactive:
        out.append("`thread view <id>` shows a thread's view page: where it stands and where to look.")
    return "\n".join(out).rstrip() + "\n"


def wrap(text: str) -> str:
    """The form Claude Code gives hook context, for harnesses that add no tags of their own."""
    return f"<system-reminder>\n{text.rstrip()}\n</system-reminder>"


def once(root: Path, key: str) -> bool:
    """True the first time `key` is seen for this store, False after.

    For adapters with no "first time" signal of their own, like Claude Code's
    SubagentStart, which also fires when a subagent resumes and on every message
    an agent-team teammate handles. Markers live in scratch/, which git ignores.
    """
    marker = root / "scratch" / "hooks" / "once" / hashlib.sha256(key.encode()).hexdigest()[:32]
    marker.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(marker, "x", encoding="utf-8") as handle:
            handle.write(key + "\n")
        return True
    except FileExistsError:
        return False


def claude_hook(event: str, text: str) -> str:
    """Claude Code hook output. Its additionalContext arrives as a <system-reminder>
    at the top of the first user turn; plain stdout would render as a status line."""
    import json

    return json.dumps({"hookSpecificOutput": {"hookEventName": event, "additionalContext": text}})


def main(argv: list[str] | None = None) -> int:
    """`python -m spindle.context [--wrap | --claude-hook EVENT] [--harness NAME] [--once KEY] [--root PATH]`,
    for integrations only."""
    import argparse
    import json
    import sys

    from .store import ThreadError, root_path

    p = argparse.ArgumentParser(prog="python -m spindle.context", description=__doc__.splitlines()[0])
    p.add_argument("--root", help="the store (default: $SPINDLE_ROOT, else ~/.spindle)")
    how = p.add_mutually_exclusive_group()
    how.add_argument("--wrap", action="store_true", help="wrap in <system-reminder> tags, for harnesses that add none")
    how.add_argument("--claude-hook", metavar="EVENT", choices=["SessionStart", "SubagentStart"],
                     help="read Claude Code's hook input on stdin and print its JSON output; "
                          "SubagentStart prints once per agent_id")
    p.add_argument("--once", metavar="KEY", help="print nothing if KEY was already used for this store")
    p.add_argument("--harness", choices=["claude-code", "pi", "omp"],
                   help="the harness asking; adds a line if `thread setup` hasn't been run for it (main sessions only)")
    args = p.parse_args(argv)
    key = args.once
    if args.claude_hook:
        try:
            hook_input = json.load(sys.stdin)
        except ValueError:
            hook_input = {}
        # SubagentStart also fires when a subagent resumes and on every message an
        # agent-team teammate handles; the subagent should see the snapshot once.
        if args.claude_hook == "SubagentStart" and not key:
            agent = hook_input.get("agent_id")
            if not agent:
                return 0
            key = f"cc-subagent:{agent}"
    note = None
    if args.harness:
        from .setup import reminder

        note = reminder(args.harness)
    try:
        root = root_path(args.root)
    except ThreadError as error:
        # A missing store must never break session start. Say nothing on stdout,
        # unless setup hasn't been run (which also creates the store).
        print(f"spindle: {error}", file=sys.stderr)
        if not note:
            return 0
        text = note + "\n"
    else:
        if key and not once(root, key):
            return 0
        text = render(root)
        if note:
            text = f"{note}\n\n{text}"
    if args.claude_hook:
        sys.stdout.write(claude_hook(args.claude_hook, text) + "\n")
    else:
        sys.stdout.write(wrap(text) + "\n" if args.wrap else text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
