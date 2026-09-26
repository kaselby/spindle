"""`thread migrate`: move each thread's metadata into thread.yml, once.

Before this model, thread.yml was a cache the tool rebuilt from the log, and
the title, parent, project and namespace lived in origin.md's frontmatter
(with a later `reparented` event outranking the parent written there). For
every thread, archived ones included, migrate writes thread.yml from what the
old code would have computed, strips those keys from origin.md, appends one
`migrated` event carrying the metadata (the baseline for the view's "what
changed" line), and commits that thread on its own. Running it again changes
nothing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from . import events, gitops, metadata
from .store import (
    ThreadError, atomic_text, iter_threads, markdown, namespace_of, parse_frontmatter, read_yaml,
)

# origin.md frontmatter keys that move to thread.yml. `namespace` just goes:
# the folder has always been the namespace. So does `project`: the field was
# removed, and a store now belongs to a project instead.
MOVED = ("title", "parent", "supersedes", "from-task")
DROPPED = ("namespace", "project")


def _parent(front: dict[str, Any], log: list[dict[str, Any]]) -> str | None:
    """The parent the old fold computed: the last `reparented` event, else origin.md's."""
    moved = [event["payload"]["to"] for event in log if event["type"] == "reparented"]
    return moved[-1] if moved else front.get("parent")


def plan(thread: Path) -> dict[str, Any] | None:
    """What migrating this thread would write, or None if it's already done."""
    front, body = parse_frontmatter((thread / "origin.md").read_text(encoding="utf-8"))
    log = events.read_events(thread)
    current = read_yaml(metadata.path_of(thread), {})
    is_cache = isinstance(current, dict) and bool(metadata._CACHE_KEYS & set(current))
    has_migrated = any(event["type"] == "migrated" for event in log)
    stale_origin = any(key in front for key in (*MOVED, *DROPPED))
    converting = is_cache or not metadata.path_of(thread).exists()
    if not converting and not stale_origin:
        # A valid thread.yml and a clean origin: migrated already, or created
        # under this model (no `migrated` event, and it mustn't get one: that
        # would reset the view's baseline for thread.yml changes).
        metadata.read(thread)  # an invalid one is reported, not skipped
        return None

    if converting:
        value: dict[str, Any] = {"title": front.get("title") or (current or {}).get("title") or thread.name}
        parent = _parent(front, log)
        if parent:
            value["parent"] = parent
        for key in ("supersedes", "from-task"):
            if front.get(key):
                value[key] = front[key]
    else:
        value = metadata.read(thread)  # already written by an interrupted run; keep it

    notes = []
    if front.get("namespace") and front["namespace"] != namespace_of(thread):
        notes.append(
            f"origin.md said namespace {front['namespace']}, but the folder is in "
            f"{namespace_of(thread) or 'default'}; the folder wins"
        )
    kept = {key: item for key, item in front.items() if key not in (*MOVED, *DROPPED)}
    return {
        "metadata": value, "origin": markdown(kept, body) if stale_origin else None,
        "event": not has_migrated, "notes": notes,
    }


def run(root: Path, by: dict[str, str], *, dry_run: bool = False) -> list[dict[str, Any]]:
    results = []
    for thread in iter_threads(root):
        identifier = thread.name.split("-", 1)[0]
        try:
            change = plan(thread)
        except (ThreadError, KeyError, ValueError, OSError) as error:
            results.append({"thread": identifier, "status": "failed", "error": str(error)})
            continue
        if change is None:
            results.append({"thread": identifier, "status": "already migrated"})
            continue
        entry = {"thread": identifier, "status": "migrated", "metadata": change["metadata"], "notes": change["notes"]}
        if dry_run:
            entry["status"] = "would migrate"
            results.append(entry)
            continue
        metadata.write(thread, change["metadata"])
        if change["origin"] is not None:
            atomic_text(thread / "origin.md", change["origin"])
        if change["event"]:
            events.append(thread, "migrated", {"metadata": change["metadata"]}, by, reopen=False)
        entry["commit"] = gitops.commit(
            root, f"migrate {identifier}: thread.yml holds the metadata, origin.md the narrative", [thread],
        )
        results.append(entry)
    return results
