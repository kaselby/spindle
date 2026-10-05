"""The task board: commands, hand-edit diffing, and promotion."""

from __future__ import annotations

import json

import pytest
import yaml

from spindle import events, metadata, store


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

    # D2: children are flat under threads/; parentage and the task it came
    # from live in the child's thread.yml, not in its origin.
    assert child.parent.name == "threads"
    values = metadata.read(child)
    assert values["parent"] == identifier and values["from-task"] == task["id"]
    front, _ = store.parse_frontmatter((child / "origin.md").read_text(encoding="utf-8"))
    assert "parent" not in front and "from-task" not in front

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


def test_thread_before_verb_is_accepted(root, make_thread, run):
    identifier = make_thread()
    path = store.resolve_thread(root, identifier)

    # task <thread> add "text"
    first = json.loads(run("task", identifier, "add", "write the tests", "--root", root, "--json").out)
    second = json.loads(run("task", identifier, "add", "run the tests", "--root", root, "--json").out)
    third = json.loads(run("task", identifier, "add", "ship it", "--root", root, "--json").out)
    # task <thread> list
    assert run("task", identifier, "list", "--root", root).out.splitlines() == [
        f"- [ ] {first['id']} write the tests",
        f"- [ ] {second['id']} run the tests",
        f"- [ ] {third['id']} ship it",
    ]
    # task <thread> close <task>, with an option ahead of the words
    assert run("task", "--root", root, identifier, "close", first["id"]).code == 0
    # task <thread> <task> close
    assert run("task", identifier, second["id"], "close", "--root", root).code == 0
    # task <thread> <task> remove
    assert run("task", identifier, third["id"], "remove", "--root", root).code == 0
    assert f"[x] {first['id']}" in run("task", identifier, "list", "--all", "--root", root).out
    assert [(task["id"], task["done"]) for task in _board(path)] == [(first["id"], True), (second["id"], True)]
    assert [event["type"] for event in events.read_events(path)][-6:] == [
        "task-added", "task-added", "task-added", "task-closed", "task-closed", "task-removed",
    ]


def test_task_order_only_moves_unambiguous_forms():
    from spindle.cli import _task_order

    canonical = ["task", "close", "abc123", "t1234", "--root", "/r"]
    assert _task_order(canonical) == canonical
    assert _task_order(["task", "abc123", "close", "t1234"]) == ["task", "close", "abc123", "t1234"]
    assert _task_order(["task", "abc123", "t1234", "close"]) == ["task", "close", "abc123", "t1234"]
    assert _task_order(["task", "--by", "s2", "abc123", "list"]) == ["task", "list", "--by", "s2", "abc123"]
    # `remove` is also a well-formed thread id: a leading verb is always the verb.
    assert _task_order(["task", "remove", "close", "t1234"]) == ["task", "remove", "close", "t1234"]
    # Two verbs after the thread: close task `remove`, or remove task `close`?
    assert _task_order(["task", "abc123", "close", "remove"]) == ["task", "abc123", "close", "remove"]
    # A verb in any other place, or a help request, is left to argparse.
    assert _task_order(["task", "abc123", "t1234", "add"]) == ["task", "abc123", "t1234", "add"]
    assert _task_order(["task", "abc123", "close", "--help"]) == ["task", "abc123", "close", "--help"]
    # A value option's argument is never taken for the verb.
    assert _task_order(["task", "abc123", "--by", "list", "close", "t1"]) == \
        ["task", "close", "abc123", "--by", "list", "t1"]


def test_ambiguous_task_order_still_errors(root, make_thread, run, capsys):
    identifier = make_thread()
    added = json.loads(run("task", "add", identifier, "keep me", "--root", root, "--json").out)
    with pytest.raises(SystemExit) as exited:
        run("task", identifier, "close", "remove", "--root", root)
    assert exited.value.code == 2
    err = capsys.readouterr().err
    assert f"invalid choice: '{identifier}'" in err
    assert "usage: thread task [-h] <add|close|remove|list>" in err
    assert run("task", "list", identifier, "--root", root).out.splitlines() == [f"- [ ] {added['id']} keep me"]
