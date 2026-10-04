"""Human-readable orientation, replay, list, and generated index rendering."""

from __future__ import annotations

import json
from collections import Counter
from datetime import timedelta
from pathlib import Path

from typing import Any

from . import decisions, events, guide, metadata, summary, tasks, tree
from .limits import LIMITS
from .store import (
    FINAL_STATES, ThreadError, atomic_text, is_final, namespace_of, parse_frontmatter, resolve_thread,
    root_of,
)


def _age(value: str) -> str:
    delta = events.now() - events.parse_time(value)
    seconds = max(0, int(delta.total_seconds()))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


def _without_event_log(text: str) -> str:
    _, body = parse_frontmatter(text)
    lines = body.splitlines()
    start = next((i for i, line in enumerate(lines) if line.strip().lower() == "## event log"), None)
    if start is None:
        return body.strip()
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    return "\n".join(lines[:start] + lines[end:]).strip()


def registrations(thread: Path) -> list[tuple[dict[str, Any], str]]:
    """(register payload, date) pairs. The payload carries the registration
    plus the lineage fields `from` and `pointer`."""
    result = []
    for event in events.read_events(thread):
        if event["type"] == "register":
            result.append((event["payload"], event["ts"][:10]))
    return result


def _name(payload: dict[str, Any]) -> str:
    """How the index names an entry: a pointer shows the thread it lives in."""
    path = payload["registration"]["path"]
    pointer = payload.get("pointer")
    if not pointer:
        return f"**{path}**"
    return f"→ **{pointer.split('@', 1)[0]}**"


def _registration_target(thread: Path, payload: dict[str, Any]) -> Path | None:
    """The local path represented by a registration, including merge pointers."""
    item = payload["registration"]
    pointer = payload.get("pointer")
    if not pointer:
        return thread / item["path"]
    reference, separator, location = pointer.partition(":")
    if not separator:
        return None
    relative = location.rsplit("@", 1)[0]
    try:
        owner = resolve_thread(root_of(thread), reference)
    except ThreadError:
        return None

    return owner / relative


def _entry_details(thread: Path, payload: dict[str, Any], date: str, *, artifact: bool) -> str:
    details: list[str] = []
    target = _registration_target(thread, payload)
    if target is not None and target.is_dir():
        count = sum(1 for path in target.rglob("*") if path.is_file())
        details += ["directory", _plural(count, "file")]
    if artifact and not payload.get("pointer"):
        details.append(date)
    return ", ".join(details)


def _index_lines(thread: Path, *, artifact_limit: int | None, pointers: bool = True) -> list[str]:
    """The docs and artifacts sections. With ``pointers=False`` (the view page),
    entries that point into merged children collapse to one count line. A path
    registered again shows once, with its newest registration."""
    newest: dict[tuple[str, str | None], tuple[dict[str, Any], str]] = {}
    for item, date in registrations(thread):
        if item["registration"].get("kind") == "reading-guide":
            continue  # written before orientation.md replaced the registered reading guide
        key = (item["registration"]["path"], item.get("pointer", "").split("@", 1)[0] or None)
        newest.pop(key, None)  # re-insert so order follows the newest registration
        newest[key] = (item, date)
    rows = list(newest.values())
    carried = [item for item, _ in rows if item.get("pointer")]
    if not pointers:
        rows = [(item, date) for item, date in rows if not item.get("pointer")]
    artifacts = rows
    lines = []
    shown = artifacts if artifact_limit is None else artifacts[-artifact_limit:]
    if shown:
        for payload, date in reversed(shown):
            item = payload["registration"]
            details = _entry_details(thread, payload, date, artifact=True)
            lines.append(f"- {_name(payload)}{f' ({details})' if details else ''} — {item['purpose']}")
            if item.get("read-when"):
                lines.append(f"  *Read when:* {item['read-when']}")
        hidden = len(artifacts) - len(shown)
        if hidden:
            lines.append(f"- … {hidden} more; see `{thread / 'index.md'}`")
    else:
        lines.append("- None.")
    if carried and not pointers:
        counts = _plural(len(carried), "artifact")
        verb = "remains" if len(carried) == 1 else "remain"
        lines += ["", f"*{counts} {verb} in merged subthreads; `{thread / 'index.md'}` lists them.*"]
    return lines


def index_text(thread: Path) -> str:
    checkpoint = events.state(thread).get("last-checkpoint", {})
    lines = [
        f"# {metadata.title_or_name(thread)} — artifacts",
        f"<!-- generated at checkpoint {checkpoint.get('id', 'none')}, {events.timestamp()}; do not edit -->",
        "",
        *_index_lines(thread, artifact_limit=None),
    ]
    return "\n".join(lines) + "\n"


def write_index(thread: Path) -> None:
    atomic_text(thread / "index.md", index_text(thread))


def _state_header(cache: dict[str, Any], log: list[dict[str, Any]]) -> list[str]:
    """The line under the title that says how this thread ended."""
    state = cache["state"]
    identifier = cache["id"]
    if state == "active":
        return []
    changed = next(
        (event for event in reversed(log)
         if event["type"] == "state-changed" and event["payload"].get("to") == state), None
    )
    date = (changed["ts"] if changed else cache["last-event"])[:10]
    if state == "inactive":
        return [f"> **Inactive** since {date} (no activity for {LIMITS['inactive_days']} days). "
                "Writing anything to it makes it active again."]
    if state == "merged":
        merged = next((event for event in reversed(log) if event["type"] == "merged-into"), None)
        if merged:
            payload = merged["payload"]
            return [f"> **Merged** into {payload['parent']} on {date}, at its checkpoint {payload['checkpoint']}."]
        return [f"> **Merged** {date}."]
    if state == "dropped":
        return [f"> **Dropped** {date}: judged not worth pursuing. `thread reopen {identifier}` brings it back."]
    return [f"> **Completed** {date}. `thread reopen {identifier}` brings it back."]


def _arc(root: Path, log: list[dict[str, Any]], children: list[dict[str, Any]],
         *, deep: bool) -> list[str]:
    checkpoints = [event for event in log if event["type"] == "checkpoint"]
    current = checkpoints[-1]["id"] if checkpoints else None
    rows: list[tuple[str, str]] = []
    for event in log:
        if event["type"] == "checkpoint":
            suffix = " ← current" if event["id"] == current else ""
            rows.append((event["ts"], f"- {event['payload']['checkpoint']}: {event['payload']['headline']}{suffix}"))
    if deep:
        for child in children:
            try:
                path = resolve_thread(root, child["id"])
            except Exception:
                continue
            own = [event for event in events.read_events(path) if event["type"] == "checkpoint"]
            mark = f" ({child['state']})" if is_final(child.get("state")) else ""
            for index, event in enumerate(own):
                tail = mark if index == len(own) - 1 else ""
                rows.append((
                    event["ts"],
                    f"  ↳ {child['id']}: {event['payload']['checkpoint']} {event['payload']['headline']}{tail}",
                ))
    # Stable sort: a child checkpoint sharing a parent's timestamp lands after it.
    return [text for _, text in sorted(rows, key=lambda row: row[0])]


def _children_rows(
    children: list[dict[str, Any]], identifier: str, *, deep: bool, unreadable: int = 0,
) -> list[str]:
    rows = [
        f"- {child['id']} — {child['title']} ({child['state']})"
        for child in children if not is_final(child["state"])
    ]
    ended = [child for child in children if is_final(child["state"])]
    if deep:
        for child in ended:
            rows.append(f"- {child['id']} — {child['title']} ({child['state']}) — `thread view {child['id']}`")
    elif ended:
        counts = ", ".join(
            f"{sum(1 for child in ended if child['state'] == state)} {state}"
            for state in FINAL_STATES if any(child["state"] == state for child in ended)
        )
        rows.append(f"- {counts} — `thread view {identifier} --deep` lists them")
    if unreadable:
        rows.append(
            f"- {unreadable} thread{'s' if unreadable != 1 else ''} couldn't be read and "
            f"{'are' if unreadable != 1 else 'is'} left out (possibly subthreads); `thread doctor` says which."
        )
    return rows or ["- None."]


def _index_body(thread: Path) -> list[str]:
    """The capped artifacts summary embedded in the view page."""
    return _index_lines(thread, artifact_limit=LIMITS["artifact_index"], pointers=False)



def _plural(count: int, word: str) -> str:
    return f"{count} {word}{'' if count == 1 else 's'}"


def _event_count(kind: str, count: int) -> str:
    if kind == "register":
        return _plural(count, "registration")
    if kind == "task-added":
        return f"{_plural(count, 'task')} added"
    if kind == "task-closed":
        return f"{_plural(count, 'task')} closed"
    if kind == "task-edited":
        return f"{_plural(count, 'task')} edited"
    if kind == "task-removed":
        return f"{_plural(count, 'task')} removed"
    if kind == "note":
        return _plural(count, "note")
    return _plural(count, kind.replace("-", " "))


def _related_rows(root: Path, thread: Path, cache: dict[str, Any]) -> list[str]:
    rows = []
    if cache.get("parent"):
        try:
            parent_path = resolve_thread(root, cache["parent"])
        except ThreadError:
            rows.append(
                f"- Parent {cache['parent']} (not found: no thread has that id, so this one is shown "
                f"as top-level; `thread doctor {cache['id']}` says how to fix it)"
            )
        else:
            if namespace_of(parent_path) != namespace_of(thread):
                rows.append(
                    f"- Parent {cache['parent']} (in namespace {namespace_of(parent_path) or 'default'}, "
                    "and a subthread must share its parent's namespace, so this one is shown as top-level; "
                    f"`thread doctor {cache['id']}` says how to fix it)"
                )
            else:
                rows.append(f"- Parent {cache['parent']}: {metadata.title_or_name(parent_path)}")

    labels = {"related": "Related to", "blocked-by": "Blocked by", "continues": "Continues"}
    for link in cache.get("links", []):
        target_id = link["target"]
        try:
            target = resolve_thread(root, target_id)
        except ThreadError:
            rows.append(f"- {labels[link['kind']]} {target_id} (not found)")
            continue
        state = ""
        if link["kind"] != "related":
            try:
                state = f" ({events.lifecycle_state(events.read_events(target))})"
            except summary.UNREADABLE:
                state = " (state unknown: its log can't be read)"
        rows.append(f"- {labels[link['kind']]} {target_id}: {metadata.title_or_name(target)}{state}")

    reverse_labels = {
        "continues": "Continued by",
        "blocked-by": "Blocks",
        "related": "Related to",
    }
    for other, link in summary.linked_from(root, cache["id"]):
        suffix = " (linked from there)" if link["kind"] == "related" else ""
        rows.append(
            f"- {reverse_labels[link['kind']]} {summary.thread_id(other)}: "
            f"{metadata.title_or_name(other)}{suffix}"
        )
    return rows


def view(root: Path, thread: Path, *, deep: bool = False) -> str:

    log = events.read_events(thread)
    cache = summary.describe(thread, log)  # a bad thread.yml stops here, with how to fix it
    identifier = cache["id"]
    _origin_metadata, origin_body = parse_frontmatter((thread / "origin.md").read_text(encoding="utf-8"))
    origin_text = guide.strip_comments(origin_body).strip()

    # Presence.
    claims = cache.get("claims", [])
    presence = []
    claim_rows = []
    for claim in claims:
        seen = _age(claim["last-seen"])
        stale = events.now() - events.parse_time(claim["last-seen"]) >= timedelta(hours=LIMITS["stale_claim_hours"])
        doing = claim.get("intent") or "claimed"
        marker = f", nothing from them for {seen}" if stale else ""
        presence.append(f"{claim['by']['session']} ({doing}{marker})")
        claim_rows.append(f"- {claim['by']['session']}: {doing} (last event {seen} ago)")
    who = "; ".join(presence) if presence else "nobody has claimed it"

    # Events since the last checkpoint. The count, the note count and the
    # list below all come from the same events, so they add up.
    counted = events.counted_since_checkpoint(log)
    notes = [event for event in counted if event["type"] == "note"]
    listed = [event for event in counted if event["type"] != "note"]
    count_text = f"**{_plural(len(counted), 'event')} since the last checkpoint**"
    if notes:
        count_text += (
            f" ({_plural(len(notes), 'note')}, not listed on this page; "
            f"`thread replay {identifier} --type note`)"
        )
    count_text += "."
    scratch = cache.get("scratch-newer-than-checkpoint", 0)
    skipped = [
        event for event in counted
        if event["type"] == "release" and event["payload"].get("skipped-checkpoint")
    ]
    work_counts = Counter(
        event["type"] for event in counted
        if event["type"] not in {"created", "claim", "release"}
    )
    count_summary = ", ".join(_event_count(kind, count) for kind, count in work_counts.items())
    checkpoint_name = cache.get("last-checkpoint", {}).get("id")
    since = f"Since {checkpoint_name}" if checkpoint_name else "Since the thread began"


    title_block = [f"# {cache['title']}"]
    facts = [f"`{identifier}`", cache["state"], f"created {cache['created'][:10]}"]
    if cache.get("parent"):
        facts.append(f"subthread of {cache['parent']}")
    title_block.append(" · ".join(facts))
    if cache.get("namespace"):
        title_block.append(f"Namespace: {cache['namespace']}")
    if cache.get("flags"):
        # Shown as written in thread.yml: true, not Python's True.
        shown = (json.dumps(value) if value is None or isinstance(value, bool) else value for value in cache["flags"].values())
        title_block.append("Flags: " + ", ".join(f"{name}={value}" for name, value in zip(cache["flags"], shown)))
    title_block += [
        "*This page is the thread's orientation. Read the origin first; "
        "everything after it is measured against it.*", "",
    ]
    banner = [
        *_state_header(cache, log),
        f"> **Working here:** {who}. {guide.CLAIMS_DONT_LOCK}",
        f"> {count_text}"
        + (f" {_plural(scratch, 'scratch file')} changed since then." if scratch else ""),
        f"> **Latest event id:** {cache['tip']} (checkpoints may need it as `--at`)",
    ]
    # Hand edits to thread.yml aren't events; this diff is how they show.
    changed = metadata.changes(summary.metadata_baseline(thread, log), metadata.read(thread))
    if changed:
        banner.insert(-1, (
            f"> **thread.yml {'since the last checkpoint' if checkpoint_name else 'since the thread began'}:** "
            f"{changed}."
        ))
    for event in skipped:
        banner.append(
            f"> **Released without a checkpoint** by {event['by']['session']}: "
            f"\"{event['payload']['skipped-checkpoint']}\". {since}: {count_summary or 'no work events'}."
        )


    children, unreadable_children = summary.children_scan(root, identifier)
    arc = _arc(root, log, children, deep=deep)
    checkpoints = [event for event in log if event["type"] == "checkpoint"]
    if checkpoints:
        last = checkpoints[-1]
        name = last["payload"]["checkpoint"]
        current_heading = f"# Where it stands: checkpoint {name} ({last['ts'][:10]}, by {last['by']['session']})"
        checkpoint_path = thread / "checkpoints" / f"{name}.md"
        current = [_without_event_log(checkpoint_path.read_text(encoding="utf-8"))]
    else:
        current_heading = "# Where it stands"
        current = [f"No checkpoint yet. `thread checkpoint {identifier}` prints the template."]

    shown = listed[-LIMITS["recent_events"] :]
    happened = [
        f"- {event['id']} {event['type']} by {event['by']['session']}: {events.event_summary(event)}"
        for event in shown
    ] or ["- None."]
    hidden = len(listed) - len(shown)
    if hidden:
        happened.insert(0, f"- … {hidden} earlier; `thread replay {identifier}` shows them all")
    if len(counted) > LIMITS["unsynced_nudge"]:
        happened += ["", (
            f"**{len(counted)} events since the last checkpoint.** If the work has moved on, write a "
            f"checkpoint (`thread checkpoint {identifier}` prints the template)."
        )]
    since_note = "*Oldest first. Notes are counted above but not listed.*" if notes else "*Oldest first.*"

    board = tasks.read(thread)
    task_rows = []
    for task in board:
        if task.get("done"):
            continue
        promoted = f" → now subthread {task['promoted']}" if task.get("promoted") else ""
        task_rows.append(f"- {task['id']}: {task['text']}{promoted}")
    if not task_rows:
        task_rows = ["- None."]

    around = _related_rows(root, thread, cache)
    orientation_path = thread / guide.ORIENTATION
    if orientation_path.is_file():
        # errors="replace": a stray non-UTF-8 byte shows as U+FFFD instead of failing the view.
        text = orientation_path.read_text(encoding="utf-8", errors="replace")
        reading = ["# Orientation", guide.strip_comments(text).strip(), ""]
    else:
        reading = []
    return "\n".join([
        *title_block, *banner, "",
        "# Origin: why this exists", origin_text, "",
        "# How it got here",
        *([f"*One line per checkpoint, oldest first; the last is the current one. "
            f"`thread replay {identifier} --checkpoint cNNNN` shows any of them in full.*"] if arc else []),
        *(arc or ["- No checkpoints yet."]), "",
        current_heading, *current, "",
        "# Since the last checkpoint", since_note, *happened, "",
        "# Subthreads", *_children_rows(children, identifier, deep=deep, unreadable=len(unreadable_children)), "",
        "# Who's working", *(claim_rows or ["- Nobody."]), "",
        "# Open tasks", *task_rows, "",
        *decisions.view_line(thread),
        *reading,
        "# Artifacts", *_index_body(thread), "",
        "# Related threads", *(around or ["- None."]),
    ]).replace("\n\n\n", "\n\n") + "\n"


def replay(
    thread: Path,
    *,
    all_events: bool = False,
    kind: str | None = None,
    session: str | None = None,
) -> str:
    log = events.read_events(thread)
    if not all_events:
        log = events.since_checkpoint(log)
    if kind:
        log = [event for event in log if event["type"] == kind]
    if session:
        log = [event for event in log if event["by"]["session"] == session]
    if not log:
        filters = [f"type {kind}" if kind else "", f"session {session}" if session else ""]
        what = " and ".join(item for item in filters if item)
        what = f" matching {what}" if what else ""
        if all_events:
            return f"No events{what} in this thread.\n"
        return f"No events{what} since the last checkpoint. `--all` shows the whole history.\n"
    return "\n".join(
        f"{event['id']} {event['ts']} {event['type']} by {event['by']['session']}: "
        f"{events.event_summary(event, full_note=True)}"
        for event in log
    ) + "\n"


def list_threads(root: Path, paths: list[Path], *, only: str | None = None, flags: list[str] | None = None) -> str:
    """Every thread as a tree, grouped by namespace (default first), with a single
    footer. Subthreads are indented under their parent (see tree.py); one line per
    thread with its state, who's working, and events since checkpoint. ``only`` is
    the namespace `--ns` filtered to, if any; ``flags`` the `--flag` filters.

    With no namespaced threads there is one group and no heading, as before
    namespaces existed; otherwise every group, the default included, gets one.
    """
    if not paths:
        if flags:
            where = f" in namespace {only}" if only is not None else ""
            return f"No active threads{where} with {', '.join(flags)}. `thread list` shows every active thread.\n"
        if only is not None:
            return f"No active threads in namespace {only}. `thread list` shows every namespace.\n"
        return "No active threads. `thread create \"title\"` prints the origin template to start one.\n"
    caches: list[dict] = []
    seen: dict[str, str] = {}
    unreadable = 0
    for path in paths:
        try:
            log = events.read_events(path)
            cache = summary.describe(path, log)
        except summary.UNREADABLE:
            unreadable += 1
            continue
        caches.append(cache)
        seen[cache["id"]] = tree.last_activity(log, cache)

    def line(row: tree.Row) -> str:
        cache = row.cache
        claims = ", ".join(claim["by"]["session"] for claim in cache.get("claims", []))
        count = cache["events-since-checkpoint"]
        blocked = []
        for link in cache.get("links", []):
            if link["kind"] != "blocked-by":
                continue
            try:
                target = resolve_thread(root, link["target"])
                if not is_final(events.lifecycle_state(events.read_events(target))):
                    blocked.append(link["target"])
            except summary.UNREADABLE:
                continue
        extra = f" · blocked by {', '.join(blocked)}" if blocked else ""
        if row.orphan:
            extra += f" · subthread of {cache['parent']}"
        return (
            f"{'  ' * row.depth}{cache['id']} ({cache['state']}) {cache['title']} · "
            f"{'claimed by ' + claims if claims else 'no claims'} · "
            f"{_plural(count, 'event')} since checkpoint{extra}"
        )

    groups = {name: [line(row) for row in rows] for name, rows in tree.arrange(caches, seen).items()}
    headed = only is not None or any(groups)
    lines: list[str] = []
    for name in sorted(groups, key=lambda key: (key != "", key)):
        if headed:
            if lines:
                lines.append("")
            lines.append(f"# Namespace: {name or 'default'}")
        lines.extend(groups[name])
    footer = f"Subthreads are indented under their parent. {guide.CLAIMS_DONT_LOCK} `thread view <id>` shows a thread."
    if unreadable:
        footer = (
            f"{unreadable} thread{'s' if unreadable != 1 else ''} couldn't be read and "
            f"{'are' if unreadable != 1 else 'is'} left out; `thread doctor` says which. " + footer
        )
    if len(groups) > 1:
        footer += " `thread list --ns <name>` shows one namespace."
    lines += ["", footer]
    return "\n".join(lines) + "\n"


def checkpoint_records(thread: Path) -> list[dict[str, Any]]:
    """Every checkpoint as written, oldest first: its frontmatter plus its body."""
    records = []
    for path in sorted((thread / "checkpoints").glob("c*.md")):
        metadata, text = parse_frontmatter(path.read_text(encoding="utf-8"))
        records.append({**metadata, "id": metadata.get("id", path.stem), "body": text.strip()})
    return records


def checkpoints_text(thread: Path, only: str | None = None) -> str:
    """Past checkpoints in full, for reading history (`replay --checkpoint(s)`)."""
    records = checkpoint_records(thread)
    identifier = thread.name.split("-", 1)[0]
    if not records:
        return f"{identifier} has no checkpoints yet.\n"
    if only is not None:
        chosen = [record for record in records if record["id"] == only]
        if not chosen:
            known = ", ".join(record["id"] for record in records)
            raise ThreadError(
                f"{identifier} has no checkpoint {only}. It has: {known}. "
                f"`thread replay {identifier} --checkpoints` shows them all."
            )
        records = chosen
    blocks = []
    for record in records:
        by = record.get("by") or {}
        who = by.get("session", "?") if isinstance(by, dict) else by
        date = str(record.get("ts", ""))[:10]
        blocks.append(f"# Checkpoint {record['id']} ({date}, by {who})\n\n{record['body']}\n")
    return "\n---\n\n".join(blocks)
