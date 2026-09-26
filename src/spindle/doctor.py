"""Named, idempotent maintenance checks."""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path
from typing import Callable

from . import events, guide, metadata, tasks
from .limits import LIMITS
from .store import resolve_thread, root_of, namespace_of, ThreadError, is_active, is_final

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
    cache = events.state(thread)
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
    count = events.state(thread)["events-since-checkpoint"]
    if count > LIMITS["unsynced_nudge"]:
        return [("events-since-checkpoint", (
            f"{count} events since the last checkpoint. If the work has moved on, write a checkpoint "
            f"(`thread checkpoint {_id(thread)}` prints the template)."
        ))]
    return []


def check_inactive(thread: Path, _: dict[str, str]) -> list[Finding]:
    log = events.read_events(thread)
    if events.lifecycle_state(log) != "active":
        return []
    # The doctor's own events (an expired release, say) and the migration's
    # baseline are not activity, so shelving looks at the last event somebody
    # else wrote.
    authored = [event for event in log if events.is_activity(event)]
    if not authored:
        return []
    if events.parse_time(authored[-1]["ts"]) > events.now() - timedelta(days=LIMITS["inactive_days"]):
        return []
    events.append(thread, "state-changed", {
        "from": "active", "to": "inactive", "reason": f"no activity for {LIMITS['inactive_days']} days",
    }, DOCTOR, reopen=False)
    identifier = _id(thread)
    try:
        has_parent = bool(metadata.read(thread).get("parent"))
    except ThreadError:
        has_parent = False
    finish = f"`thread merge {identifier}`" if has_parent else f"`thread complete {identifier}`"
    return [("inactive", (
        f"marked inactive after {LIMITS['inactive_days']} days without activity. Writing anything to it "
        f"makes it active again. If it's finished, {finish}; if it isn't worth pursuing, "
        f"`thread drop {identifier}`."
    ))]


def _last_checkpoint_time(thread: Path) -> float:
    checkpoint = events.state(thread).get("last-checkpoint")
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
            f"`thread register {_id(thread)} {path} --kind {'doc' if path.startswith('docs/') else 'artifact'} "
            f"--purpose \"...\"`"
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
    for link in events.links(events.read_events(thread)):
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
    state = events.lifecycle_state(events.read_events(thread))
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


def check_metadata(thread: Path, _: dict[str, str]) -> list[Finding]:
    """thread.yml validates (that rejects a thread naming itself as parent),
    and its parent exists, is in the same namespace, and doesn't lead back
    here. The parent problems are findings, not read errors: the thread reads
    as top-level meanwhile."""
    try:
        value = metadata.read(thread)
    except ThreadError as error:
        return [("metadata", str(error))]
    parent = value.get("parent")
    if not parent:
        return []
    root = root_of(thread)
    try:
        found = resolve_thread(root, parent)
    except ThreadError:
        return [("dangling-parent", (
            f"thread.yml names parent {parent}, but no thread has that id, so this thread is shown "
            f"as top-level. Fix `parent:` in {metadata.path_of(thread)} (or remove it), or restore "
            "the parent's folder from git."
        ))]
    if namespace_of(found) != namespace_of(thread):
        return [("cross-namespace-parent", (
            f"thread.yml names parent {parent}, which is in namespace {namespace_of(found) or 'default'}, "
            f"not {namespace_of(thread) or 'default'}. A subthread lives in its parent's namespace, so this "
            f"thread is shown as top-level. Fix `parent:` in {metadata.path_of(thread)} (or remove it)."
        ))]
    cycle = _parent_cycle(root, thread)
    if cycle:
        return [("parent-cycle", (
            f"following parents from here comes back here ({' → '.join(cycle)}), so none of these "
            f"threads has a top. Remove or fix `parent:` in one of their thread.yml files."
        ))]
    return []


def _parent_cycle(root: Path, thread: Path, limit: int = 100) -> list[str]:
    """The ids from this thread back to itself if its parents loop, else []."""
    start = _id(thread)
    chain = [start]
    current = thread
    for _ in range(limit):
        try:
            parent = metadata.read(current).get("parent")
            if not parent:
                return []
            current = resolve_thread(root, parent)
        except ThreadError:
            return []  # a broken link further up is that thread's own finding
        identifier = _id(current)
        chain.append(identifier)
        if identifier == start:
            return chain
        if identifier in chain[:-1]:
            return []  # a loop further up that doesn't include this thread
    return []


# Local paths in a reading guide: absolute, home, relative, this thread's
# docs/ and artifacts/, or another thread's `<id>:docs/...`. URLs are removed
# first; branch names and the like don't match (no leading marker).
_URL = re.compile(r"[a-z][a-z0-9+.-]*://\S+", re.I)
_PATH = re.compile(
    r"(?<![\w/.~:-])"
    r"(?:~/|\.\./|\./|/(?=[^\s/])|docs/|artifacts/|[a-z0-9]{6,12}:(?:docs|artifacts)/)"
    r"[^\s`'\"()<>\[\]{}|*]*"
)


def guide_paths(text: str) -> list[str]:
    """The local path tokens doctor checks in a reading guide, in order."""
    text = _URL.sub(" ", text)
    found = []
    for match in _PATH.finditer(text):
        token = match.group(0).rstrip(".,;:!?")
        if token and token not in found:
            found.append(token)
    return found


def _resolve_guide_path(thread: Path, token: str) -> Path | None:
    """Where a token points, or None if it names a thread that doesn't exist."""
    if token.startswith("~/"):
        return Path(token).expanduser()
    if token.startswith("/"):
        return Path(token)
    head, colon, rest = token.partition(":")
    if colon and re.fullmatch(r"[a-z0-9]{6,12}", head):
        try:
            return resolve_thread(root_of(thread), head) / rest
        except ThreadError:
            return None
    return thread / token


def check_reading_guide(thread: Path, _: dict[str, str]) -> list[Finding]:
    path = thread / guide.READING_GUIDE
    if not path.is_file():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    result = []
    size = len(guide.strip_comments(text).strip())
    cap = LIMITS["reading_guide_chars"]
    if size > cap:
        result.append(("reading-guide-too-long", (
            f"**reading-guide.md is {size:,} characters, over the {cap:,} cap.** That is usually "
            "status or next steps creeping in. Move those to the checkpoint and keep only pointers "
            "and the order to read them in."
        )))
    for token in guide_paths(guide.strip_comments(text)):
        target = _resolve_guide_path(thread, token)
        if target is None or not target.exists():
            result.append(("reading-guide-dead-path", (
                f"reading-guide.md points at {token}, which doesn't exist. Fix the path or remove the line."
            )))
    return result


CHEAP: tuple[Callable[[Path, dict[str, str]], list[Finding]], ...] = (
    check_tasks, check_expired_claims, check_unsynced,
)
FULL: tuple[Callable[[Path, dict[str, str]], list[Finding]], ...] = (
    *CHEAP, check_metadata, check_inactive, check_scratch, check_unregistered, check_orphan_promotions,
    check_dangling_pointers, check_dangling_links, check_unarchived, check_reading_guide,
)


def run(thread: Path, by: dict[str, str], *, full: bool = False) -> list[Finding]:
    findings: list[Finding] = []
    for check in FULL if full else CHEAP:
        findings.extend(check(thread, by))
    return findings


def run_safely(thread: Path, by: dict[str, str]) -> list[Finding]:
    """The full pass for `thread doctor`: a thread that can't be read becomes a
    finding, so one damaged thread doesn't stop the report on the rest."""
    try:
        return run(thread, by, full=True)
    except (ThreadError, KeyError, ValueError, OSError) as error:
        detail = str(error) if isinstance(error, ThreadError) else f"{type(error).__name__}: {error}"
        return [("unreadable", detail)]


def render(grouped: list[tuple[Path, list[Finding]]]) -> str:
    lines = []
    for thread, findings in grouped:
        lines.append(f"## {thread.name}")
        if findings:
            lines.extend(f"- **{name}:** {detail}" for name, detail in findings)
        else:
            lines.append("- No problems found.")
    return "\n".join(lines) + ("\n" if lines else "")
