"""Decisions: choices made in a thread, with the reason, kept findable.

Each decision is one file, decisions/D001-<slug>.md, and one `decided` event.
A decision is `working` (the current best judgement, open to revision) or
`settled` (the user addressed it directly). Nothing is edited in place: a
change of mind is a new decision that supersedes the old one, and the old file
stays, marked `superseded-by`. Which decisions are live is computed from the
log; the frontmatter mark is for anyone reading the file directly.

Decisions are looked up with `thread decisions`; the view page only says how
many there are.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import events
from .store import (
    ThreadError, atomic_text, markdown, parse_frontmatter, slugify, strip_comments,
)

STATUSES = ("working", "settled")
REQUIRED = ("Decision", "Why")
OPTIONAL = ("Alternatives",)
_ID = re.compile(r"^D\d{3,}$")

TEMPLATE = """\
## Decision
<!-- Required. What was decided, plainly. -->

## Why
<!-- Required. The reason. A later session uses this to judge whether the
     decision still holds, so give the reason that would change if it shouldn't. -->

## Alternatives
<!-- Optional. What else was considered, and why it lost. -->
"""


def template(command: str) -> str:
    return (
        f"<!-- Decision template. Fill it in, save it to a file, and run:\n"
        f"       {command}\n"
        f"     Add --settled only if the user addressed this decision directly.\n"
        f"     Comment lines like this one are ignored. -->\n\n" + TEMPLATE
    )


def _sections(body: str) -> dict[str, str]:
    lines = strip_comments(body).splitlines()
    headings = [(i, line[3:].strip()) for i, line in enumerate(lines) if line.startswith("## ")]
    found: dict[str, str] = {}
    for position, (start, name) in enumerate(headings):
        end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        found[name] = "\n".join(lines[start + 1:end]).strip()
    return found


def _check_body(body: str) -> str:
    found = _sections(body)
    for name in REQUIRED:
        if not found.get(name):
            raise ThreadError(
                f"a decision needs a non-empty `## {name}` section. "
                f"`thread decide <id> \"<title>\"` without a body prints the template."
            )
    unknown = [name for name in found if name not in REQUIRED + OPTIONAL]
    if unknown:
        raise ThreadError(
            f"a decision has `## Decision`, `## Why` and optionally `## Alternatives`; "
            f"remove or rename `## {unknown[0]}`."
        )
    return "\n\n".join(f"## {name}\n\n{found[name]}" for name in REQUIRED + OPTIONAL if found.get(name)) + "\n"


def records(thread: Path) -> list[dict[str, Any]]:
    """Every decision in the thread, oldest first, from the log. Each record
    has id, title, status, ts, by, file, supersedes and superseded-by."""
    found: dict[str, dict[str, Any]] = {}
    for event in events.read_events(thread):
        if event["type"] != "decided":
            continue
        payload = event["payload"]
        record = {
            "id": payload["decision"], "title": payload["title"], "status": payload["status"],
            "ts": event["ts"], "by": event["by"], "file": payload.get("file"),
            "supersedes": payload.get("supersedes"), "superseded-by": None,
        }
        found[record["id"]] = record
        if record["supersedes"] in found:
            found[record["supersedes"]]["superseded-by"] = record["id"]
    return list(found.values())


def live(thread: Path) -> list[dict[str, Any]]:
    return [record for record in records(thread) if not record["superseded-by"]]


def decide(
    thread: Path, title: str, body_text: str, by: dict[str, str], *,
    settled: bool = False, supersedes: str | None = None,
) -> dict[str, Any]:
    if not title.strip() or len(title) > 80 or "\n" in title:
        raise ThreadError(
            f"a decision title is one line of at most 80 characters; this one is {len(title)}. "
            "Detail belongs in the body."
        )
    body = _check_body(body_text)
    existing = records(thread)
    if supersedes is not None:
        supersedes = supersedes.upper()
        old = next((record for record in existing if record["id"] == supersedes), None)
        if old is None:
            raise ThreadError(
                f"{thread.name.split('-', 1)[0]} has no decision {supersedes}. "
                f"`thread decisions {thread.name.split('-', 1)[0]} --all` lists them."
            )
        if old["superseded-by"]:
            raise ThreadError(
                f"{supersedes} was already superseded by {old['superseded-by']}. "
                f"Supersede {old['superseded-by']} instead."
            )
    number = max((int(record["id"][1:]) for record in existing), default=0) + 1
    identifier = f"D{number:03d}"
    relative = f"decisions/{identifier}-{slugify(title)}.md"
    status = "settled" if settled else "working"
    front: dict[str, Any] = {
        "id": identifier, "title": title, "status": status,
        "created": events.timestamp(), "by": by,
    }
    if supersedes:
        front["supersedes"] = supersedes
    atomic_text(thread / relative, markdown(front, body))
    if supersedes:
        old_file = thread / (old["file"] or "")
        if old["file"] and old_file.is_file():
            old_front, old_body = parse_frontmatter(old_file.read_text(encoding="utf-8"))
            old_front["superseded-by"] = identifier
            atomic_text(old_file, markdown(old_front, old_body))
    payload: dict[str, Any] = {"decision": identifier, "title": title, "status": status, "file": relative}
    if supersedes:
        payload["supersedes"] = supersedes
    event = events.append(thread, "decided", payload, by)
    return {**payload, "event": event["id"], "path": str(thread / relative)}


def _line(record: dict[str, Any]) -> str:
    mark = f"superseded by {record['superseded-by']}" if record["superseded-by"] else record["status"]
    replaces = f", replaces {record['supersedes']}" if record["supersedes"] else ""
    return f"- {record['id']} [{mark}] {record['title']} ({record['ts'][:10]}{replaces})"


def listing(thread: Path, *, include_superseded: bool = False) -> list[str]:
    shown = records(thread) if include_superseded else live(thread)
    return [_line(record) for record in shown]


def show(thread: Path, decision: str) -> str:
    decision = decision.upper()
    if not _ID.match(decision):
        raise ThreadError(f"decision ids look like D003; got {decision}.")
    record = next((item for item in records(thread) if item["id"] == decision), None)
    if record is None or not record["file"] or not (thread / record["file"]).is_file():
        raise ThreadError(
            f"{thread.name.split('-', 1)[0]} has no decision {decision}. "
            f"`thread decisions {thread.name.split('-', 1)[0]} --all` lists them."
        )
    return (thread / record["file"]).read_text(encoding="utf-8")


def view_line(thread: Path) -> list[str]:
    """The one line the view page gives decisions: how many, and where to look."""
    current = live(thread)
    if not current:
        return []
    settled = sum(1 for record in current if record["status"] == "settled")
    working = len(current) - settled
    parts = [f"{working} working" if working else "", f"{settled} settled" if settled else ""]
    counts = " and ".join(part for part in parts if part)
    identifier = thread.name.split("-", 1)[0]
    return [f"*Decisions: {counts}. `thread decisions {identifier}` lists them.*", ""]
