"""Argument parsing and command dispatch for ``thread``."""

from __future__ import annotations

import argparse
import os
import re
import json
import shutil
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from . import scope as scopes
from . import checkpoint, doctor, events, guide, lifecycle, metadata, render, summary, tasks
from .limits import LIMITS
from .store import (
    NeedsInput, ThreadError, atomic_text, initialize, iter_threads, markdown, new_thread_id,
    parse_frontmatter, resolve_thread, root_path, slugify, write_yaml,
    thread_home, is_active, namespace_of, strip_comments,
)

ORIGIN_TEMPLATE = guide.ORIGIN_TEMPLATE
# A registration is a doc (docs/, read to understand the work), an artifact
# (artifacts/, what the work produced), or the thread's reading guide
# (reading-guide.md at the thread root). The kind must match the path.
KINDS = ["doc", "artifact", "reading-guide"]
KIND_FOLDER = {"doc": "docs", "artifact": "artifacts"}
LINK_KINDS = ["related", "blocked-by", "continues"]



def _common(parser: argparse.ArgumentParser, *, identity: bool = False, data: bool = False) -> None:
    parser.add_argument("--root", help="the thread store (default: $SPINDLE_ROOT, else by the scope in ~/.spindle/config.yml)")
    if identity:
        parser.add_argument("--by", help="act as this session[/agent] instead of THREAD_SESSION")
    if data:
        parser.add_argument("--json", action="store_true", help="print JSON")


class _Parser(argparse.ArgumentParser):
    """argparse, with a pointer to --help on every usage error."""

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        self.exit(2, f"{self.prog}: {message}\n`{self.prog} --help` explains each argument.\n")


ORIGIN_HELP = "the origin: a markdown file (leave it out to print the template)"


def _setup(args: argparse.Namespace) -> None:
    from . import setup

    if args.check:
        state = setup.status(args.harness)
        _emit({"harness": args.harness, "path": str(setup.target(args.harness)), "status": state} if args.json
              else f"{args.harness}: {state} ({setup.target(args.harness)})\n", as_json=args.json)
        return
    if args.remove:
        path, removed = setup.remove(args.harness)
        _emit({"path": str(path), "removed": removed} if args.json
              else f"{'Removed Spindle instructions from' if removed else 'Nothing to remove in'} {path}\n",
              as_json=args.json)
        return
    lines = []
    if args.scope:
        scopes.write_scope(args.scope)
        lines.append(f"Scope set to {args.scope} ({scopes.config_path()})")
    root, how = scopes.locate(args.root)
    store = "existing"
    if how == "project":
        store = "per project"
        lines.append("Each project's store is started by the first `thread create` there.")
    elif root.exists():
        root_path(args.root)  # an existing folder must already be a store; this says how to fix it if not
    else:
        initialize(root)
        store = "created"
        lines.append(f"Created the thread store at {root}")
    path, change = setup.install(args.harness)
    lines.append(f"Instructions for {args.harness}: {change} ({path})")
    if change != "already current":
        lines.append("They take effect in the next session.")
    _emit({"root": str(root), "store": store, "path": str(path), "change": change} if args.json
          else "\n".join(lines) + "\n", as_json=args.json)


def parser() -> argparse.ArgumentParser:
    result = _Parser(
        prog="thread",
        description=(
            "Track ongoing work on disk so a new session can pick it up. Start with `thread list`, "
            "then `thread view <id>`. Guide: the spindle-threads skill."
        ),
    )
    commands = result.add_subparsers(dest="command", required=True, metavar="<command>")

    init = commands.add_parser("init", help="create the thread store (~/.spindle unless --root or SPINDLE_ROOT says otherwise)")
    _common(init, data=True)

    setup_cmd = commands.add_parser(
        "setup", help="install Spindle's standing instructions for a harness, and create the store if needed")
    setup_cmd.add_argument("--harness", required=True, choices=["claude-code", "pi", "omp"],
                           help="the harness this session runs in")
    how = setup_cmd.add_mutually_exclusive_group()
    how.add_argument("--check", action="store_true", help="only report: current, outdated, or missing")
    how.add_argument("--remove", action="store_true", help="take the instructions out again (the store stays)")
    setup_cmd.add_argument("--scope", choices=list(scopes.SCOPES),
                           help="global (~/.spindle, the default) or project (<launch folder>/.spindle)")
    _common(setup_cmd, data=True)

    create = commands.add_parser("create", help="start a thread (no --origin: print the origin template)")
    create.add_argument("title", nargs="?", help="one line, at most 80 characters")
    create.add_argument("--origin", type=Path, help=ORIGIN_HELP)
    create.add_argument("--parent", help="make it a subthread of this thread")
    create.add_argument("--from-task", help="the parent's task this subthread came from")
    create.add_argument("--template", action="store_true", help="print the origin template and exit")
    create.add_argument("--ns", help=f"{guide.NAMESPACE_HELP} (default: $SPINDLE_NAMESPACE if set)")
    _common(create, identity=True, data=True)

    view = commands.add_parser("view", help="the thread's orientation page: read this first")
    view.add_argument("thread", help="thread id (a unique prefix works)")
    view.add_argument("--deep", action="store_true", help="include subthreads' checkpoints in the history")
    _common(view, identity=True, data=True)

    claim = commands.add_parser("claim", help="say you're working on a thread (doesn't lock anything)")
    claim.add_argument("thread")
    claim.add_argument("--intent", help="what you're doing, shown to other sessions")
    _common(claim, identity=True, data=True)

    release = commands.add_parser("release", help="say you've stopped working on a thread")
    release.add_argument("thread")
    release.add_argument("--skip", metavar="REASON",
                         help="release without the checkpoint it asks for; the reason is shown to the next session")
    _common(release, identity=True, data=True)

    note = commands.add_parser("note", help="record a finding in the log (not shown on the view page)")
    note.add_argument("thread")
    note.add_argument("text")
    note.add_argument("--tag", action="append", default=[], help="a tag; repeat for more")
    _common(note, identity=True, data=True)

    task = commands.add_parser("task", help="the thread's task list: add, close, remove, list")
    task_commands = task.add_subparsers(dest="task_command", required=True, metavar="<add|close|remove|list>")
    task_add = task_commands.add_parser("add", help="add a task (one line, at most 200 characters)")
    task_add.add_argument("thread")
    task_add.add_argument("text")
    _common(task_add, identity=True, data=True)
    for name in ("close", "remove"):
        sub = task_commands.add_parser(name, help=f"{name} a task by id")
        sub.add_argument("thread")
        sub.add_argument("task_id", help="task id, from `thread task list`")
        _common(sub, identity=True, data=True)
    task_list = task_commands.add_parser("list", help="list open tasks")
    task_list.add_argument("thread")
    task_list.add_argument("--all", action="store_true", help="include closed tasks")
    _common(task_list, identity=True, data=True)

    promote = commands.add_parser("promote", help="turn a task into a subthread")
    promote.add_argument("thread")
    promote.add_argument("task_id")
    promote.add_argument("title", help="the subthread's title")
    promote.add_argument("--origin", type=Path, help=ORIGIN_HELP)
    promote.add_argument("--ns", help=f"{guide.NAMESPACE_HELP} (default: the parent's)")
    _common(promote, identity=True, data=True)

    register = commands.add_parser(
        "register", help="list a file or directory in docs/ or artifacts/ on the view page, "
                         "or record that the reading guide was written or changed")
    register.add_argument("thread")
    register.add_argument("path", help="relative to the thread folder: under docs/ or artifacts/, or reading-guide.md")
    register.add_argument("--kind", required=True, choices=KINDS,
                          help="doc (under docs/), artifact (under artifacts/), or reading-guide (reading-guide.md); "
                               "must match the path")
    register.add_argument("--purpose", help="what it is, at most 160 characters (for a reading guide: optional, "
                                            "what changed)")
    register.add_argument("--read-when", help="when a reader should open it (required for docs)")
    _common(register, identity=True, data=True)

    cp = commands.add_parser("checkpoint", help="record where the work stands (no body: print the template)")
    cp.add_argument("thread")
    cp.add_argument("body", type=Path, nargs="?", help="markdown file (leave it out to print the template)")
    cp.add_argument("--at", metavar="EVENT-ID",
                    help="the latest event id you've read; needed when another session wrote since the last checkpoint")
    cp.add_argument("--forced-by", choices=["merge", "pivot", "complete", "drop"], help="mark why the checkpoint was required (the tool sets merge itself)")
    _common(cp, identity=True, data=True)

    replay = commands.add_parser("replay", help="read the event log (default: since the last checkpoint)")
    replay.add_argument("thread")
    scope = replay.add_mutually_exclusive_group()
    scope.add_argument("--since-checkpoint", action="store_true", default=True, help="the default")
    scope.add_argument("--all", action="store_true", help="the whole history")
    scope.add_argument("--checkpoint", metavar="cNNNN", help="one past checkpoint in full, as written")
    scope.add_argument("--checkpoints", action="store_true", help="every checkpoint in full, oldest first")
    replay.add_argument("--type", help="only this event type, e.g. note, checkpoint, register")
    replay.add_argument("--session", help="only events by this session")
    _common(replay, identity=True, data=True)

    doc = commands.add_parser("doctor", help="check for problems; each finding says what to do")
    doc.add_argument("thread", nargs="?", help="one thread (default: all)")
    _common(doc, identity=True, data=True)

    merge = commands.add_parser("merge", help="fold a finished subthread into its parent")
    merge.add_argument("thread", metavar="child")
    merge.add_argument("--promote", nargs="+", action="extend", metavar="REL-PATH",
                       help="docs/artifacts to copy into the parent (the rest are linked)")
    merge.add_argument("--tasks", nargs="+", action="extend", metavar="ID",
                       help="child task ids to copy onto the parent's task list")
    merge.add_argument("--all-tasks", action="store_true", help="copy all the child's open tasks")
    merge.add_argument("--force", action="store_true", help="move the child's open subthreads to the parent")
    merge.add_argument("--body", type=Path,
                       help="the parent's merge checkpoint (required; without it, merge prints the template)")
    _common(merge, identity=True, data=True)

    complete = commands.add_parser("complete", help="finish a top-level thread whose work is done (subthreads merge instead)")
    complete.add_argument("thread")
    _common(complete, identity=True, data=True)

    drop = commands.add_parser("drop", help="end a thread that isn't worth pursuing (subthreads too)")
    drop.add_argument("thread")
    drop.add_argument("--force", action="store_true", help="move unfinished subthreads to this thread's parent")
    _common(drop, identity=True, data=True)

    # Retired verb, kept off the help list: it only says what replaced it.
    retired = commands.add_parser("close", add_help=False)
    retired.add_argument("rest", nargs=argparse.REMAINDER)

    reopen = commands.add_parser("reopen", help="bring back a completed or dropped thread")
    reopen.add_argument("thread")
    _common(reopen, identity=True, data=True)

    revise = commands.add_parser("revise", help="append a dated revision to the origin")
    revise.add_argument("thread")
    revise.add_argument("file", type=Path, help="markdown: what changed in the understanding, and why")
    _common(revise, identity=True, data=True)

    reanchor = commands.add_parser("reanchor", help="replace the origin while keeping the thread and its work")
    reanchor.add_argument("thread")
    reanchor.add_argument("--origin", type=Path, help=ORIGIN_HELP)
    reanchor.add_argument("--title", help="replace the title (the folder and slug stay unchanged)")
    reanchor.add_argument("--body", type=Path, help="the checkpoint reanchoring writes, measured against the new origin (no body: print the template)")
    _common(reanchor, identity=True, data=True)

    link = commands.add_parser(
        "link",
        help="relate threads (blocked-by is display-only and never gates a command)",
    )
    link.add_argument("thread")
    link.add_argument("kind", choices=LINK_KINDS)
    link.add_argument("target")
    _common(link, identity=True, data=True)

    unlink = commands.add_parser("unlink", help="remove a thread relationship")
    unlink.add_argument("thread")
    unlink.add_argument("kind", choices=LINK_KINDS)
    unlink.add_argument("target")
    _common(unlink, identity=True, data=True)

    # Retired verb, kept off the help list: it only says what replaced it.
    retired = commands.add_parser("supersede", add_help=False)
    retired.add_argument("rest", nargs=argparse.REMAINDER)

    archive = commands.add_parser("archive", help="move finished threads (merged, completed, dropped) into threads/archived/")
    _common(archive, identity=True, data=True)

    listing = commands.add_parser("list", help="active threads as a tree by namespace: their state, who's working, events since checkpoint")
    listing.add_argument("--ns", help="only this namespace; `default` means threads created without one")
    listing.add_argument(
        "--flag", action="append", default=[], metavar="KEY[=VALUE]",
        help="only threads whose thread.yml has this flag (with this value, if given); repeat to require several")
    _common(listing, identity=True, data=True)


    path = commands.add_parser("path", help="print a thread's folder")
    path.add_argument("thread")
    _common(path, identity=True, data=True)
    return result


PREVIOUS_ORIGIN = "Previous origin"


def _validate_origin(body: str, *, reanchoring: bool = False) -> None:
    body = guide.strip_comments(body)
    lines = body.splitlines()
    found: dict[str, str] = {}
    headings = [(i, line[3:].strip()) for i, line in enumerate(lines) if line.startswith("## ")]
    for position, (start, name) in enumerate(headings):
        end = headings[position + 1][0] if position + 1 < len(headings) else len(lines)
        content = "\n".join(
            line for line in lines[start + 1 : end] if not line.strip().startswith("<!--")
        ).strip()
        found[name] = content
    for name in ("Context & Motivation",):
        if not found.get(name):
            raise ThreadError(
                f"the origin needs a non-empty `## {name}` section. `thread create --template` prints "
                f"the template ({guide.doc('creating-a-thread.md')})."
            )
    # A reanchored origin is written as if the thread were
    # created today, plus one short section on the change, pointing back.
    if reanchoring:
        text = found.get(PREVIOUS_ORIGIN, "")
        if not text:
            raise ThreadError(
                f"a reanchored origin needs a short `## {PREVIOUS_ORIGIN}` section at the end: what the "
                f"earlier framing was, what changed, and why. The tool adds the pointer to the old file. "
                f"Write the rest as if the thread were created today ({guide.doc('changing-direction.md')})."
            )
        limit = LIMITS["previous_origin_chars"]
        if len(text) > limit:
            raise ThreadError(
                f"`## {PREVIOUS_ORIGIN}` is {len(text)} characters; the limit is {limit}. Keep it to a few "
                f"sentences: the old origin itself stays readable in its own file."
            )
    elif PREVIOUS_ORIGIN in found:
        raise ThreadError(
            f"`## {PREVIOUS_ORIGIN}` belongs only in a reanchored origin (`thread reanchor`). "
            f"Remove it from a new thread's origin."
        )


def _flag_filters(values: list[str]) -> list[tuple[str, str | None]]:
    """`--flag key=value` or `--flag key` as (key, value or None). The split is at
    the first `=`, so a value may contain one; a flag name can't."""
    filters = []
    for value in values:
        key, has_value, wanted = value.partition("=")
        if not key.strip():
            raise ThreadError(f"--flag {value!r} names no flag; write --flag key=value, or --flag key for any value")
        filters.append((key.strip(), wanted if has_value else None))
    return filters


def _flag_text(value: Any) -> str:
    """A flag value as it would be typed: YAML's true/false, and blank for null."""
    if isinstance(value, bool):
        return "true" if value else "false"
    return "" if value is None else str(value)


def _has_flags(path: Path, filters: list[tuple[str, str | None]]) -> bool:
    """Does the thread carry every flag asked for? One that can't be read is kept,
    so the listing still counts it as unreadable rather than silently dropping it."""
    try:
        flags = summary.describe(path).get("flags") or {}
    except summary.UNREADABLE:
        return True
    return all(key in flags and (wanted is None or _flag_text(flags[key]) == wanted) for key, wanted in filters)


def _clean_namespace(value: str | None, source: str = "--ns") -> str | None:
    """Normalize a namespace: 'default'/'' mean the root namespace (stored as absent).

    ``source`` names where the value came from (--ns or SPINDLE_NAMESPACE), so
    the refusal can say what to change.
    """
    if value is None:
        return None
    value = value.strip()
    if value in ("", "default"):
        return None
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,31}", value):
        raise ThreadError(guide.bad_namespace(value, source))
    return value


def _default_namespace() -> str | None:
    return _clean_namespace(os.environ.get("SPINDLE_NAMESPACE"), "SPINDLE_NAMESPACE")


def _require_parent_namespace(parent: Path, namespace: str | None, source: str) -> None:
    """A subthread lives in its parent's namespace."""
    if namespace != namespace_of(parent):
        raise ThreadError(
            f"{parent.name.split('-', 1)[0]} is in namespace {namespace_of(parent) or 'default'}, and a "
            f"subthread lives in its parent's namespace, so {source} {namespace or 'default'} can't be used "
            f"here. Leave {source} out and the subthread goes into {namespace_of(parent) or 'default'}."
        )


def _create(
    root: Path,
    title: str,
    origin_path: Path,
    by: dict[str, str],
    *,
    parent: Path | None = None,
    from_task: str | None = None,
    namespace: str | None = None,
) -> Path:
    if namespace is not None:
        namespace = _clean_namespace(namespace)
    if parent is not None:
        _require_parent_namespace(parent, namespace, "the namespace")
    if not title.strip() or len(title) > 80 or "\n" in title:
        raise ThreadError(
            f"a thread title is one line of at most 80 characters; this one is {len(title)}"
            f"{' over several lines' if chr(10) in title else ''}. Detail belongs in the origin."
        )
    body = strip_comments(origin_path.read_text(encoding="utf-8"))
    _validate_origin(body)
    identifier = new_thread_id(root)
    destination = thread_home(root, f"{identifier}-{slugify(title)}", namespace)
    # origin.md is the narrative; its frontmatter only says whose it is and when.
    front: dict[str, Any] = {"thread": identifier, "created": events.timestamp(), "by": by}
    # thread.yml is the metadata; people edit it directly from here on.
    values: dict[str, Any] = {"title": title}
    if parent:
        values["parent"] = parent.name.split("-", 1)[0]
    if from_task:
        values["from-task"] = from_task
    try:
        for folder in ("checkpoints", "docs", "artifacts", "scratch"):
            (destination / folder).mkdir(parents=True, exist_ok=True)
        atomic_text(destination / "origin.md", markdown(front, body))
        metadata.write(destination, values)
        atomic_text(destination / "log.jsonl", "")
        write_yaml(destination / "tasks.yml", {"tasks": []})
        # The initial metadata, so the view can show what changed before the first checkpoint.
        created_payload: dict[str, Any] = dict(values)
        if namespace:
            created_payload["namespace"] = namespace
        events.append(destination, "created", created_payload, by)
        events.append(destination, "claim", {}, by)
        render.write_index(destination)
        if parent:
            payload = {"child": identifier, "title": title}
            if from_task:
                payload["from-task"] = from_task
            events.append(parent, "child-created", payload, by)
    except Exception:
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return destination


def _emit(value: Any, *, as_json: bool = False) -> None:
    if as_json:
        print(json.dumps(value, ensure_ascii=False, indent=2))
    elif isinstance(value, str):
        print(value, end="" if value.endswith("\n") else "\n")
    else:
        print(value)


def _prepare(thread: Path, by: dict[str, str]) -> None:
    doctor.run(thread, by, full=False)


def _registration_path(thread: Path, value: str) -> tuple[str, Path]:
    normalized = PurePosixPath(value)
    if normalized.is_absolute() or ".." in normalized.parts or len(normalized.parts) < 2:
        raise ThreadError(
            f"register takes a path relative to the thread folder, under docs/ or artifacts/ "
            f"(like docs/setup.md); got {value}. The folder is {thread}."
        )
    if normalized.parts[0] not in {"docs", "artifacts"}:
        raise ThreadError(
            f"register takes a path under docs/ or artifacts/; got {value}. Move the file there first "
            f"(the thread folder is {thread})."
        )
    path = thread.joinpath(*normalized.parts)
    if not path.exists():
        raise ThreadError(f"{thread / value} doesn't exist. Put the file there first, then register it.")
    return normalized.as_posix(), path


def _register_reading_guide(thread: Path, identifier: str, args: argparse.Namespace, by: dict[str, str]) -> None:
    """Record that the reading guide was written or changed. The view shows the
    file itself; the event puts the change in the log and on replay."""
    if PurePosixPath(args.path).as_posix() != guide.READING_GUIDE:
        raise ThreadError(
            f"--kind reading-guide is for {guide.READING_GUIDE} at the thread root; got {args.path}. "
            f"`thread register {identifier} {guide.READING_GUIDE} --kind reading-guide`."
        )
    path = thread / guide.READING_GUIDE
    if not path.is_file():
        raise ThreadError(f"{path} doesn't exist. Write the guide there first, then register it.")
    if args.read_when:
        raise ThreadError("--read-when is for docs; the view page always shows the reading guide.")
    if args.purpose is not None and not 1 <= len(args.purpose.strip()) <= 160:
        raise ThreadError(f"--purpose must be 1–160 characters; it is {len(args.purpose.strip())}.")
    size = len(strip_comments(path.read_text(encoding="utf-8", errors="replace")).strip())
    cap = LIMITS["reading_guide_chars"]
    registration: dict[str, str] = {"path": guide.READING_GUIDE, "kind": "reading-guide"}
    if args.purpose:
        registration["purpose"] = args.purpose.strip()
    checkpoint_id = events.state(thread).get("last-checkpoint", {}).get("id", "pending")
    event = events.append(thread, "register", {"registration": registration, "checkpoint": checkpoint_id}, by)
    over = size > cap
    value = {**event, "chars": size, "cap": cap}
    text = f"Registered the reading guide at {event['id']} ({size:,} of {cap:,} characters)\n"
    if over:
        text += ("It is over the cap. Trim it to pointers and a reading order; "
                 "status and next steps belong in the checkpoint.\n")
    _emit(value if args.json else text, as_json=args.json)


def _size(path: Path) -> int:
    return path.stat().st_size if path.is_file() else sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


def run(args: argparse.Namespace) -> None:
    command = args.command
    if command == "close":
        raise ThreadError(
            "`thread close` is gone: a thread now ends as completed or dropped, so the archive shows "
            "which. `thread complete <id>` if the work is done (a subthread merges instead: "
            "`thread merge <id>`); `thread drop <id>` if it isn't worth pursuing "
            f"({guide.doc('completion-and-merging.md')})."
        )
    if command == "supersede":
        raise ThreadError(
            "`thread supersede` is gone. If the work continues under a new origin, use "
            "`thread reanchor <id> --origin <file>`. If the question itself was wrong, "
            "`thread drop <old>` (or `thread complete <old>`), create a new thread, then connect it "
            "with `thread link <new> continues <old>`."
        )
    if command == "init":
        root, how = scopes.locate(args.root)
        notes = scopes.start_project_store(root) if how == "project" else (initialize(root) or [])
        _emit({"root": str(root), "notes": notes} if args.json
              else "".join(f"{note}\n" for note in notes) or f"Initialized {root}\n", as_json=args.json)
        return
    if command == "setup":
        _setup(args)
        return
    if command == "create" and args.template:
        _emit(guide.origin_template(f'thread create "{args.title or "<title>"}" --origin <file>'))
        return

    notes: list[str] = []
    if command == "create" and args.origin:
        path, how = scopes.locate(args.root)
        if how == "project" and not path.exists():
            notes = scopes.start_project_store(path)
    root = root_path(args.root)
    by = events.identity(getattr(args, "by", None))

    if command == "create":
        if not args.title:
            raise ThreadError('create needs a title: thread create "<title>" --origin <file>')
        # Check the namespace and parent before printing a template, so a bad
        # one is caught before the origin is written rather than after.
        parent = resolve_thread(root, args.parent) if args.parent else None
        if args.ns is not None:
            namespace = _clean_namespace(args.ns)
        elif parent is not None:
            namespace = namespace_of(parent)  # a subthread lives in its parent's namespace
        else:
            namespace = _default_namespace()
        if parent is not None:
            _require_parent_namespace(parent, namespace, "--ns")
        if not args.origin:
            extra = "".join(
                f" --{flag} {value}" for flag, value in (
                    ("parent", args.parent), ("from-task", args.from_task), ("ns", args.ns),
                ) if value
            )
            raise NeedsInput(guide.origin_template(f'thread create "{args.title}"{extra} --origin <file>'))
        if parent:
            _prepare(parent, by)
        path = _create(root, args.title, args.origin, by, parent=parent, from_task=args.from_task, namespace=namespace)
        value = {"id": path.name.split("-", 1)[0], "path": str(path)}
        if notes:
            value["notes"] = notes
        _emit(value if args.json else "".join(f"{note}\n" for note in notes) + f"Created {value['id']} at {path}\n",
              as_json=args.json)
        return

    if command == "doctor":
        paths = [resolve_thread(root, args.thread)] if args.thread else iter_threads(root)
        grouped = [(path, doctor.run_safely(path, by)) for path in paths]
        if args.json:
            _emit({path.name.split('-', 1)[0]: findings for path, findings in grouped}, as_json=True)
        else:
            _emit(doctor.render(grouped))
        return

    if command == "archive":
        moved = lifecycle.archive(root, by)
        if args.json:
            _emit(moved, as_json=True)
        else:
            _emit("\n".join(f"- {line}" for line in moved) + "\n" if moved else "Nothing to archive\n")
        return

    if command == "list":
        paths = [path for path in iter_threads(root) if is_active(path)]
        for path in paths:
            try:
                _prepare(path, by)
            except summary.UNREADABLE:
                pass  # render.list_threads skips it and counts it
        wanted = None
        if args.ns is not None:
            wanted = _clean_namespace(args.ns)
            paths = [path for path in paths if namespace_of(path) == wanted]
        filters = _flag_filters(args.flag)
        if filters:
            paths = [path for path in paths if _has_flags(path, filters)]
        if args.json:
            described = []
            for path in paths:
                try:
                    described.append(summary.describe(path))
                except summary.UNREADABLE:
                    continue
            _emit(described, as_json=True)
        else:
            _emit(render.list_threads(
                root, paths, only=(wanted or "default") if args.ns is not None else None,
                flags=[key if value is None else f"{key}={value}" for key, value in filters],
            ))
        return

    thread = resolve_thread(root, args.thread)
    _prepare(thread, by)
    identifier = thread.name.split("-", 1)[0]

    if command == "path":
        _emit({"path": str(thread)} if args.json else f"{thread}\n", as_json=args.json)
    elif command == "view":
        if args.json:
            value = summary.describe(thread)
            value["children"] = summary.children(root, identifier)
            _emit(value, as_json=True)
        else:
            _emit(render.view(root, thread, deep=args.deep))
    elif command == "merge":
        value = lifecycle.merge(
            root, thread, by, promote=args.promote, task_ids=args.tasks,
            all_tasks=args.all_tasks, force=args.force, body=args.body,
        )
        _emit(value if args.json else (
            f"Merged {value['child']}@{value['child-checkpoint']} into "
            f"{value['parent']}@{value['checkpoint']} in commit {value['commit']}\n"
        ), as_json=args.json)
    elif command in ("complete", "drop"):
        if command == "complete":
            value = lifecycle.complete(root, thread, by)
        else:
            value = lifecycle.drop(root, thread, by, force=args.force)
        _emit(value if args.json else (
            f"{value['state'].capitalize()} {value['thread']}@{value['checkpoint']} in commit {value['commit']}\n"
        ), as_json=args.json)
    elif command == "reopen":
        value = lifecycle.reopen(root, thread, by)
        _emit(value if args.json else f"Reopened {value['thread']} at {value['path']}\n", as_json=args.json)
    elif command == "revise":
        value = lifecycle.revise(root, thread, args.file, by)
        _emit(value if args.json else (
            f"Revised {value['thread']}: revision {value['revision']}\n"
        ), as_json=args.json)
    elif command == "reanchor":
        if not args.origin:
            title_flag = f' --title "{args.title}"' if args.title else ""
            raise NeedsInput(guide.reanchor_origin_template(
                f"thread reanchor {identifier}{title_flag} --origin <file>"
            ))
        if not args.body:
            # Reanchoring is a checkpoint: it opens the thread
            # under its new origin, so it needs a body written against that origin.
            title_flag = f' --title "{args.title}"' if args.title else ""
            template = checkpoint.template(thread, by).replace(
                f"thread checkpoint {identifier} <file>",
                f"thread reanchor {identifier}{title_flag} --origin {args.origin} --body <file>\n"
                "     Reanchoring writes this checkpoint. The origin's Previous origin section says why the\n"
                "     framing changed; this checkpoint says where the work stands against the NEW origin.",
                1,
            )
            raise NeedsInput(template)
        value = lifecycle.reanchor(
            root, thread, args.origin, by, title=args.title, body_text=args.body.read_text(encoding="utf-8"),
        )
        _emit(value if args.json else (
            f"Reanchored {value['thread']}: {value['checkpoint']} opens the new origin "
            f"(previous origin is {value['previous']})\n"
        ), as_json=args.json)
    elif command == "link":
        target = resolve_thread(root, args.target)
        event = lifecycle.link(thread, args.kind, target, by)
        target_id = target.name.split("-", 1)[0]
        _emit(event if args.json else f"Linked {identifier} {args.kind} {target_id} at {event['id']}\n", as_json=args.json)
    elif command == "unlink":
        try:
            target_id = resolve_thread(root, args.target).name.split("-", 1)[0]
        except ThreadError:
            # A dangling link must remain removable after its target folder is gone.
            target_id = args.target
        event = lifecycle.unlink(thread, args.kind, target_id, by)
        _emit(event if args.json else f"Unlinked {identifier} {args.kind} {target_id} at {event['id']}\n", as_json=args.json)
    elif command == "claim":
        payload = {"intent": args.intent} if args.intent else {}
        event = events.append(thread, "claim", payload, by)
        _emit(event if args.json else f"Claimed {thread.name.split('-', 1)[0]} at {event['id']}\n", as_json=args.json)
    elif command == "release":
        recent = events.since_checkpoint(events.read_events(thread))
        # Only work (events.carries_work) needs a checkpoint before leaving.
        own = [
            event for event in recent
            if event["by"]["session"] == by["session"] and events.carries_work(event)
        ]
        if len(own) > LIMITS["release_events"] and not args.skip:
            raise ThreadError(
                f"{by['session']} has written {len(own)} events to {identifier} since the last checkpoint. "
                "Write a checkpoint before you release, so the next session knows where things stand "
                f"(`thread checkpoint {identifier}` prints the template). Or release without one: "
                f'`thread release {identifier} --skip "<reason>"`; the reason is shown to the next session.',
                code=3,
            )
        payload = {"skipped-checkpoint": args.skip} if args.skip else {}
        event = events.append(thread, "release", payload, by)
        _emit(event if args.json else f"Released {thread.name.split('-', 1)[0]} at {event['id']}\n", as_json=args.json)
    elif command == "note":
        payload = {"text": args.text}
        if args.tag:
            payload["tags"] = args.tag
        event = events.append(thread, "note", payload, by)
        _emit(event if args.json else f"Noted at {event['id']}\n", as_json=args.json)
    elif command == "task":
        if args.task_command == "add":
            value = tasks.add(thread, args.text, by)
        elif args.task_command == "close":
            value = tasks.close(thread, args.task_id, by)
        elif args.task_command == "remove":
            value = tasks.remove(thread, args.task_id, by)
        else:
            value = tasks.read(thread)
            if not args.all:
                value = [item for item in value if not item.get("done")]
        if args.json:
            _emit(value, as_json=True)
        elif args.task_command == "list":
            rows = []
            for item in value:
                mark = "x" if item.get("done") else " "
                promoted = f" → see thread {item['promoted']}" if item.get("promoted") else ""
                rows.append(f"- [{mark}] {item['id']} {item['text']}{promoted}")
            _emit("\n".join(rows) + ("\n" if rows else ""))
        else:
            _emit(f"{args.task_command} {value['id']}: {value['text']}\n")
    elif command == "promote":
        board = tasks.read(thread)
        task = next((item for item in board if item.get("id") == args.task_id), None)
        if task is None:
            raise ThreadError(
                f"no task {args.task_id} in {identifier}. `thread task list {identifier}` shows task ids."
            )
        # Refuse before creating the child, or a refused promote leaves a stray thread.
        if task.get("promoted"):
            raise ThreadError(
                f"task {args.task_id} was already promoted to thread {task['promoted']}; "
                f"work there instead (`thread view {task['promoted']}`)."
            )
        if args.ns is not None:
            namespace = _clean_namespace(args.ns)
            _require_parent_namespace(thread, namespace, "--ns")
        else:
            namespace = namespace_of(thread)
        if not args.origin:
            ns_flag = f" --ns {args.ns}" if args.ns else ""
            raise NeedsInput(guide.origin_template(
                f'thread promote {identifier} {args.task_id} "{args.title}"{ns_flag} --origin <file>'
            ))
        child = _create(root, args.title, args.origin, by, parent=thread, from_task=args.task_id, namespace=namespace)
        child_id = child.name.split("-", 1)[0]
        tasks.promote(thread, args.task_id, child_id, by)
        value = {"id": child_id, "path": str(child)}
        _emit(value if args.json else f"Promoted {args.task_id} to {child_id}\n", as_json=args.json)
    elif command == "register" and args.kind == "reading-guide":
        _register_reading_guide(thread, identifier, args, by)
    elif command == "register":
        if args.purpose is None:
            raise ThreadError('register needs --purpose "<what it is>" (1–160 characters).')
        relpath, path = _registration_path(thread, args.path)
        folder = relpath.split("/", 1)[0]
        if KIND_FOLDER[args.kind] != folder:
            right = "doc" if folder == "docs" else "artifact"
            raise ThreadError(
                f"--kind {args.kind} is for files under {KIND_FOLDER[args.kind]}/, and {relpath} is under "
                f"{folder}/. Use --kind {right}, or move the file to {KIND_FOLDER[args.kind]}/ first."
            )
        if relpath.startswith("docs/") and not args.read_when:
            raise ThreadError(
                'docs need --read-when "<when a reader should open it>", e.g. "before changing the parser". '
                "The view page lists each doc with it."
            )
        if len(args.purpose) > 160 or not args.purpose.strip():
            raise ThreadError(f"--purpose must be 1–160 characters; it is {len(args.purpose.strip())}.")
        if args.read_when and len(args.read_when) > 160:
            raise ThreadError(f"--read-when must be at most 160 characters; it is {len(args.read_when)}.")
        if _size(path) > LIMITS["register_bytes"]:
            subject = "directory" if path.is_dir() else "file"
            raise ThreadError(
                f"{subject} is over 5 MB. Store it outside the thread and register a small artifact that "
                "says where it is instead."
            )
        registration = {"path": relpath, "kind": args.kind, "purpose": args.purpose}
        if args.read_when:
            registration["read-when"] = args.read_when
        checkpoint_id = events.state(thread).get("last-checkpoint", {}).get("id", "pending")
        event = events.append(thread, "register", {
            "registration": registration, "checkpoint": checkpoint_id,
        }, by)
        render.write_index(thread)
        _emit(event if args.json else f"Registered {relpath} at {event['id']}\n", as_json=args.json)
    elif command == "checkpoint":
        checkpoint_id, sha = checkpoint.create(
            root, thread, args.body, by, at=args.at, forced_by=args.forced_by,
        )
        value = {"checkpoint": checkpoint_id, "commit": sha}
        _emit(value if args.json else f"Wrote {checkpoint_id} in commit {sha}\n", as_json=args.json)
    elif command == "replay" and (args.checkpoint or args.checkpoints):
        if args.type or args.session:
            raise ThreadError(
                "--type and --session filter events; --checkpoint and --checkpoints print checkpoints as written. "
                f"Use one or the other: `thread replay {identifier} --checkpoints`, or "
                f"`thread replay {identifier} --all --type checkpoint` for when each was written.",
                code=2,
            )
        if args.json:
            records = render.checkpoint_records(thread)
            if args.checkpoint:
                render.checkpoints_text(thread, args.checkpoint)  # refuses an unknown id
                records = [record for record in records if record["id"] == args.checkpoint]
            _emit(records, as_json=True)
        else:
            _emit(render.checkpoints_text(thread, args.checkpoint))
    elif command == "replay":
        text = render.replay(thread, all_events=args.all, kind=args.type, session=args.session)
        if args.json:
            log = events.read_events(thread)
            if not args.all:
                log = events.since_checkpoint(log)
            if args.type:
                log = [event for event in log if event["type"] == args.type]
            if args.session:
                log = [event for event in log if event["by"]["session"] == args.session]
            _emit(log, as_json=True)
        else:
            _emit(text)


def main(argv: list[str] | None = None) -> int:
    try:
        run(parser().parse_args(argv))
        return 0
    except NeedsInput as exc:
        print(str(exc), end="" if str(exc).endswith("\n") else "\n")
        return exc.code
    except ThreadError as exc:
        print(str(exc), file=sys.stderr)
        return exc.code
    except FileNotFoundError as exc:
        print(f"file not found: {exc.filename}", file=sys.stderr)
        return 2
    except PermissionError as exc:
        print(f"permission denied: {exc.filename}", file=sys.stderr)
        return 2
    except UnicodeDecodeError as exc:
        # thread.yml and the reading guide handle this themselves; this is the
        # backstop for any other file, so it never ends in a traceback.
        print(
            f"a file isn't UTF-8 text ({exc.reason} at byte {exc.start}). `thread doctor` names the thread.",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
