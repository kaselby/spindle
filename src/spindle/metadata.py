"""thread.yml: the thread's metadata, written by hand or by the tool.

What a thread is (title, parent, flags) lives here and nowhere else.
What happened lives in log.jsonl; what state the thread is in is computed from
the log on read (events.state) and never stored. origin.md is narrative only.

People and agents edit thread.yml directly. The tool writes it on create, on
reanchor (title) and on reparent (parent), touching only the line it changes so
hand-written comments and flag order survive.

The file is validated on every read. A bad file is an error for commands on
that one thread; store-wide readers (list, the startup snapshot, subthread and
link scans) skip it and count it, so one bad file never takes down the store.
"""

from __future__ import annotations

import difflib
import re
import subprocess
from datetime import date, datetime
from pathlib import Path
from typing import Any

import yaml

from .store import ThreadError, atomic_text, root_of

FILE = "thread.yml"
THREAD_ID = re.compile(r"^[a-z0-9]{6,12}$")

# Known top-level keys, in the order the tool writes them.
KEYS = ("title", "parent", "from-task", "supersedes", "flags")

# The shape, printed when a bad file has no committed version to restore.
SCHEMA = """\
title: One line, at most 80 characters        # required
parent: <thread id>                           # subthreads only
from-task: <task id>                          # set by `thread promote`
flags:                                        # optional: your own keys, scalar values
  kiln.autonomous: true                       #   prefix keys with your tool's name
"""

# Keys only the old cache had. Their presence means the store predates this
# model, which this version no longer converts (see OLD_FORMAT).
_CACHE_KEYS = {"state", "tip", "events-since-checkpoint", "claims", "children", "last-event"}


# Where to convert a store from before thread.yml held the metadata. The
# converter was removed once the known stores were converted.
OLD_FORMAT = "convert the store with `thread migrate` from an older Spindle (commit 5de08e0 has it)"


class MetadataError(ThreadError):
    """thread.yml is missing or doesn't validate."""


def path_of(thread: Path) -> Path:
    return thread / FILE


def _relative(thread: Path) -> tuple[Path | None, str]:
    """(store root, path of thread.yml relative to it), for the git command."""
    try:
        root = root_of(thread)
    except ThreadError:
        return None, str(path_of(thread))
    return root, path_of(thread).relative_to(root).as_posix()


def _committed(root: Path | None, relative: str) -> bool:
    if root is None:
        return False
    result = subprocess.run(
        ["git", "cat-file", "-e", f"HEAD:{relative}"], cwd=root,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False,
    )
    return result.returncode == 0


def _refuse(thread: Path, problems: list[str]) -> MetadataError:
    """One error naming every problem, then how to get back to a good file."""
    root, relative = _relative(thread)
    where = f"{thread.name}/{FILE}"
    lines = [f"{where} isn't valid thread metadata:"]
    lines += [f"- {problem}" for problem in problems]
    if _committed(root, relative):
        lines.append(
            f"Fix it by hand, or restore the last committed version: git -C {root} checkout -- {relative}"
        )
    else:
        lines.append("Fix it by hand. It should look like this:")
        lines += [f"  {line}" for line in SCHEMA.splitlines()]
    return MetadataError("\n".join(lines))


def _scalar(value: Any) -> bool:
    return value is None or isinstance(value, (str, int, float, bool))


def _validate(thread: Path, value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _refuse(thread, [f"it must be a mapping of keys to values, not {type(value).__name__}"])
    stale = sorted(_CACHE_KEYS & set(value))
    if stale:
        raise MetadataError(
            f"{thread.name}/{FILE} is in the old format, a summary the tool rebuilt from the log "
            f"(it has {', '.join(stale)}). This version can't read that; {OLD_FORMAT}."
        )
    problems: list[str] = []
    result: dict[str, Any] = {}
    for key, item in value.items():
        if key not in KEYS:
            guess = difflib.get_close_matches(str(key), KEYS, n=1)
            hint = f" (did you mean `{guess[0]}`?)" if guess else ""
            problems.append(
                f"unknown key `{key}`{hint}. Known keys: {', '.join(KEYS)}. "
                f"Your own keys go under `flags:`."
            )
            continue
        if item is None and key != "title":
            continue  # `parent:` left blank means no parent
        if key == "title":
            if not isinstance(item, str) or not item.strip():
                problems.append("`title` must be text, one line of at most 80 characters")
            elif "\n" in item.strip() or len(item) > 80:
                problems.append(f"`title` must be one line of at most 80 characters; it is {len(item)}")
        elif key in ("parent", "supersedes"):
            if isinstance(item, int) and not isinstance(item, bool):
                item = str(item)  # an all-digit id typed without quotes reads as a number
            if not isinstance(item, str) or not THREAD_ID.match(item):
                problems.append(f"`{key}` must be a thread id (like 9eu8w2); got {item!r}")
            elif key == "parent" and item == thread.name.split("-", 1)[0]:
                problems.append(f"`parent` is this thread's own id ({item}); a thread can't be its own subthread")
        elif key == "from-task":
            if not isinstance(item, str):
                problems.append(f"`{key}` must be text; got {item!r}")
        elif key == "flags":
            if not isinstance(item, dict):
                problems.append("`flags` must be a mapping of your own keys to single values")
                continue
            flags = {}
            for name, flag in item.items():
                if not isinstance(name, str):
                    problems.append(f"flag name {name!r} must be text; put it in quotes")
                    continue
                if isinstance(flag, (date, datetime)):
                    flag = flag.isoformat()  # YAML reads a bare date as a date
                if not _scalar(flag):
                    problems.append(
                        f"flag `{name}` must be a single value (text, number, true/false), not a "
                        f"{'list' if isinstance(flag, list) else 'mapping'}"
                    )
                    continue
                flags[name] = flag
            item = flags
        result[key] = item
    if "title" not in value:
        problems.append("`title` is missing; every thread has one")
    if problems:
        raise _refuse(thread, problems)
    return result


def read(thread: Path) -> dict[str, Any]:
    """The validated metadata. Blank optional keys are left out."""
    path = path_of(thread)
    if not path.exists():
        root, relative = _relative(thread)
        restore = (
            f" Restore it: git -C {root} checkout -- {relative}" if _committed(root, relative)
            else " Write one by hand; it should look like this:\n" + "\n".join(f"  {line}" for line in SCHEMA.splitlines())
        )
        raise MetadataError(f"{thread.name} has no {FILE}.{restore}")
    try:
        value = yaml.safe_load(path.read_text(encoding="utf-8"))
    except UnicodeDecodeError as exc:
        raise _refuse(thread, [f"it isn't UTF-8 text ({exc.reason} at byte {exc.start})"]) from exc
    except yaml.YAMLError as exc:
        raise _refuse(thread, [f"it isn't valid YAML: {exc}"]) from exc
    return _validate(thread, value)


def title_or_name(thread: Path) -> str:
    """For headers that must render even when thread.yml is broken."""
    try:
        return read(thread)["title"]
    except (ThreadError, OSError):
        return thread.name


def dump(value: dict[str, Any]) -> str:
    ordered = {key: value[key] for key in KEYS if key in value and value[key] is not None}
    return yaml.safe_dump(ordered, sort_keys=False, allow_unicode=True)


def write(thread: Path, value: dict[str, Any]) -> None:
    """Write the whole file (create)."""
    atomic_text(path_of(thread), dump(value))


def _line(key: str, value: Any) -> str:
    return yaml.safe_dump({key: value}, allow_unicode=True, width=10_000).rstrip("\n")


def update(thread: Path, key: str, value: Any) -> None:
    """Change one top-level scalar key, keeping the rest of the file as written
    (comments, flag order). Falls back to rewriting the file if the key's
    current value isn't a plain one-line scalar."""
    current = read(thread)
    path = path_of(thread)
    lines = path.read_text(encoding="utf-8").splitlines()
    new = _line(key, value)
    pattern = re.compile(rf"^{re.escape(key)}\s*:")
    at = next((i for i, line in enumerate(lines) if pattern.match(line)), None)
    if at is None:
        # New key: after the title, where the tool would have put it.
        title_at = next((i for i, line in enumerate(lines) if line.startswith("title:")), -1)
        lines.insert(title_at + 1, new)
    elif at + 1 < len(lines) and lines[at + 1][:1] in (" ", "\t", "-"):
        lines = []  # a multi-line value: rewrite the file instead
    else:
        lines[at] = new
    text = "\n".join(lines) + "\n" if lines else ""
    expected = {**current, key: value}
    if not text or _parsed(text) != expected:
        atomic_text(path, dump(expected))
        return
    atomic_text(path, text)


def _parsed(text: str) -> Any:
    try:
        value = yaml.safe_load(text)
    except yaml.YAMLError:
        return None
    if not isinstance(value, dict):
        return None
    return {key: item for key, item in value.items() if item is not None}


def changes(before: dict[str, Any] | None, after: dict[str, Any]) -> str | None:
    """"title, parent changed; 2 flags changed", or None when nothing did.
    Built-in fields are named; flags are only counted."""
    if before is None:
        return None
    named = [key for key in KEYS if key != "flags" and before.get(key) != after.get(key)]
    old_flags, new_flags = before.get("flags") or {}, after.get("flags") or {}
    flagged = sum(1 for name in {*old_flags, *new_flags} if old_flags.get(name, _MISSING) != new_flags.get(name, _MISSING))
    parts = []
    if named:
        parts.append(f"{', '.join(named)} changed")
    if flagged:
        parts.append(f"{flagged} flag{'' if flagged == 1 else 's'} changed")
    return "; ".join(parts) or None


_MISSING = object()


def baseline_from(payload: dict[str, Any]) -> dict[str, Any]:
    """The metadata keys of a `created` payload or a checkpoint's `metadata` block."""
    return {key: payload[key] for key in KEYS if payload.get(key) is not None}
