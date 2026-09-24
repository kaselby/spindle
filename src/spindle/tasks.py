"""Hand-editable task board and its event diff."""

from __future__ import annotations

import hashlib
import secrets
from pathlib import Path
from typing import Any

from . import events
from .store import ThreadError, read_yaml, write_yaml


def _id(thread: Path) -> str:
    return thread.name.split("-", 1)[0]


def read(thread: Path) -> list[dict[str, Any]]:
    value = read_yaml(thread / "tasks.yml", {"tasks": []})
    if not isinstance(value, dict) or not isinstance(value.get("tasks"), list):
        raise ThreadError(f"{thread.name}/tasks.yml must contain a `tasks` list; fix the file, or restore it from git.")
    for task in value["tasks"]:
        if not isinstance(task, dict) or not str(task.get("text", "")).strip():
            raise ThreadError(f"{thread.name}/tasks.yml has a task with no text; fix the file. Use `thread task` to change tasks.")
        if "\n" in task["text"] or len(task["text"]) > 200:
            raise ThreadError(
                f"{thread.name}/tasks.yml has a task longer than one line of 200 characters; fix the file. "
                "Use `thread task` to change tasks."
            )
    return value["tasks"]


def _hash(thread: Path) -> str:
    return hashlib.sha256((thread / "tasks.yml").read_bytes()).hexdigest()


def _new_id(used: set[str]) -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyz0123456789"
    while True:
        value = "t" + "".join(secrets.choice(alphabet) for _ in range(4))
        if value not in used:
            return value


def snapshot(log: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for event in log:
        payload = event.get("payload", {})
        task_id = payload.get("task")
        if event["type"] == "task-added" and task_id:
            result[task_id] = {"id": task_id, "text": payload.get("text", ""), "done": False}
        elif event["type"] == "task-closed" and task_id in result:
            result[task_id]["done"] = True
        elif event["type"] == "task-removed" and task_id:
            result.pop(task_id, None)
        elif event["type"] == "task-edited" and task_id in result:
            for field in ("text", "promoted"):
                if field in payload:
                    result[task_id][field] = payload[field]
    return result


def _store_hash(thread: Path) -> None:
    cache = events.regenerate(thread)
    cache["tasks-hash"] = _hash(thread)
    write_yaml(thread / "thread.yml", cache)


def sync(thread: Path, by: dict[str, str]) -> list[dict[str, Any]]:
    """Diff the board against task events, assigning ids to hand additions."""
    cache = read_yaml(thread / "thread.yml", {})
    current_hash = _hash(thread)
    if cache.get("tasks-hash") == current_hash:
        return []
    board = read(thread)
    log = events.read_events(thread)
    previous = snapshot(log)
    used = set(previous)
    rewritten = False
    for task in board:
        if not task.get("id"):
            task["id"] = _new_id(used)
            used.add(task["id"])
            rewritten = True
        task.setdefault("done", False)
    if len({task["id"] for task in board}) != len(board):
        raise ThreadError(f"{thread.name}/tasks.yml has duplicate task ids; fix the file. Use `thread task` to change tasks.")
    if rewritten:
        write_yaml(thread / "tasks.yml", {"tasks": board})

    emitted: list[dict[str, Any]] = []
    current = {task["id"]: task for task in board}
    for task_id, task in current.items():
        old = previous.get(task_id)
        if old is None:
            emitted.append(events.append(thread, "task-added", {
                "task": task_id, "text": task["text"], "hand-edit": True,
            }, by))
            if task.get("done"):
                emitted.append(events.append(thread, "task-closed", {
                    "task": task_id, "text": task["text"], "hand-edit": True,
                }, by))
            continue
        changed = any(task.get(field) != old.get(field) for field in ("text", "promoted"))
        if changed:
            payload: dict[str, Any] = {"task": task_id, "text": task["text"], "hand-edit": True}
            if task.get("promoted"):
                payload["promoted"] = task["promoted"]
            emitted.append(events.append(thread, "task-edited", payload, by))
        if bool(task.get("done")) != bool(old.get("done")):
            kind = "task-closed" if task.get("done") else "task-added"
            emitted.append(events.append(thread, kind, {
                "task": task_id, "text": task["text"], "hand-edit": True,
            }, by))
    for task_id, old in previous.items():
        if task_id not in current:
            emitted.append(events.append(thread, "task-removed", {
                "task": task_id, "text": old["text"], "hand-edit": True,
            }, by))
    _store_hash(thread)
    return emitted


def add(
    thread: Path, text: str, by: dict[str, str], *, from_thread: str | None = None
) -> dict[str, Any]:
    """`from_thread` marks a task rolled up from a merged child; the id is
    fresh, because ids are per-board, and `from` carries the lineage."""
    if not text.strip():
        raise ThreadError("task text is empty; say what the step is.")
    if "\n" in text or len(text) > 200:
        raise ThreadError(
            f"task text is {len(text)} characters{' over several lines' if chr(10) in text else ''}; "
            "a task is one line of at most 200. If it needs more room, it may be a subthread "
            "(`thread task add`, then `thread promote`)."
        )
    board = read(thread)
    task_id = _new_id({task.get("id", "") for task in board})
    task = {"id": task_id, "text": text, "done": False}
    board.append(task)
    write_yaml(thread / "tasks.yml", {"tasks": board})
    payload = {"task": task_id, "text": text}
    if from_thread:
        payload["from"] = from_thread
    events.append(thread, "task-added", payload, by)
    _store_hash(thread)
    return task


def close(thread: Path, task_id: str, by: dict[str, str]) -> dict[str, Any]:
    board = read(thread)
    task = next((item for item in board if item.get("id") == task_id), None)
    if task is None:
        raise ThreadError(f"no task {task_id} in {_id(thread)}. `thread task list {_id(thread)} --all` shows task ids.")
    if task.get("done"):
        raise ThreadError(f"task {task_id} is already closed; nothing to do.")
    task["done"] = True
    write_yaml(thread / "tasks.yml", {"tasks": board})
    events.append(thread, "task-closed", {"task": task_id, "text": task["text"]}, by)
    _store_hash(thread)
    return task


def remove(thread: Path, task_id: str, by: dict[str, str]) -> dict[str, Any]:
    board = read(thread)
    task = next((item for item in board if item.get("id") == task_id), None)
    if task is None:
        raise ThreadError(f"no task {task_id} in {_id(thread)}. `thread task list {_id(thread)} --all` shows task ids.")
    board.remove(task)
    write_yaml(thread / "tasks.yml", {"tasks": board})
    events.append(thread, "task-removed", {"task": task_id, "text": task["text"]}, by)
    _store_hash(thread)
    return task


def promote(thread: Path, task_id: str, child_id: str, by: dict[str, str]) -> None:
    board = read(thread)
    task = next((item for item in board if item.get("id") == task_id), None)
    if task is None:
        raise ThreadError(f"no task {task_id} in {_id(thread)}. `thread task list {_id(thread)} --all` shows task ids.")
    if task.get("promoted"):
        raise ThreadError(f"task {task_id} was already promoted to thread {task['promoted']}; work there instead (`thread view {task['promoted']}`).")
    task["promoted"] = child_id
    write_yaml(thread / "tasks.yml", {"tasks": board})
    events.append(thread, "task-edited", {
        "task": task_id, "text": task["text"], "promoted": child_id,
    }, by)
    _store_hash(thread)
