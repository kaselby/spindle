"""Threads arranged as a tree, shared by `thread list` and the startup snapshot.

Per namespace: subthreads sit under their parent, oldest first; top-level trees
are ordered by the most recent activity anywhere in them. A thread whose parent
isn't in the set (ended, left out, or in another namespace) stays at the top
level and is marked an orphan so the caller can name its parent. Nothing is cut,
and a parent cycle never loops: those threads are listed flat.
"""

from __future__ import annotations

from typing import NamedTuple

from .events import is_activity


class Row(NamedTuple):
    cache: dict
    depth: int
    orphan: bool  # has a parent that isn't nested above it


def last_activity(log: list[dict], cache: dict) -> str:
    """When someone last wrote to the thread. The doctor's own events (marking it
    inactive, expiring a claim) aren't activity, or every inactive thread would
    look as recent as the last doctor pass."""
    for event in reversed(log):
        if is_activity(event):
            return event["ts"]
    return cache["created"]


def arrange(caches: list[dict], seen: dict[str, str]) -> dict[str, list[Row]]:
    """Rows per namespace ('' is the default). ``seen`` maps id to last activity."""
    by_id = {cache["id"]: cache for cache in caches}
    children: dict[str, list[dict]] = {}
    tops: list[dict] = []
    for cache in sorted(caches, key=lambda c: (c["created"], c["id"])):
        parent = by_id.get(cache.get("parent") or "")
        # Nest only within a namespace: each namespace is its own group.
        if parent is not None and parent is not cache and parent.get("namespace") == cache.get("namespace"):
            children.setdefault(parent["id"], []).append(cache)
        else:
            tops.append(cache)

    def latest(cache: dict, visiting: frozenset = frozenset()) -> str:
        if cache["id"] in visiting:  # a parent cycle
            return ""
        inner = visiting | {cache["id"]}
        return max([seen[cache["id"]], *(latest(child, inner) for child in children.get(cache["id"], []))])

    groups: dict[str, list[Row]] = {}
    placed: set[str] = set()

    def walk(cache: dict, depth: int, rows: list[Row]) -> None:
        if cache["id"] in placed:  # a parent cycle; never loop
            return
        placed.add(cache["id"])
        rows.append(Row(cache, depth, depth == 0 and bool(cache.get("parent"))))
        for child in children.get(cache["id"], []):
            walk(child, depth + 1, rows)

    for cache in sorted(tops, key=latest, reverse=True):
        walk(cache, 0, groups.setdefault(cache.get("namespace") or "", []))
    # Threads caught in a parent cycle have no top; list them flat rather than lose them.
    for cache in caches:
        if cache["id"] not in placed:
            walk(cache, 0, groups.setdefault(cache.get("namespace") or "", []))
    return groups
