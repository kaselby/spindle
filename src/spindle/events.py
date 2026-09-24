"""Identity, append-only event I/O, and the thread.yml fold."""

from __future__ import annotations

import fcntl
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .limits import LIMITS
from .store import ThreadError, atomic_text, current_state, parse_frontmatter, read_yaml, write_yaml


# Child lifecycle events seen on the PARENT, and the child state each implies.
_CHILD_STATE = {
    "child-merged": "merged",
    "child-dropped": "dropped",
    "child-closed": "completed",  # written before the rename; read only
    "child-reopened": "active",
    "child-superseded": "dropped",  # legacy; supersede is no longer written
}


def now() -> datetime:
    return datetime.now(timezone.utc)


def timestamp(moment: datetime | None = None) -> str:
    return (moment or now()).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def identity(value: str | None = None) -> dict[str, str]:
    if value:
        session, separator, agent = value.partition("/")
        if not session:
            raise ThreadError("--by takes a session name, or session/agent, like --by alpha or --by alpha/opus.")
        return {"session": session, "agent": agent if separator else session}
    from .identity import resolve

    return resolve()


def read_events(thread: Path) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    try:
        lines = (thread / "log.jsonl").read_text(encoding="utf-8").splitlines()
    except FileNotFoundError as exc:
        raise ThreadError(f"{thread.name} has no log.jsonl; restore it from git in the .spindle folder.") from exc
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ThreadError(
                f"{thread.name}/log.jsonl line {number} is not valid JSON ({exc.msg}); "
                "fix or remove that line (check `git diff` in the .spindle folder)."
            ) from exc
        events.append(event)
    return events


def tip(thread: Path) -> str | None:
    events = read_events(thread)
    return events[-1]["id"] if events else None


def _event_id() -> str:
    stamp = now().strftime("%Y%m%dT%H%M%S")
    suffix = "".join(secrets.choice("23456789abcdefghjkmnpqrstuvwxyz") for _ in range(4))
    return f"{stamp}-{suffix}"


def append(
    thread: Path,
    kind: str,
    payload: dict[str, Any] | None,
    by: dict[str, str],
    *,
    expected_tip: str | None = None,
    event_ts: str | None = None,
    reopen: bool = True,
) -> dict[str, Any]:
    """Append under an advisory lock; expected_tip makes the operation CAS."""
    if reopen and by.get("session") != "doctor" and kind != "state-changed":
        cache = read_yaml(thread / "thread.yml", {})
        if cache.get("state") == "inactive":
            append(
                thread, "state-changed", {"from": "inactive", "to": "active"}, by,
                expected_tip=expected_tip, reopen=False,
            )
            expected_tip = tip(thread)

    log = thread / "log.jsonl"
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a+", encoding="utf-8") as handle:
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.seek(0)
        lines = [line for line in handle.read().splitlines() if line.strip()]
        current = json.loads(lines[-1])["id"] if lines else None
        if expected_tip is not None and current != expected_tip:
            raise ThreadError(
                f"another session wrote to {thread.name} while this command ran "
                f"(expected latest event {expected_tip}, found {current}). Nothing was written; "
                "run the command again.", code=4,
            )
        event = {
            "id": _event_id(),
            "ts": event_ts or timestamp(),
            "by": by,
            "type": kind,
            "payload": payload or {},
        }
        handle.seek(0, os.SEEK_END)
        handle.write(json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
        fcntl.flock(handle, fcntl.LOCK_UN)
    regenerate(thread)
    return event


def _origin(thread: Path) -> dict[str, Any]:
    metadata, _ = parse_frontmatter((thread / "origin.md").read_text(encoding="utf-8"))
    return metadata


def fold(thread: Path, events: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    events = read_events(thread) if events is None else events
    if not events:
        raise ThreadError(f"{thread.name}/log.jsonl is empty; restore it from git in the .spindle folder.")
    origin = _origin(thread)
    identifier, _, slug = thread.name.partition("-")
    state = "active"
    claims: dict[str, dict[str, Any]] = {}
    children: dict[str, dict[str, Any]] = {}
    latest_checkpoint: dict[str, Any] | None = None
    last_checkpoint_index = -1
    superseded_by: str | None = None
    reparented_to: str | None = None
    links: list[dict[str, str]] = []

    for index, event in enumerate(events):
        session = event["by"]["session"]
        if session in claims:
            claims[session]["last-seen"] = event["ts"]
        kind, payload = event["type"], event.get("payload", {})
        if kind == "claim":
            claim = {"by": event["by"], "since": event["ts"], "last-seen": event["ts"]}
            if payload.get("intent"):
                claim["intent"] = payload["intent"]
            claims[session] = claim
        elif kind == "release":
            claims.pop(payload.get("session", session), None)
        elif kind == "state-changed":
            state = current_state(payload["to"], payload.get("reason"))
            superseded_by = payload.get("successor", payload.get("superseded-by", superseded_by))
        elif kind == "checkpoint":
            latest_checkpoint = {
                "id": payload["checkpoint"], "ts": event["ts"], "headline": payload["headline"]
            }
            last_checkpoint_index = index
        elif kind in ("child-created", "child-adopted"):
            children[payload["child"]] = {
                "id": payload["child"], "title": payload["title"], "state": "active"
            }
        elif kind == "child-merged" and payload.get("child") in children:
            children[payload["child"]]["state"] = "merged"
            if payload.get("checkpoint"):
                children[payload["child"]]["merged"] = payload["checkpoint"]
        elif kind == "reparented":
            reparented_to = payload["to"]
        elif kind == "linked":
            link = {"kind": payload["kind"], "target": payload["target"]}
            if link not in links:
                links.append(link)
        elif kind == "unlinked":
            links = [
                link for link in links
                if link != {"kind": payload["kind"], "target": payload["target"]}
            ]
        elif kind in _CHILD_STATE and payload.get("child") in children:
            children[payload["child"]]["state"] = _CHILD_STATE[kind]

    # Lifecycle bookkeeping written by merge/complete/drop is not "work
    # since the checkpoint" -- a finished thread must not read as unsynced.
    unsynced_count = sum(
        1 for event in events[last_checkpoint_index + 1:]
        if event["type"] not in BOOKKEEPING
    )
    prior = read_yaml(thread / "thread.yml", {})
    result: dict[str, Any] = {
        "id": identifier,
        "slug": slug,
        "title": origin["title"],
        "state": state,
        "created": events[0]["ts"],
        "last-event": events[-1]["ts"],
        "tip": events[-1]["id"],
        "events-since-checkpoint": unsynced_count,
        "unsynced": unsynced_count > LIMITS["unsynced_nudge"],
        "claims": list(claims.values()),
        "children": list(children.values()),
        "links": links,
        "scratch-newer-than-checkpoint": scratch_newer(thread, latest_checkpoint),
    }
    for field in ("parent", "supersedes", "project", "namespace"):
        if field in origin:
            result[field] = origin[field]
    if reparented_to:
        # The log outranks origin.md's frontmatter once a thread has moved.
        result["parent"] = reparented_to
    if superseded_by:
        result["superseded-by"] = superseded_by
    if latest_checkpoint:
        result["last-checkpoint"] = latest_checkpoint
    if prior.get("tasks-hash"):
        result["tasks-hash"] = prior["tasks-hash"]
    return result


def scratch_newer(thread: Path, checkpoint: dict[str, Any] | None) -> int:
    # Event timestamps are whole seconds; a file written in the same second as
    # the checkpoint (typically its own body file) isn't newer than it.
    threshold = parse_time(checkpoint["ts"]).timestamp() + 1 if checkpoint else 0
    scratch = thread / "scratch"
    return sum(1 for path in scratch.rglob("*") if path.is_file() and path.stat().st_mtime > threshold)


def regenerate(thread: Path) -> dict[str, Any]:
    value = fold(thread)
    write_yaml(thread / "thread.yml", value)
    return value


def event_summary(event: dict[str, Any], *, full_note: bool = False) -> str:
    payload = event.get("payload", {})
    if event["type"] == "note":
        text = payload.get("text", "")
        return text if full_note else " ".join(text.splitlines())
    if event["type"] == "claim":
        return f"claimed: {payload['intent']}" if payload.get("intent") else "claimed"
    if event["type"] == "release":
        if payload.get("expired"):
            return f"released {payload.get('session', '?')}'s claim after no activity (expired)"
        if payload.get("skipped-checkpoint"):
            return f"released, skipped checkpoint: {payload['skipped-checkpoint']}"
        return "released"
    pieces = []
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            rendered = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        else:
            rendered = str(value)
        pieces.append(f"{key}={rendered}")
    return ", ".join(pieces) or "-"


# Lifecycle bookkeeping written by merge/complete/drop and by shelving is
# not "work since the checkpoint": it is left out of the count everywhere.
# What displays leave out of "events since the last checkpoint": the bookkeeping a
# lifecycle verb writes after the checkpoint it closes over. Claims and releases
# are shown and counted like anything else.
BOOKKEEPING = frozenset({"merged-into", "state-changed"})

# The one rule the GATES use (release gate, clean gate, CAS): does this event
# carry anything a checkpoint writer needs to have read? Presence (claim,
# release), creation, and lifecycle bookkeeping don't. Gates only: nothing
# about what is shown or counted on the view page depends on this.
# Links are display-only (they never gate), so they are shown and counted but
# are not work a checkpoint writer must have read.
NOT_WORK = frozenset({"created", "claim", "release", "merged-into", "state-changed", "linked", "unlinked"})


def carries_work(event: dict[str, Any]) -> bool:
    return event["type"] not in NOT_WORK


def counted_since_checkpoint(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The events behind "N events since the last checkpoint"."""
    return [event for event in since_checkpoint(events) if event["type"] not in BOOKKEEPING]


def since_checkpoint(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    last = max((i for i, event in enumerate(events) if event["type"] == "checkpoint"), default=-1)
    return events[last + 1 :]
