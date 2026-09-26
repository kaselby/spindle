"""A thread as readers see it: metadata (thread.yml) plus state (the log),
and the relationships found by scanning the store: subthreads (threads whose
thread.yml names this one as parent) and links pointing here.

Display scans skip a thread whose files can't be read and count it, so one bad
thread.yml never breaks a view, a list or the startup snapshot; doctor names it.
Gates (complete, drop, merge) use children_scan's second list and refuse
instead: a subthread that can't be read is unknown, not absent.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import events, metadata
from .store import ThreadError, is_final, iter_threads, namespace_of

# What a scan tolerates in one thread without failing the whole command.
UNREADABLE = (ThreadError, KeyError, ValueError, OSError)


def thread_id(thread: Path) -> str:
    return thread.name.split("-", 1)[0]


def describe(thread: Path, log: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """id, slug and namespace (from the folder), metadata, then state. Raises
    MetadataError if thread.yml doesn't validate."""
    identifier, _, slug = thread.name.partition("-")
    result: dict[str, Any] = {"id": identifier, "slug": slug}
    namespace = namespace_of(thread)
    if namespace:
        result["namespace"] = namespace
    result.update(metadata.read(thread))
    result.update(events.state(thread, log))
    return result


def _may_name(thread: Path, identifier: str) -> bool:
    """Could this unreadable thread be a subthread of ``identifier``? Only where
    a parent gets set counts, so a note, a checkpoint or a link that merely
    mentions the id doesn't: a thread.yml line with `parent` and the id, or in
    the log `"parent":"<id>"` (the `created` payload, and `migrated`'s copy of
    thread.yml) or `"to":"<id>"` (`reparented`). events.append writes compact
    JSON, so those bytes are stable. A thread.yml that's missing or can't be
    read falls through to the log test; a log that can't be read is unknown,
    so yes."""
    needle = re.escape(identifier.encode())
    try:
        if re.search(rb"parent[^\n]*" + needle, metadata.path_of(thread).read_bytes()):
            return True
    except OSError:
        pass
    try:
        log = (thread / "log.jsonl").read_bytes()
    except OSError:
        return True
    return re.search(rb'"(?:parent|to)":"' + needle + rb'"', log) is not None


def children_scan(root: Path, identifier: str) -> tuple[list[dict[str, Any]], list[str]]:
    """(subthreads, folder names of threads that couldn't be read and might be
    subthreads). Every thread (archived ones too) in this thread's namespace
    whose parent is this id, oldest first, each with its own title and state.

    A thread in another namespace is never a subthread, whatever its thread.yml
    says: it reads as top-level and doctor flags it. Display callers ignore the
    second list; gates refuse on it, because a thread that can't be read is an
    unknown, not a "no"."""
    threads = iter_threads(root)
    home = next((path for path in threads if thread_id(path) == identifier), None)
    rows, unknown = [], []
    for path in threads:
        if path == home:
            continue
        if home is not None and namespace_of(path) != namespace_of(home):
            continue
        try:
            parent = metadata.read(path).get("parent")
        except UNREADABLE:
            if _may_name(path, identifier):
                unknown.append(path.name)
            continue
        if parent != identifier:
            continue
        try:
            log = events.read_events(path)
            row = {
                "id": thread_id(path),
                "title": metadata.read(path)["title"],
                "state": events.lifecycle_state(log),
                "created": log[0]["ts"] if log else "",
            }
        except UNREADABLE:
            unknown.append(path.name)  # a known subthread whose state can't be read
            continue
        rows.append(row)
    rows.sort(key=lambda row: (row["created"], row["id"]))
    for row in rows:
        del row["created"]
    return rows, unknown


def children(root: Path, identifier: str) -> list[dict[str, Any]]:
    """Subthreads for display: threads that can't be read are skipped (doctor names them)."""
    return children_scan(root, identifier)[0]


def linked_from(root: Path, identifier: str) -> list[tuple[Path, dict[str, str]]]:
    """(other thread, its link) for every link elsewhere in the store that
    targets this id. Only link events are parsed, so this stays cheap."""
    found = []
    for other in iter_threads(root):
        if thread_id(other) == identifier:
            continue
        try:
            text = (other / "log.jsonl").read_text(encoding="utf-8")
        except (OSError, ValueError):  # not there, or not UTF-8: doctor names it
            continue
        if identifier not in text or '"linked"' not in text:
            continue  # nothing here can point at this thread
        try:
            log = events.read_events(other)
        except UNREADABLE:
            continue
        for link in events.links(log):
            if link["target"] == identifier:
                found.append((other, link))
    return found


def metadata_baseline(thread: Path, log: list[dict[str, Any]]) -> dict[str, Any] | None:
    """thread.yml as it was at the latest checkpoint, for the view's "what
    changed" line. The newest of: a checkpoint's `metadata` block, the
    `migrated` event, the `created` event. None when that checkpoint predates
    the block (nothing to compare against). A `reparented` event after it is
    the tool's own edit, logged, so the baseline takes that parent too."""
    baseline = _baseline_event(thread, log)
    if baseline is None:
        return None
    for event in reversed(log):
        if event["type"] in ("checkpoint", "migrated", "created"):
            break
        if event["type"] == "reparented":
            baseline["parent"] = event.get("payload", {}).get("to")
            break
    return baseline


def _baseline_event(thread: Path, log: list[dict[str, Any]]) -> dict[str, Any] | None:
    from .store import parse_frontmatter

    for event in reversed(log):
        kind, payload = event["type"], event.get("payload", {})
        if kind == "checkpoint":
            try:
                text = (thread / "checkpoints" / f"{payload['checkpoint']}.md").read_text(encoding="utf-8")
                front, _ = parse_frontmatter(text)
            except (OSError, ThreadError, KeyError, ValueError):
                return None
            block = front.get("metadata")
            return metadata.baseline_from(block) if isinstance(block, dict) else None
        if kind == "migrated":
            return metadata.baseline_from(payload.get("metadata") or {})
        if kind == "created":
            return metadata.baseline_from(payload)
    return None
