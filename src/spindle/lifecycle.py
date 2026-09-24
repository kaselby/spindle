"""Lifecycle verbs: merge, complete, drop, reopen, revise, reanchor, archive.

Every lifecycle verb here is one git commit. Merge is the only
one that writes files before events, so it is the only one with a rollback,
and that rollback covers copied files only: events already appended stay.
So every check that can refuse runs before the first write (gates, body
validation, promote paths, task ids). After the first write, only a disk or
git failure, or another session appending in that moment (nothing locks the
thread), can interrupt; both are known v1 gaps, recovered by hand.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

from . import checkpoint, events, gitops, guide, render, store, tasks
from .store import (
    thread_home, namespace_of, is_active, is_final, iter_threads,
    NeedsInput, ThreadError, atomic_text, markdown, parse_frontmatter, read_yaml, resolve_thread,
)

# One exit code per gate, so a caller can tell refusals apart. 2 (refusal),
# 3 (release) and 4 (CAS) belong to phase 1.
NO_PARENT = 10
BAD_STATE = 11
PARENT_BAD_STATE = 12
DIRTY = 13
PARENT_DIRTY = 14
OPEN_CHILDREN = 15
NOT_REGISTERED = 16
CONFLICT = 17
UNKNOWN_TASK = 18
HAS_PARENT = 19


def thread_id(thread: Path) -> str:
    return thread.name.split("-", 1)[0]


def _cache(thread: Path) -> dict[str, Any]:
    return read_yaml(thread / "thread.yml", {})


def _state_advice(thread: Path) -> str:
    return f"`thread reopen {thread_id(thread)}` brings it back first."


def _require_state(thread: Path, code: int, *, verb: str) -> str:
    state = _cache(thread).get("state", "active")
    if is_final(state):
        raise ThreadError(
            f"{thread_id(thread)} is {state}, so it can't be {verb}. {_state_advice(thread)}", code=code
        )
    return state


def _require_clean(thread: Path, code: int, *, verb: str, role: str = "") -> str:
    """The latest checkpoint must cover every counted event. Returns its id.

    ``role`` names the side ("the child", "the parent") for merge."""
    cache = _cache(thread)
    identifier = thread_id(thread)
    checkpoint_id = cache.get("last-checkpoint", {}).get("id")
    count = sum(1 for event in events.since_checkpoint(events.read_events(thread))
                if events.carries_work(event))
    if count or not checkpoint_id:
        who = f"{role}, {identifier}," if role else identifier
        has = (
            f"has {count} event{'' if count == 1 else 's'} since its last checkpoint"
            if checkpoint_id else "has no checkpoint yet"
        )
        finishing = (
            f" For what a final checkpoint should say, "
            f"{guide.doc('merging.md' if verb == 'merge' else 'lifecycle.md')}."
            if verb in ("merge", "complete", "drop") else ""
        )
        raise ThreadError(
            f"can't {verb} yet: {who} {has}; write one first "
            f"(`thread checkpoint {identifier}` prints the template).{finishing}", code=code,
        )
    return checkpoint_id


def _headline(thread: Path) -> str:
    return _cache(thread).get("last-checkpoint", {}).get("headline", thread.name)


def _open_children(thread: Path) -> list[dict[str, Any]]:
    return [child for child in _cache(thread).get("children", []) if not is_final(child["state"])]


def _parent_of(root: Path, thread: Path) -> Path | None:
    """The one place that maps a thread to its parent (merge stays parent-only,
    but nothing below hard-codes the lookup)."""
    parent = _cache(thread).get("parent")
    return resolve_thread(root, parent) if parent else None


def _copy(source: Path, destination: Path) -> None:
    """APFS clone when the filesystem offers it, a plain copy otherwise."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    flags = ["-c", "-R"] if source.is_dir() else ["-c"]
    clone = subprocess.run(
        ["cp", *flags, str(source), str(destination)],
        check=False, text=True, capture_output=True,
    )
    if clone.returncode == 0:
        return
    if source.is_dir():
        shutil.copytree(source, destination)
    else:
        shutil.copy2(source, destination)


def _undo_copies(copied: list[Path]) -> None:
    for path in reversed(copied):
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
        # Subdirectories the copy created are now empty; docs/ and artifacts/
        # themselves belong to the thread layout, so stop there.
        parent = path.parent
        while parent.name not in ("docs", "artifacts") and parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            parent = parent.parent


def _to_archive(root: Path, thread: Path, moment: str) -> Path:
    """Move a thread into threads/archived/YYYY-MM/ by the month of the closing event."""
    destination = thread_home(root, thread.name, namespace_of(thread), month=moment[:7])
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(thread), str(destination))
    return destination


def _reparent(root: Path, child_id: str, old: Path, new: Path, by: dict[str, str]) -> None:
    """Two events, `reparented` on the child and `child-adopted` on the new parent; no folder moves."""
    moved = resolve_thread(root, child_id)
    title = _cache(moved).get("title", child_id)
    events.append(moved, "reparented", {"from": thread_id(old), "to": thread_id(new)}, by)
    events.append(new, "child-adopted", {
        "child": child_id, "title": title, "from": thread_id(old),
    }, by)


def _register(parent: Path, registration: dict[str, Any], by: dict[str, str], **extra: str) -> None:
    payload: dict[str, Any] = {
        "registration": dict(registration),
        "checkpoint": _cache(parent).get("last-checkpoint", {}).get("id", "pending"),
    }
    payload.update(extra)
    events.append(parent, "register", payload, by)


def _registered(thread: Path) -> dict[str, dict[str, Any]]:
    """Registered docs/artifacts held in this thread, newest registration wins.
    Pointers are other threads' files, so they are not promotable."""
    found: dict[str, dict[str, Any]] = {}
    for payload, _ in render.registrations(thread):
        if payload.get("pointer"):
            continue
        found[payload["registration"]["path"]] = payload["registration"]
    return found


def _merge_command(child_id: str, promote: list[str], task_ids: list[str] | None,
                   all_tasks: bool, force: bool) -> str:
    """The merge command to rerun with --body, keeping the flags already given."""
    parts = [f"thread merge {child_id} --body <file>"]
    if promote:
        parts.append("--promote " + " ".join(promote))
    if all_tasks:
        parts.append("--all-tasks")
    elif task_ids:
        parts.append("--tasks " + " ".join(task_ids))
    if force:
        parts.append("--force")
    return " ".join(parts)


def merge(
    root: Path,
    child: Path,
    by: dict[str, str],
    *,
    promote: list[str] | None = None,
    task_ids: list[str] | None = None,
    all_tasks: bool = False,
    force: bool = False,
    body: Path | None = None,
) -> dict[str, Any]:
    promote = list(promote or [])
    child_id = thread_id(child)

    parent = _parent_of(root, child)
    if parent is None:
        raise ThreadError(
            f"{child_id} has no parent thread, so there is nothing to merge it into. To finish it, "
            f"use `thread complete {child_id}`, or `thread drop {child_id}` if it isn't worth pursuing "
            f"({guide.doc('lifecycle.md')}).", code=NO_PARENT,
        )
    parent_id = thread_id(parent)
    _require_state(child, BAD_STATE, verb="merged")
    if is_final(_cache(parent).get("state", "active")):
        raise ThreadError(
            f"can't merge {child_id}: its parent {parent_id} is {_cache(parent)['state']}. "
            f"{_state_advice(parent)}", code=PARENT_BAD_STATE,
        )
    child_cid = _require_clean(child, DIRTY, verb="merge", role="the child")
    parent_cid = _require_clean(parent, PARENT_DIRTY, verb="merge", role="the parent")

    grandchildren = _open_children(child)
    if grandchildren and not force:
        names = ", ".join(item["id"] for item in grandchildren)
        raise ThreadError(
            f"{child_id} has unfinished subthreads ({names}). Merge or drop them first, or pass --force "
            f"to move them under {parent_id}.",
            code=OPEN_CHILDREN,
        )

    registered = _registered(child)
    wanted: list[str] = []
    for value in promote:
        relative = PurePosixPath(value).as_posix()
        if relative not in registered:
            known = ", ".join(sorted(registered)[:10]) or "none"
            raise ThreadError(
                f"--promote takes docs or artifacts registered in {child_id}, and {relative} isn't one. "
                f"Registered: {known}. (`thread register {child_id} <path> ...` registers a file.)",
                code=NOT_REGISTERED,
            )
        if relative not in wanted:
            wanted.append(relative)
    taken = set(_registered(parent))
    conflicts = [
        relative for relative in wanted
        if relative in taken or parent.joinpath(*relative.split("/")).exists()
    ]
    if conflicts:
        raise ThreadError(
            f"{parent_id} already has {', '.join(conflicts)}, so --promote can't copy it there. "
            f"Leave it out of --promote; the parent will link to {child_id}'s copy instead.", code=CONFLICT,
        )

    board = tasks.read(child)
    if all_tasks:
        rolling = [task for task in board if not task.get("done")]
    else:
        rolling = []
        for task_id in task_ids or []:
            task = next((item for item in board if item.get("id") == task_id), None)
            if task is None:
                raise ThreadError(
                    f"no task {task_id} in {child_id}. `thread task list {child_id} --all` shows its task ids.",
                    code=UNKNOWN_TASK,
                )
            rolling.append(task)

    pointers = [relative for relative in registered if relative not in wanted]
    rolling_ids = {task.get("id") for task in rolling}
    left_tasks = sum(1 for task in board if not task.get("done") and task.get("id") not in rolling_ids)
    left_docs = sum(1 for relative in pointers if relative.startswith("docs/"))

    def facts(moved: list[tuple[str, str | None]]) -> str:
        return guide.merge_facts(
            child_id, parent_id, child_cid, _headline(child), wanted, moved,
            left_docs, len(pointers) - left_docs, left_tasks,
        )

    if body is None:
        current = parent / "checkpoints" / f"{parent_cid}.md"
        inherited = parse_frontmatter(current.read_text(encoding="utf-8"))[0].get("inherited") or []
        raise NeedsInput(guide.merge_template(
            child_id, parent_id, parent_cid,
            _merge_command(child_id, promote, task_ids, all_tasks, force),
            _headline(child), facts([(task["text"], None) for task in rolling]),
            [item["text"] if isinstance(item, dict) else str(item) for item in inherited],
        ))
    body_text = body.read_text(encoding="utf-8")
    headline = checkpoint.parse_merge_body(body_text, child_id)["headline"]
    # The parent's merge checkpoint id is the next ordinal, known before we write it.
    parent_next = checkpoint.next_id(parent)

    copied: list[Path] = []
    try:
        for relative in wanted:
            destination = parent.joinpath(*relative.split("/"))
            _copy(child.joinpath(*relative.split("/")), destination)
            copied.append(destination)
        for relative in wanted:
            _register(parent, registered[relative], by, **{"from": f"{child_id}@{child_cid}"})
        for relative in pointers:
            _register(parent, registered[relative], by, pointer=f"{child_id}:{relative}@{child_cid}")
        rolled = [tasks.add(parent, task["text"], by, from_thread=child_id)["id"] for task in rolling]
        for task in tasks.read(parent):
            if task.get("promoted") == child_id and not task.get("done"):
                tasks.close(parent, task["id"], by)
        for grandchild in grandchildren:
            _reparent(root, grandchild["id"], child, parent, by)

        events.append(child, "merged-into", {"parent": parent_id, "checkpoint": parent_next}, by)
        closing = events.append(child, "state-changed", {
            "from": _cache(child).get("state", "active"), "to": "merged",
        }, by, reopen=False)

        events.append(parent, "child-merged", {
            "child": child_id, "checkpoint": child_cid, "promoted": wanted,
            "pointers": pointers, "tasks": rolled, "forced": bool(grandchildren),
        }, by)
        block = facts([(task["text"], new_id) for task, new_id in zip(rolling, rolled)])
        written, _ = checkpoint.create(
            root, parent, None, by, at=None, forced_by="merge", body_text=body_text, commit=False,
            merged=(child_id, block),
            # The clean gate above proved the parent has no unread work, and the
            # CAS here would run after this merge's own events: skip it.
            skip_cas=True,
        )
    except Exception:
        _undo_copies(copied)
        raise

    archived = _to_archive(root, child, closing["ts"])
    render.write_index(archived)
    touched = [child, archived, parent]
    touched.extend(resolve_thread(root, grandchild["id"]) for grandchild in grandchildren)
    sha = gitops.commit(
        root, f"merge {child_id}@{child_cid} into {parent_id}@{written}: {headline}", touched,
    )
    return {

        "child": child_id, "parent": parent_id, "checkpoint": written,
        "child-checkpoint": child_cid, "parent-previous": parent_cid,
        "promoted": wanted, "pointers": pointers, "tasks": rolled,
        "forced": bool(grandchildren), "archived": str(archived), "commit": sha,
    }


def _finish(
    root: Path, thread: Path, by: dict[str, str], *, to: str, verb: str, force: bool,
) -> dict[str, Any]:
    """complete and drop: the same gates and moves, a different final state."""
    identifier = thread_id(thread)
    past = {"complete": "completed", "drop": "dropped"}[verb]
    _require_state(thread, BAD_STATE, verb=past)
    parent = _parent_of(root, thread)
    if verb == "complete" and parent is not None:
        # A finished subthread's result reaches its parent only through merge;
        # completing it in place would strand the result.
        raise ThreadError(
            f"{identifier} is a subthread of {thread_id(parent)}, so it finishes by merging: "
            f"`thread merge {identifier}` carries its result into {thread_id(parent)} "
            f"({guide.doc('merging.md')}). If it isn't worth pursuing, `thread drop {identifier}`.",
            code=HAS_PARENT,
        )
    checkpoint_id = _require_clean(thread, DIRTY, verb=verb)

    children = _open_children(thread)
    if children:
        names = ", ".join(item["id"] for item in children)
        if parent is None:
            raise ThreadError(
                f"{identifier} has unfinished subthreads ({names}) and no parent to move them to. "
                "Merge or drop them first.",
                code=OPEN_CHILDREN,
            )
        if not force:
            raise ThreadError(
                f"{identifier} has unfinished subthreads ({names}). Merge or drop them first, or pass "
                f"--force to move them under {thread_id(parent)}.",
                code=OPEN_CHILDREN,
            )
        for child in children:
            _reparent(root, child["id"], thread, parent, by)

    ending = events.append(thread, "state-changed", {
        "from": _cache(thread).get("state", "active"), "to": to,
    }, by, reopen=False)
    if parent is not None:
        # Only drop reaches here with a parent: complete refused above.
        events.append(parent, "child-dropped", {
            "child": identifier, "checkpoint": checkpoint_id,
        }, by)
    archived = _to_archive(root, thread, ending["ts"])
    touched = [thread, archived]
    if parent is not None:
        touched.append(parent)
    touched.extend(resolve_thread(root, child["id"]) for child in children)
    sha = gitops.commit(
        root, f"{verb} {identifier}@{checkpoint_id}: {_headline(archived)}", touched,
    )
    return {

        "thread": identifier, "state": to, "checkpoint": checkpoint_id, "archived": str(archived),
        "reparented": [child["id"] for child in children], "commit": sha,
    }


def complete(root: Path, thread: Path, by: dict[str, str]) -> dict[str, Any]:
    """The work is done. Top-level threads only: a subthread merges instead.
    No --force: with no parent there is nowhere to move open subthreads."""
    return _finish(root, thread, by, to="completed", verb="complete", force=False)


def drop(root: Path, thread: Path, by: dict[str, str], *, force: bool = False) -> dict[str, Any]:
    """Not worth pursuing. Any thread, subthreads included."""
    return _finish(root, thread, by, to="dropped", verb="drop", force=force)


def reopen(root: Path, thread: Path, by: dict[str, str]) -> dict[str, Any]:
    identifier = thread_id(thread)
    cache = _cache(thread)
    state = cache.get("state", "active")
    if state == "inactive":
        raise ThreadError(
            f"{identifier} is inactive, not finished. It becomes active again on its own the next time "
            "anything is written to it (a claim, a note, a checkpoint).", code=BAD_STATE,
        )
    # A merged thread can be reopened too.
    if state not in ("completed", "dropped", "merged"):
        raise ThreadError(
            f"{identifier} is already {state}; nothing to reopen. `thread view {identifier}` shows where it stands.",
            code=BAD_STATE,
        )
    checkpoint_id = cache.get("last-checkpoint", {}).get("id", "none")

    events.append(thread, "reopened", {}, by, reopen=False)
    events.append(thread, "state-changed", {
        "from": state, "to": "active", "reason": "reopened",
    }, by, reopen=False)
    destination = thread_home(root, thread.name, namespace_of(thread))
    shutil.move(str(thread), str(destination))
    parent = _parent_of(root, destination)
    if parent is not None:
        events.append(parent, "child-reopened", {"child": identifier}, by)
    touched = [thread, destination]
    if parent is not None:
        touched.append(parent)
    sha = gitops.commit(
        root, f"reopen {identifier}@{checkpoint_id}: {_headline(destination)}", touched,
    )
    return {"thread": identifier, "path": str(destination), "commit": sha}



def _previous_origin_last(body: str, pointer: str) -> str:
    """Move `## Previous origin` to the end of the origin and add the tool's
    pointer line, so the standalone sections always come first."""
    lines = body.rstrip("\n").splitlines()
    start = next(i for i, line in enumerate(lines) if line.strip() == "## Previous origin")
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("## ")), len(lines))
    section = [line for line in lines[start + 1 : end]]
    rest = (lines[:start] + lines[end:])
    text = "\n".join(section).strip()
    return "\n".join(rest).rstrip() + f"\n\n## Previous origin\n\n{text}\n\n{pointer}\n"


def reanchor(
    root: Path, thread: Path, source: Path, by: dict[str, str], *, title: str | None = None,
    body_text: str,
) -> dict[str, Any]:
    """Replace the origin in place after a checkpoint has closed out the old one,
    and write the checkpoint that opens the new one: reanchoring is itself a
    checkpoint. One commit."""
    from .cli import _validate_origin

    identifier = thread_id(thread)
    _require_state(thread, BAD_STATE, verb="reanchored")
    checkpoint_id = _require_clean(thread, DIRTY, verb="reanchor")

    body = store.strip_comments(source.read_text(encoding="utf-8"))
    _validate_origin(body, reanchoring=True)
    old_origin = thread / "origin.md"
    old_metadata, _ = parse_frontmatter(old_origin.read_text(encoding="utf-8"))
    new_title = title if title is not None else old_metadata["title"]
    if not new_title.strip() or len(new_title) > 80 or "\n" in new_title:
        raise ThreadError(
            f"a thread title is one line of at most 80 characters; this one is {len(new_title)}"
            f"{' over several lines' if chr(10) in new_title else ''}. Detail belongs in the origin."
        )

    # Everything that can refuse runs before the first write.
    checkpoint.parse_body(body_text)

    replacements = [event for event in events.read_events(thread) if event["type"] == "origin-replaced"]
    previous = f"origin-{len(replacements) + 1}.md"
    metadata: dict[str, Any] = {
        "thread": old_metadata["thread"],
        "title": new_title,
        "created": events.timestamp(),
        "by": by,
    }
    for field in ("parent", "namespace", "from-task"):
        if field in old_metadata:
            metadata[field] = old_metadata[field]
    metadata["previous"] = previous

    body = _previous_origin_last(body, f"→ {previous} (replaced after {checkpoint_id})")
    atomic_text(thread / previous, old_origin.read_text(encoding="utf-8"))
    atomic_text(old_origin, markdown(metadata, body))
    payload = {"previous": previous, "after-checkpoint": checkpoint_id}
    if new_title != old_metadata["title"]:
        payload["title"] = new_title
    events.append(thread, "origin-replaced", payload, by)
    written, _ = checkpoint.create(
        root, thread, None, by, at=None, forced_by="reanchor", body_text=body_text, commit=False,
        # The clean gate above proved there is no unread work; the CAS would
        # otherwise see this reanchor's own event.
        skip_cas=True,
    )
    render.write_index(thread)
    sha = gitops.commit(root, f"reanchor {identifier} after {checkpoint_id}, opened by {written}: {new_title}", [thread])
    return {
        "thread": identifier, "previous": previous, "after-checkpoint": checkpoint_id,
        "checkpoint": written, "title": new_title, "commit": sha,
    }


def link(thread: Path, kind: str, target: Path, by: dict[str, str]) -> dict[str, Any]:
    identifier = thread_id(thread)
    target_id = thread_id(target)
    _require_state(thread, BAD_STATE, verb="linked")
    if identifier == target_id:
        raise ThreadError(f"{identifier} can't link to itself. Choose a different target.")
    item = {"kind": kind, "target": target_id}
    if item in _cache(thread).get("links", []):
        raise ThreadError(
            f"{identifier} is already linked to {target_id} as {kind}. "
            f"Use `thread unlink {identifier} {kind} {target_id}` to remove it."
        )
    # blocked-by is information for readers; it deliberately never gates work.
    return events.append(thread, "linked", item, by)


def unlink(thread: Path, kind: str, target_id: str, by: dict[str, str]) -> dict[str, Any]:
    identifier = thread_id(thread)
    item = {"kind": kind, "target": target_id}
    if item not in _cache(thread).get("links", []):
        raise ThreadError(
            f"{identifier} has no {kind} link to {target_id}. `thread view {identifier}` shows its links."
        )
    return events.append(thread, "unlinked", item, by)


def revise(root: Path, thread: Path, source: Path, by: dict[str, str]) -> dict[str, Any]:
    """Append a dated change to the current origin."""
    identifier = thread_id(thread)
    _require_state(thread, BAD_STATE, verb="revised")
    _require_clean(thread, DIRTY, verb="revise the origin")

    addition = source.read_text(encoding="utf-8")
    if not addition.strip():
        raise ThreadError(
            f"{source} is empty. A revision says what changed in the understanding of the work, and why; "
            f"it is appended to the origin ({guide.doc('thread-creation.md')})."
        )
    origin = thread / "origin.md"
    metadata, body = parse_frontmatter(origin.read_text(encoding="utf-8"))
    revision = 1
    for event in reversed(events.read_events(thread)):
        if event["type"] == "origin-replaced":
            break
        if event["type"] == "origin-revised":
            revision += 1
    body = body.rstrip("\n")
    if not any(line.strip() == "## Revisions" for line in body.splitlines()):
        body += "\n\n## Revisions"
    heading = f"### {events.timestamp()[:10]} by {by['session']}"
    body = f"{body}\n\n{heading}\n\n{addition}"
    if not body.endswith("\n"):
        body += "\n"
    atomic_text(origin, markdown(metadata, body))
    events.append(thread, "origin-revised", {"revision": revision}, by)
    sha = gitops.commit(root, f"revise {identifier}: revision {revision}", [thread])
    return {"thread": identifier, "revision": revision, "commit": sha}



def archive(root: Path, by: dict[str, str]) -> list[str]:
    """Idempotent: anything in a final state not yet archived moves."""
    moved: list[str] = []
    touched: list[Path] = []
    for thread in [path for path in iter_threads(root) if is_active(path)]:
        cache = _cache(thread)
        state = cache.get("state")
        if not is_final(state):
            continue
        changed = [
            event for event in events.read_events(thread)
            if event["type"] == "state-changed"
            and store.current_state(event["payload"]["to"], event["payload"].get("reason")) == state
        ]
        moment = changed[-1]["ts"] if changed else cache.get("last-event", events.timestamp())
        destination = _to_archive(root, thread, moment)
        touched += [thread, destination]
        moved.append(f"{thread_id(destination)} → {destination.relative_to(root)}")
    if moved:
        gitops.commit(root, f"archive: {len(moved)} thread(s)", touched)
    return moved

