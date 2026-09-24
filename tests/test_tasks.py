"""The task board: commands, hand-edit diffing, and promotion."""

from __future__ import annotations

import json

import yaml

from spindle import events, store


def _board(path):
    return yaml.safe_load((path / "tasks.yml").read_text(encoding="utf-8"))["tasks"]


def test_add_close_remove_list(root, make_thread, run):
    identifier = make_thread()
    path = store.resolve_thread(root, identifier)

    added = json.loads(run("task", "add", identifier, "write the tests", "--root", root, "--json").out)
    assert added["done"] is False
    other = json.loads(run("task", "add", identifier, "run the tests", "--root", root, "--json").out)

    listing = run("task", "list", identifier, "--root", root)
    assert listing.out.splitlines() == [
        f"- [ ] {added['id']} write the tests",
        f"- [ ] {other['id']} run the tests",
    ]

    assert run("task", "close", identifier, added["id"], "--root", root).code == 0
    assert run("task", "list", identifier, "--root", root).out.splitlines() == [
        f"- [ ] {other['id']} run the tests"
    ]
    assert f"[x] {added['id']}" in run("task", "list", identifier, "--root", root, "--all").out

    assert run("task", "remove", identifier, other["id"], "--root", root).code == 0
    assert [task["id"] for task in _board(path)] == [added["id"]]
    assert [event["type"] for event in events.read_events(path)][-4:] == [
        "task-added", "task-added", "task-closed", "task-removed",
    ]
    assert run("task", "close", identifier, "tzzzz", "--root", root).code == 2


def test_hand_edits_are_diffed_into_the_log_on_the_next_command(root, make_thread, run):
    identifier = make_thread()
    path = store.resolve_thread(root, identifier)
    kept = json.loads(run("task", "add", identifier, "kept task", "--root", root, "--json").out)
    doomed = json.loads(run("task", "add", identifier, "doomed task", "--root", root, "--json").out)
    tip_before = events.tip(path)

    # A human edits the board directly: one addition (no id), one close,
    # one rewording, one removal.
    (path / "tasks.yml").write_text(
        yaml.safe_dump({"tasks": [
            {"id": kept["id"], "text": "kept task, reworded", "done": True},
            {"text": "hand-added task"},
        ]}, sort_keys=False),
        encoding="utf-8",
    )

    result = run("task", "list", identifier, "--root", root)
    assert result.code == 0

    log = events.read_events(path)
    assert events.tip(path) != tip_before
    new = log[[event["id"] for event in log].index(tip_before) + 1 :]
    by_type = {}
    for event in new:
        by_type.setdefault(event["type"], []).append(event["payload"])
    assert all(payload["hand-edit"] for payloads in by_type.values() for payload in payloads)
    assert by_type["task-edited"][0]["task"] == kept["id"]
    assert by_type["task-edited"][0]["text"] == "kept task, reworded"
    assert [payload["task"] for payload in by_type["task-closed"]] == [kept["id"]]
    assert [payload["task"] for payload in by_type["task-removed"]] == [doomed["id"]]
    assert len(by_type["task-added"]) == 1  # the id-less hand addition

    # The tool assigned the hand-added task an id and rewrote the file once.
    board = _board(path)
    assigned = next(task for task in board if task["text"] == "hand-added task")
    assert assigned["id"] == by_type["task-added"][0]["task"]
    assert assigned["id"].startswith("t") and len(assigned["id"]) == 5

    # Idempotent: a second command emits nothing further.
    tip_after = events.tip(path)
    assert run("task", "list", identifier, "--root", root).code == 0
    assert events.tip(path) == tip_after


def test_promote_creates_a_subthread_and_marks_the_task(root, make_thread, run, origin):
    identifier = make_thread("Parent thread")
    parent = store.resolve_thread(root, identifier)
    task = json.loads(run("task", "add", identifier, "do the sub-work", "--root", root, "--json").out)

    result = run(
        "promote", identifier, task["id"], "Sub-work", "--origin", origin, "--root", root, "--json"
    )
    assert result.code == 0, result.err
    child_id = json.loads(result.out)["id"]
    child = store.resolve_thread(root, child_id)

    # D2: children are flat under active/, parentage lives in the log and the fold.
    assert child.parent.name == "threads"
    assert yaml.safe_load((child / "thread.yml").read_text(encoding="utf-8"))["parent"] == identifier
    metadata, _ = store.parse_frontmatter((child / "origin.md").read_text(encoding="utf-8"))
    assert metadata["parent"] == identifier and metadata["from-task"] == task["id"]

    created = [event for event in events.read_events(parent) if event["type"] == "child-created"]
    assert created[0]["payload"] == {
        "child": child_id, "title": "Sub-work", "from-task": task["id"]
    }

    # The task stays on the board, marked promoted.
    board = _board(parent)
    assert board[0]["promoted"] == child_id
    assert f"→ see thread {child_id}" in run("task", "list", identifier, "--root", root).out
    assert f"- {child_id} — Sub-work (active)" in run("view", identifier, "--root", root).out
    # A second promotion is refused *before* a stray child thread is created.
    again = run("promote", identifier, task["id"], "Again", "--origin", origin, "--root", root)
    assert again.code == 2 and "already promoted" in again.err
    assert len(list((root / "default" / "threads").iterdir())) == 2
