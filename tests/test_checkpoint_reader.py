"""Reading past checkpoints in full: `replay --checkpoint cNNNN` and `--checkpoints`."""

from __future__ import annotations

import json

FIRST = "First headline.\n\n## Status\nEarly state.\n"
SECOND = "Second headline.\n\n## Status\nLater state.\n\n## Aside\nKept as written.\n"


def _two(run, root, body, make_thread):
    identifier = make_thread("Reader")
    assert run("checkpoint", identifier, body(FIRST), "--root", root).code == 0
    assert run("note", identifier, "between them", "--root", root).code == 0
    assert run("checkpoint", identifier, body(SECOND), "--root", root).code == 0
    return identifier


def test_one_checkpoint_in_full(root, run, body, make_thread):
    identifier = _two(run, root, body, make_thread)
    out = run("replay", identifier, "--checkpoint", "c0001", "--root", root).out
    assert out.startswith("# Checkpoint c0001 (")
    assert "Early state." in out and "Later state." not in out
    # Its event log answers "what happened before c0001"; c0002's covers the note.
    later = run("replay", identifier, "--checkpoint", "c0002", "--root", root).out
    assert "between them" in later and "Kept as written." in later
    assert "---\nid:" not in later  # no raw frontmatter


def test_all_checkpoints_oldest_first(root, run, body, make_thread):
    identifier = _two(run, root, body, make_thread)
    out = run("replay", identifier, "--checkpoints", "--root", root).out
    assert out.index("# Checkpoint c0001") < out.index("# Checkpoint c0002")


def test_unknown_checkpoint_lists_the_real_ones(root, run, body, make_thread):
    identifier = _two(run, root, body, make_thread)
    result = run("replay", identifier, "--checkpoint", "c0009", "--root", root)
    assert result.code == 2 and "c0001, c0002" in result.err


def test_checkpoint_flags_refuse_event_filters(root, run, body, make_thread):
    identifier = _two(run, root, body, make_thread)
    result = run("replay", identifier, "--checkpoints", "--type", "note", "--root", root)
    assert result.code == 2 and "one or the other" in result.err


def test_json_and_view_pointer(root, run, body, make_thread):
    identifier = _two(run, root, body, make_thread)
    records = json.loads(run("replay", identifier, "--checkpoint", "c0002", "--root", root, "--json").out)
    assert [record["id"] for record in records] == ["c0002"] and "Later state." in records[0]["body"]
    view = run("view", identifier, "--root", root).out
    assert f"`thread replay {identifier} --checkpoint cNNNN` shows any of them in full" in view
