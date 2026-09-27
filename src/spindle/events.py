"""Identity, append-only event I/O, and the state fold (computed on read, never stored)."""

from __future__ import annotations

import fcntl
import json
import os
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .limits import LIMITS
from .store import ThreadError


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
        problem = _shape_problem(event)
        if problem:
            raise ThreadError(
                f"{thread.name}/log.jsonl line {number} is malformed ({problem}); "
                "fix or remove that line (check `git diff` in the .spindle folder)."
            )
        events.append(event)
    return events


# Required keys per event type, mirroring schemas/event.schema.json (a test
# keeps the two in step). Checked on read, so a damaged or hand-edited line is
# named here instead of surfacing later as a traceback.
EVENT_KEYS = ("id", "ts", "by", "type")
PAYLOAD_KEYS: dict[str, tuple[str, ...]] = {
    "created": ("title",),
    "checkpoint": ("checkpoint", "at", "headline"),
    "note": ("text",),
    "task-added": ("task",), "task-closed": ("task",), "task-removed": ("task",), "task-edited": ("task",),
    "child-created": ("child", "title"),
    "child-merged": ("child", "checkpoint"),
    "register": ("registration", "checkpoint"),
    "state-changed": ("from", "to"),
    "origin-replaced": ("previous", "after-checkpoint"),
    "origin-revised": ("revision",),
    "linked": ("kind", "target"), "unlinked": ("kind", "target"),
    "merged-into": ("parent", "checkpoint"),
    "child-dropped": ("child",), "child-reopened": ("child",),
    "child-adopted": ("child", "title"),
    "reparented": ("from", "to"),
}


def _shape_problem(event: Any) -> str | None:
    if not isinstance(event, dict):
        return "not a JSON object"
    missing = [key for key in EVENT_KEYS if key not in event]
    if missing:
        return f"missing {', '.join(missing)}"
    if not isinstance(event["by"], dict) or "session" not in event["by"]:
        return "`by` has no session"
    payload = event.get("payload", {})
    if not isinstance(payload, dict):
        return "payload is not an object"
    missing = [key for key in PAYLOAD_KEYS.get(event["type"], ()) if key not in payload]
    if missing:
        return f"{event['type']} payload is missing {', '.join(missing)}"
    return None


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
        if lifecycle_state(read_events(thread)) == "inactive":
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
    return event


def lifecycle_state(log: list[dict[str, Any]]) -> str:
    """Just the state: the last state-changed event, else active."""
    for event in reversed(log):
        if event["type"] == "state-changed":
            return event["payload"]["to"]
    return "active"


def state(thread: Path, log: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Where the thread stands, folded from its log. Read-only: nothing here is
    stored, and nothing here is metadata (that is thread.yml's, metadata.read).
    Subthreads come from a scan of the store (summary.children), not from here."""
    log = read_events(thread) if log is None else log
    if not log:
        raise ThreadError(f"{thread.name}/log.jsonl is empty; restore it from git in the .spindle folder.")
    lifecycle = "active"
    claims: dict[str, dict[str, Any]] = {}
    latest_checkpoint: dict[str, Any] | None = None
    last_checkpoint_index = -1

    for index, event in enumerate(log):
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
            lifecycle = payload["to"]
        elif kind == "checkpoint":
            latest_checkpoint = {
                "id": payload["checkpoint"], "ts": event["ts"], "headline": payload["headline"]
            }
            last_checkpoint_index = index

    # Lifecycle bookkeeping written by merge/complete/drop is not "work
    # since the checkpoint" -- a finished thread must not read as unsynced.
    unsynced_count = sum(
        1 for event in log[last_checkpoint_index + 1:]
        if event["type"] not in BOOKKEEPING
    )
    result: dict[str, Any] = {
        "state": lifecycle,
        "created": log[0]["ts"],
        "last-event": log[-1]["ts"],
        "tip": log[-1]["id"],
        "events-since-checkpoint": unsynced_count,
        "unsynced": unsynced_count > LIMITS["unsynced_nudge"],
        "claims": list(claims.values()),
        "links": links(log),
        "scratch-newer-than-checkpoint": scratch_newer(thread, latest_checkpoint),
    }
    if latest_checkpoint:
        result["last-checkpoint"] = latest_checkpoint
    return result


def links(log: list[dict[str, Any]]) -> list[dict[str, str]]:
    """This thread's own links (one-sided), folded from linked/unlinked events."""
    result: list[dict[str, str]] = []
    for event in log:
        if event["type"] not in ("linked", "unlinked"):
            continue
        link = {"kind": event["payload"]["kind"], "target": event["payload"]["target"]}
        if event["type"] == "linked" and link not in result:
            result.append(link)
        elif event["type"] == "unlinked":
            result = [item for item in result if item != link]
    return result


def scratch_newer(thread: Path, checkpoint: dict[str, Any] | None) -> int:
    # Event timestamps are whole seconds; a file written in the same second as
    # the checkpoint (typically its own body file) isn't newer than it.
    threshold = parse_time(checkpoint["ts"]).timestamp() + 1 if checkpoint else 0
    scratch = thread / "scratch"
    return sum(1 for path in scratch.rglob("*") if path.is_file() and path.stat().st_mtime > threshold)


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
    registration = payload.get("registration") if event["type"] == "register" else None
    if registration and registration.get("kind") == "reading-guide":
        where = f" (from {payload['pointer'].split('@', 1)[0]})" if payload.get("pointer") else ""
        note = f": {registration['purpose']}" if registration.get("purpose") else ""
        return f"reading guide updated{where}{note}"
    pieces = []
    for key, value in payload.items():
        if isinstance(value, (dict, list)):
            rendered = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        else:
            rendered = str(value)
        pieces.append(f"{key}={rendered}")
    return ", ".join(pieces) or "-"


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
NOT_WORK = frozenset({
    "created", "claim", "release", "merged-into", "state-changed", "linked", "unlinked",
})


def is_activity(event: dict[str, Any]) -> bool:
    """Somebody wrote this: not the doctor's upkeep.
    Decides when a thread last saw activity (shelving, list order)."""
    return event["by"]["session"] != "doctor"


def carries_work(event: dict[str, Any]) -> bool:
    return event["type"] not in NOT_WORK


def counted_since_checkpoint(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The events behind "N events since the last checkpoint"."""
    return [event for event in since_checkpoint(events) if event["type"] not in BOOKKEEPING]


def since_checkpoint(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    last = max((i for i, event in enumerate(events) if event["type"] == "checkpoint"), default=-1)
    return events[last + 1 :]
