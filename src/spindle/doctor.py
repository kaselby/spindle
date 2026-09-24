"""Named, idempotent maintenance checks."""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path
from typing import Callable

from . import events, tasks
from .limits import LIMITS
from .store import read_yaml, resolve_thread, root_of, ThreadError, is_active, is_final

Finding = tuple[str, str]
DOCTOR = {"session": "doctor", "agent": "doctor"}


def _id(thread: Path) -> str:
    return thread.name.split("-", 1)[0]


def check_tasks(thread: Path, by: dict[str, str]) -> list[Finding]:
    emitted = tasks.sync(thread, by)
    if not emitted:
        return []
    return [("tasks-diff", (
        f"recorded {len(emitted)} change(s) made by editing tasks.yml by hand; nothing to do. "
        "Next time use `thread task`."
    ))]


def check_expired_claims(thread: Path, _: dict[str, str]) -> list[Finding]:
    cache = read_yaml(thread / "thread.yml", {})
    findings: list[Finding] = []
    threshold = events.now() - timedelta(hours=LIMITS["stale_claim_hours"])
    for claim in list(cache.get("claims", [])):
        if events.parse_time(claim["last-seen"]) <= threshold:
            session = claim["by"]["session"]
            unsynced = cache.get("events-since-checkpoint", 0)
            events.append(thread, "release", {
                "session": session, "expired": True, "unsynced-events": unsynced,
            }, DOCTOR, reopen=False)
            findings.append(("expired-claims", (
                f"released {session}'s claim after {LIMITS['stale_claim_hours']}+ hours with no events from them; "
                f"the thread has {unsynced} events since the last checkpoint. If {session}'s work matters, "
                f"read it with `thread replay {_id(thread)} --session {session}` and write a checkpoint."
            )))
    return findings


def check_unsynced(thread: Path, _: dict[str, str]) -> list[Finding]:
    count = read_yaml(thread / "thread.yml", {}).get("events-since-checkpoint", 0)
    if count > LIMITS["unsynced_nudge"]:
        return [("events-since-checkpoint", (
            f"{count} events since the last checkpoint. If the work has moved on, write a checkpoint "
            f"(`thread checkpoint {_id(thread)}` prints the template)."
        ))]
    return []


def check_inactive(thread: Path, _: dict[str, str]) -> list[Finding]:
    cache = read_yaml(thread / "thread.yml", {})
    if cache.get("state") != "active":
        return []
    # The doctor's own events (an expired release, say) are not activity, so
    # shelving looks at the last event somebody else wrote.
    authored = [event for event in events.read_events(thread) if event["by"]["session"] != "doctor"]
    if not authored:
        return []
    if events.parse_time(authored[-1]["ts"]) > events.now() - timedelta(days=LIMITS["inactive_days"]):
        return []
    events.append(thread, "state-changed", {
        "from": "active", "to": "inactive", "reason": f"no activity for {LIMITS['inactive_days']} days",
    }, DOCTOR, reopen=False)
    identifier = _id(thread)
    finish = f"`thread merge {identifier}`" if cache.get("parent") else f"`thread complete {identifier}`"
    return [("inactive", (
        f"marked inactive after {LIMITS['inactive_days']} days without activity. Writing anything to it "
        f"makes it active again. If it's finished, {finish}; if it isn't worth pursuing, "
        f"`thread drop {identifier}`."
    ))]


def _last_checkpoint_time(thread: Path) -> float:
    cache = read_yaml(thread / "thread.yml", {})
    checkpoint = cache.get("last-checkpoint")
    return events.parse_time(checkpoint["ts"]).timestamp() if checkpoint else 0


def check_scratch(thread: Path, _: dict[str, str]) -> list[Finding]:
    scratch = thread / "scratch"
    checkpoint_time = _last_checkpoint_time(thread)
    old_time = (events.now() - timedelta(days=LIMITS["old_scratch_days"])).timestamp()
    newer = [path for path in scratch.rglob("*") if path.is_file() and path.stat().st_mtime > checkpoint_time]
    old = [path for path in scratch.rglob("*") if path.is_file() and path.stat().st_mtime < old_time]
    result = []
    if newer:
        result.append(("scratch-newer", (
            f"{len(newer)} scratch files changed since the last checkpoint. Before the next checkpoint, "
            "move anything worth keeping into docs/ or artifacts/ and `thread register` it."
        )))
    if old:
        result.append(("old-scratch", (
            f"{len(old)} scratch files are older than {LIMITS['old_scratch_days']} days. Delete them, "
            "or move keepers into docs/ or artifacts/ and `thread register` them."
        )))
    return result


def check_unregistered(thread: Path, _: dict[str, str]) -> list[Finding]:
    # Pointers name another thread's file, so they register nothing here.
    registered = {
        event["payload"]["registration"]["path"]
        for event in events.read_events(thread)
        if event["type"] == "register" and not event["payload"].get("pointer")
    }
    directories = {
        relative for relative in registered
        if (thread / relative).is_dir()
    }
    files = {
        path.relative_to(thread).as_posix()
        for folder in (thread / "docs", thread / "artifacts")
        for path in folder.rglob("*") if path.is_file()
    }
    missing = sorted(
        path for path in files
        if path not in registered and not any(path.startswith(f"{directory}/") for directory in directories)
    )
    return [

        ("unregistered", (
            f"{path} isn't registered, so the view page doesn't list it. "
            f"`thread register {_id(thread)} {path} --kind <kind> --purpose \"...\"`"
            + (" --read-when \"...\"" if path.startswith("docs/") else "")
            + ", or delete it."
        ))
        for path in missing
    ]


def check_dangling_pointers(thread: Path, _: dict[str, str]) -> list[Finding]:
    """A pointer whose target thread folder is gone."""
    root = root_of(thread)
    result = []
    for event in events.read_events(thread):
        pointer = event["payload"].get("pointer") if event["type"] == "register" else None
        if not pointer:
            continue
        try:
            resolve_thread(root, pointer.split(":", 1)[0])
        except ThreadError:
            result.append(("dangling-pointer", (
                f"{pointer} points at a thread folder that no longer exists. Restore the folder from git "
                "history in the .spindle folder, or ignore this if it was deleted on purpose."
            )))
    return result


def check_dangling_links(thread: Path, _: dict[str, str]) -> list[Finding]:
    root = root_of(thread)
    identifier = _id(thread)
    result = []
    for link in read_yaml(thread / "thread.yml", {}).get("links", []):
        try:
            resolve_thread(root, link["target"])
        except ThreadError:
            result.append(("dangling-link", (
                f"{link['kind']} points to thread {link['target']}, whose folder no longer exists. "
                f"Restore it from git, or remove the link with "
                f"`thread unlink {identifier} {link['kind']} {link['target']}`."
            )))
    return result


def check_unarchived(thread: Path, _: dict[str, str]) -> list[Finding]:
    """Finished (any final state) but not archived; `thread archive` moves it."""
    state = read_yaml(thread / "thread.yml", {}).get("state")
    if is_final(state) and is_active(thread):
        return [("unarchived", f"{state} but not archived yet. `thread archive` moves it.")]
    return []


def check_orphan_promotions(thread: Path, _: dict[str, str]) -> list[Finding]:
    root = root_of(thread)
    result = []
    for task in tasks.read(thread):
        child = task.get("promoted")
        if child:
            try:
                resolve_thread(root, child)
            except ThreadError:
                result.append(("orphan-promotion", (
                    f"task {task['id']} was promoted to thread {child}, which no longer exists. "
                    f"`thread task close {_id(thread)} {task['id']}` if that work is done, "
                    f"or `thread task remove {_id(thread)} {task['id']}`."
                )))
    return result


CHEAP: tuple[Callable[[Path, dict[str, str]], list[Finding]], ...] = (
    check_tasks, check_expired_claims, check_unsynced,
)
FULL: tuple[Callable[[Path, dict[str, str]], list[Finding]], ...] = (
    *CHEAP, check_inactive, check_scratch, check_unregistered, check_orphan_promotions,
    check_dangling_pointers, check_dangling_links, check_unarchived,
)


def run(thread: Path, by: dict[str, str], *, full: bool = False) -> list[Finding]:
    findings: list[Finding] = []
    for check in FULL if full else CHEAP:
        findings.extend(check(thread, by))
    return findings


def render(grouped: list[tuple[Path, list[Finding]]]) -> str:
    lines = []
    for thread, findings in grouped:
        lines.append(f"## {thread.name}")
        if findings:
            lines.extend(f"- **{name}:** {detail}" for name, detail in findings)
        else:
            lines.append("- No problems found.")
    return "\n".join(lines) + ("\n" if lines else "")
