"""Lifecycle: merge, complete, drop, reopen, revise, archive, view --deep."""

from __future__ import annotations

import itertools
import json
import shutil
from datetime import datetime, timedelta, timezone

import pytest
import yaml

from conftest import git

from spindle import events, lifecycle, metadata, store, summary

PARENT_BODY = "Parent synthesis.\n\n## Status\nThe parent holds.\n"
CHILD_BODY = "Child synthesis.\n\nA second outline line.\n\n## Status\nThe child is done.\n"


def _merge_text(child, narrative="The child ran the whole study and finished clean.",
                status="The parent now holds the child's result."):
    return f"Merged {child}: the result is in.\n\n## From {child}\n{narrative}\n\n## Status\n{status}\n"


def _cp(run, root, body, identifier, text):
    result = run("checkpoint", identifier, body(text), "--root", root)
    assert result.code == 0, result.err


def _log(path):
    return events.read_events(path)


def _types(path):
    return [event["type"] for event in _log(path)]


def _task_ids(run, root, identifier):
    listed = run("task", "list", identifier, "--root", root, "--json")
    return [task["id"] for task in json.loads(listed.out)]


@pytest.fixture
def family(root, run, body, make_thread):
    """A parent and a child, each with one checkpoint, both clean."""
    parent = make_thread("Parent thread")
    child = make_thread("Child thread", "--parent", parent)
    _cp(run, root, body, parent, PARENT_BODY)
    _cp(run, root, body, child, CHILD_BODY)
    return {
        "parent": parent, "child": child,
        "parent_path": store.resolve_thread(root, parent),
        "child_path": store.resolve_thread(root, child),
    }


@pytest.fixture
def loaded(root, run, body, make_thread):
    """The brief's merge scenario: 3 artifacts (one with a read-when), 3 tasks in the child."""
    parent = make_thread("Parent thread")
    child = make_thread("Child thread", "--parent", parent)
    path = store.resolve_thread(root, child)
    (path / "artifacts" / "guide.md").write_text("# how to work on this\n", encoding="utf-8")
    (path / "artifacts" / "kept.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    (path / "artifacts" / "left.csv").write_text("c,d\n3,4\n", encoding="utf-8")
    assert run("register", child, "artifacts/guide.md", "--purpose", "orientation",
               "--read-when", "before touching the harness", "--root", root).code == 0
    assert run("register", child, "artifacts/kept.csv",
               "--purpose", "the numbers that matter", "--root", root).code == 0
    assert run("register", child, "artifacts/left.csv",
               "--purpose", "intermediate output", "--root", root).code == 0
    for text in ("roll this one up", "leave this one", "and this one"):
        assert run("task", "add", child, text, "--root", root).code == 0
    _cp(run, root, body, parent, PARENT_BODY)
    _cp(run, root, body, child, CHILD_BODY)
    return {
        "parent": parent, "child": child,
        "parent_path": store.resolve_thread(root, parent), "child_path": path,
        "tasks": _task_ids(run, root, child),
    }


# ── merge ────────────────────────────────────────────────────────────────────


def test_merge_copies_points_rolls_up_and_commits_once(root, run, body, loaded):
    parent, child = loaded["parent"], loaded["child"]
    parent_path, child_path = loaded["parent_path"], loaded["child_path"]
    before = _log(child_path)
    commits = len(git(root, "log", "--oneline").splitlines())

    result = run("merge", child, "--promote", "artifacts/kept.csv", "artifacts/guide.md",
                 "--tasks", loaded["tasks"][0], "--body", body(_merge_text(child)), "--root", root, "--json")
    assert result.code == 0, result.err
    value = json.loads(result.out)

    # Files landed at the same relative paths, with the same bytes.
    assert (parent_path / "artifacts" / "guide.md").read_text() == "# how to work on this\n"
    assert (parent_path / "artifacts" / "kept.csv").read_text() == "a,b\n1,2\n"
    assert not (parent_path / "artifacts" / "left.csv").exists()

    registers = [e for e in _log(parent_path) if e["type"] == "register"]
    copied = {e["payload"]["registration"]["path"]: e["payload"] for e in registers
              if e["payload"].get("from")}
    assert set(copied) == {"artifacts/guide.md", "artifacts/kept.csv"}
    assert all(payload["from"] == f"{child}@c0001" for payload in copied.values())
    assert copied["artifacts/guide.md"]["registration"]["read-when"] == "before touching the harness"
    pointers = [e["payload"] for e in registers if e["payload"].get("pointer")]
    assert [p["pointer"] for p in pointers] == [f"{child}:artifacts/left.csv@c0001"]

    # One task rolled up with lineage; the child's board is untouched.
    added = [e for e in _log(parent_path) if e["type"] == "task-added"]
    assert [e["payload"]["text"] for e in added] == ["roll this one up"]
    assert added[0]["payload"]["from"] == child
    board = yaml.safe_load((store.resolve_thread(root, child) / "tasks.yml").read_text())
    assert [task["text"] for task in board["tasks"]] == [
        "roll this one up", "leave this one", "and this one"
    ]
    assert not any(task.get("done") for task in board["tasks"])

    merged = [e for e in _log(parent_path) if e["type"] == "child-merged"]
    assert len(merged) == 1
    assert merged[0]["payload"] == {
        "child": child, "checkpoint": "c0001",
        "promoted": ["artifacts/kept.csv", "artifacts/guide.md"],
        "pointers": ["artifacts/left.csv"],
        "tasks": [added[0]["payload"]["task"]], "forced": False,
    }

    # The forced checkpoint: the author's headline, narrative and Status, with
    # the tool's facts under the narrative.
    text = (parent_path / "checkpoints" / "c0002.md").read_text(encoding="utf-8")
    metadata, rendered = store.parse_frontmatter(text)
    assert metadata["forced-by"] == "merge"
    assert metadata["headline"] == f"Merged {child}: the result is in."
    assert rendered.startswith(f"Merged {child}: the result is in.\n\n## From {child}\n"
                               "The child ran the whole study and finished clean.\n\n"
                               "Recorded by the tool at merge:\n")
    from_section = rendered.split(f"## From {child}\n")[1].split("\n## ")[0]
    added_id = added[0]["payload"]["task"]
    assert f'- Final checkpoint: c0001, "Child synthesis."' in from_section
    assert f"- Promoted to {parent}: artifacts/kept.csv, artifacts/guide.md" in from_section
    assert f'- Tasks moved to {parent}: "roll this one up" (now {added_id})' in from_section
    assert f"- Left in {child}: 1 artifact, 2 open tasks" in from_section
    status = rendered.split("## Status\n")[1].strip()
    assert status == "The parent now holds the child's result."
    assert value["checkpoint"] == "c0002"

    # The child: two new events, nothing else, and it moved to the archive.
    archived = store.resolve_thread(root, child)
    assert archived.parent.parent.name == "archived"
    assert archived.parent.name == events.timestamp()[:7]
    after = _log(archived)
    assert [e["id"] for e in after[: len(before)]] == [e["id"] for e in before]
    assert [e["type"] for e in after[len(before):]] == ["merged-into", "state-changed"]
    assert after[-2]["payload"] == {"parent": parent, "checkpoint": "c0002"}
    assert after[-1]["payload"] == {"from": "active", "to": "merged"}
    assert events.state(archived)["state"] == "merged"

    # Exactly one new commit, touching both folders.
    log = git(root, "log", "--oneline").splitlines()
    assert len(log) == commits + 1
    assert log[0].endswith(f"merge {child}@c0001 into {parent}@c0002: Merged {child}: the result is in.")
    touched = git(root, "show", "--name-only", "--format=", "HEAD").split()
    assert any(name.startswith(f"default/threads/{parent}") for name in touched)
    assert any(f"{child}" in name for name in touched)
    assert all(parent in name or child in name for name in touched)



def test_merge_index_renders_pointers_as_arrows(root, run, body, loaded):
    child = loaded["child"]
    assert run("merge", child, "--promote", "artifacts/guide.md", "--body", body(_merge_text(child)),
               "--root", root).code == 0
    index = (loaded["parent_path"] / "index.md").read_text(encoding="utf-8")
    assert f"- → **{child}:artifacts/left.csv** — intermediate output" in index
    assert "- **artifacts/guide.md** (" in index and ") — orientation\n  *Read when:* before touching the harness" in index


def test_the_view_counts_pointers_instead_of_listing_them(root, run, body, loaded):
    parent, child = loaded["parent"], loaded["child"]
    assert run("merge", child, "--promote", "artifacts/guide.md", "--body", body(_merge_text(child)),
               "--root", root).code == 0
    view = run("view", parent, "--root", root).out
    assert "- **artifacts/guide.md** (" in view and ") — orientation" in view  # promoted: the parent's own
    assert f"{child}:artifacts" not in view
    index_path = loaded["parent_path"] / "index.md"
    assert f"*2 artifacts remain in merged subthreads; `{index_path}` lists them.*" in view



def test_merge_refuses_a_thread_with_no_parent(root, run, body, make_thread):
    identifier = make_thread("Root thread")
    _cp(run, root, body, identifier, PARENT_BODY)
    result = run("merge", identifier, "--root", root)
    assert result.code == lifecycle.NO_PARENT
    assert "has no parent" in result.err


def test_merge_refuses_a_dirty_child(root, run, family):
    assert run("note", family["child"], "still thinking", "--root", root).code == 0
    result = run("merge", family["child"], "--root", root)
    assert result.code == lifecycle.DIRTY
    assert result.err.startswith(f"can't merge yet: the child, {family['child']}, has 1 event since its last checkpoint")


def test_merge_refuses_a_dirty_parent(root, run, family):
    assert run("note", family["parent"], "mid-thought", "--root", root).code == 0
    result = run("merge", family["child"], "--root", root)
    assert result.code == lifecycle.PARENT_DIRTY
    assert result.err.startswith(f"can't merge yet: the parent, {family['parent']}, has 1 event since its last checkpoint")


def test_merge_refuses_open_grandchildren_and_force_reparents_them(root, run, body, family, make_thread):
    grandchild = make_thread("Grandchild thread", "--parent", family["child"])
    _cp(run, root, body, family["child"], CHILD_BODY)  # child-created made it dirty

    refused = run("merge", family["child"], "--root", root)
    assert refused.code == lifecycle.OPEN_CHILDREN
    assert grandchild in refused.err

    assert run("merge", family["child"], "--force", "--body", body(_merge_text(family["child"])),
               "--root", root).code == 0
    moved = store.resolve_thread(root, grandchild)
    reparented = [e for e in _log(moved) if e["type"] == "reparented"]
    assert reparented[0]["payload"] == {"from": family["child"], "to": family["parent"]}
    adopted = [e for e in _log(family["parent_path"]) if e["type"] == "child-adopted"]
    assert adopted[0]["payload"]["child"] == grandchild
    # Both folds agree the grandchild now hangs off the parent.
    assert metadata.read(moved)["parent"] == family["parent"]
    children = summary.children(root, family["parent"])
    assert {child["id"] for child in children} == {family["child"], grandchild}
    merged = [e for e in _log(family["parent_path"]) if e["type"] == "child-merged"][0]
    assert merged["payload"]["forced"] is True


def test_merge_refuses_an_unregistered_promote_path(root, run, loaded):
    result = run("merge", loaded["child"], "--promote", "artifacts/nope.csv", "--root", root)
    assert result.code == lifecycle.NOT_REGISTERED
    assert "isn't one. Registered:" in result.err


def test_merge_refuses_a_promote_path_the_parent_already_has(root, run, loaded):
    (loaded["parent_path"] / "artifacts" / "guide.md").write_text("mine\n", encoding="utf-8")
    result = run("merge", loaded["child"], "--promote", "artifacts/guide.md", "--root", root)
    assert result.code == lifecycle.CONFLICT
    assert "artifacts/guide.md" in result.err
    # --force does not override a conflict.
    forced = run("merge", loaded["child"], "--promote", "artifacts/guide.md", "--force", "--root", root)
    assert forced.code == lifecycle.CONFLICT
    assert (loaded["parent_path"] / "artifacts" / "guide.md").read_text() == "mine\n"


def test_merge_refuses_an_unknown_task_id(root, run, loaded):
    result = run("merge", loaded["child"], "--tasks", "tzzzz", "--root", root)
    assert result.code == lifecycle.UNKNOWN_TASK
    assert "no task tzzzz in" in result.err


def test_merge_rolls_back_copied_files_when_an_append_fails(root, run, body, loaded, monkeypatch):
    parent_path = loaded["parent_path"]
    tip = events.tip(parent_path)
    child_tip = events.tip(loaded["child_path"])
    head = git(root, "rev-parse", "HEAD").strip()

    def explode(*args, **kwargs):
        raise RuntimeError("disk on fire")

    monkeypatch.setattr(events, "append", explode)
    with pytest.raises(RuntimeError):
        run("merge", loaded["child"], "--promote", "artifacts/guide.md", "artifacts/kept.csv",
            "--body", body(_merge_text(loaded["child"])), "--root", root)
    monkeypatch.undo()

    assert not (parent_path / "artifacts" / "guide.md").exists()
    assert not (parent_path / "artifacts" / "kept.csv").exists()
    assert (parent_path / "artifacts").is_dir()  # the layout folder itself stays
    assert events.tip(parent_path) == tip
    assert events.tip(loaded["child_path"]) == child_tip
    assert git(root, "rev-parse", "HEAD").strip() == head
    assert loaded["child_path"].parent.name == "threads"


def test_merge_without_body_prints_the_template(root, run, loaded):
    parent, child = loaded["parent"], loaded["child"]
    head = git(root, "rev-parse", "HEAD").strip()
    result = run("merge", child, "--promote", "artifacts/guide.md", "--tasks", loaded["tasks"][0], "--root", root)
    assert result.code == 2 and result.err == ""
    template = result.out
    assert f"thread merge {child} --body <file> --promote artifacts/guide.md --tasks {loaded['tasks'][0]}" in template
    assert "completion-and-merging.md" in template
    # The headline is suggested and is the only line before ## From.
    before = store.strip_comments(template).split(f"## From {child}")[0]
    assert [line for line in before.splitlines() if line.strip()] == [f"Merged {child}: Child synthesis."]
    # The facts are visible while writing.
    assert '- Final checkpoint: c0001, "Child synthesis."' in template
    assert f"- Promoted to {parent}: artifacts/guide.md" in template
    assert f'- Tasks moved to {parent}: "roll this one up"' in template
    assert f"- Left in {child}: 2 artifacts, 2 open tasks" in template
    assert "How does merging this subthread change the parent's state?" in template
    assert "Write it against the parent's origin." in template
    assert "## Inherited" in template
    # Nothing happened.
    assert git(root, "rev-parse", "HEAD").strip() == head
    assert not (loaded["parent_path"] / "checkpoints" / "c0002.md").exists()
    assert loaded["child_path"].parent.name == "threads"


def test_merge_template_filled_in_merges_without_duplicating_the_facts(root, run, body, loaded):
    parent, child = loaded["parent"], loaded["child"]
    template = run("merge", child, "--tasks", loaded["tasks"][0], "--root", root).out
    filled = template.replace(
        f"## From {child}\n", f"## From {child}\nIt measured everything and left one loose end.\n", 1
    ).replace("## Status\n", "## Status\nThe parent can use the numbers now.\n", 1)
    result = run("merge", child, "--tasks", loaded["tasks"][0], "--body", body(filled), "--root", root)
    assert result.code == 0, result.err
    written = (loaded["parent_path"] / "checkpoints" / "c0002.md").read_text(encoding="utf-8")
    assert "<!--" not in written
    assert written.count("Recorded by the tool at merge:") == 1
    assert written.count("- Final checkpoint:") == 1
    assert "(now t" in written  # the stored copy is the tool's, with the parent's task id
    _, rendered = store.parse_frontmatter(written)
    narrative = rendered.split(f"## From {child}\n")[1].split("Recorded by the tool")[0].strip()
    assert narrative == "It measured everything and left one loose end."
    # The view shows From like any other section of the current checkpoint.
    view = run("view", parent, "--root", root).out
    assert f"## From {child}" in view and "It measured everything" in view
    assert "Recorded by the tool at merge:" in view


def test_merge_validates_an_authored_body(root, run, body, family):
    child = family["child"]
    written = family["parent_path"] / "checkpoints" / "c0002.md"

    def refused(text):
        result = run("merge", child, "--body", body(text), "--root", root)
        assert result.code == 2
        assert "completion-and-merging.md" in result.err
        assert not written.exists()
        return result.err

    long_headline = "h" * 130 + f"\n\n## From {child}\nDid it.\n\n## Status\nfine.\n"
    assert "headline (the first line) is 130 characters; the limit is 120" in refused(long_headline)

    outline = f"Merged it.\n\nAn outline line.\n\n## From {child}\nDid it.\n\n## Status\nfine.\n"
    assert "has only its headline before" in refused(outline)

    old_shape = "Absorbed the child.\n\n## Status\nParent carries it now.\n"
    err = refused(old_shape)
    assert f"needs a `## From {child}` section" in err and f"`thread merge {child}` without --body" in err

    wrong_child = "Merged it.\n\n## From zzzz\nDid it.\n\n## Status\nfine.\n"
    assert "found `## from zzzz`" in refused(wrong_child)

    no_status = f"Merged it.\n\n## From {child}\nDid it.\n"
    assert "needs a `## Status` section" in refused(no_status)

    empty_status = f"Merged it.\n\n## From {child}\nDid it.\n\n## Status\n\n"
    assert "`## Status` is empty" in refused(empty_status)

    authored = _merge_text(child, status="Parent carries it now.")
    assert run("merge", child, "--body", body(authored), "--root", root).code == 0
    metadata, rendered = store.parse_frontmatter(written.read_text(encoding="utf-8"))
    assert metadata["headline"] == f"Merged {child}: the result is in."
    assert "Parent carries it now." in rendered


def test_merge_refuses_a_missing_from_narrative(root, run, body, family):
    child = family["child"]
    for text in (
        f"Merged it.\n\n## From {child}\n\n## Status\nfine.\n",
        # Only the pasted facts: still no narrative.
        f"Merged it.\n\n## From {child}\nRecorded by the tool at merge:\n- Final checkpoint: c0001\n\n"
        "## Status\nfine.\n",
    ):
        result = run("merge", child, "--body", body(text), "--root", root)
        assert result.code == 2
        assert f"`## From {child}` has no narrative" in result.err
        assert "write what" in result.err
    assert not (family["parent_path"] / "checkpoints" / "c0002.md").exists()


def test_merge_refuses_an_over_limit_from_narrative(root, run, body, family):
    child = family["child"]
    result = run("merge", child, "--body", body(_merge_text(child, narrative="n" * 1501)), "--root", root)
    assert result.code == 2
    assert f"`## From {child}` is 1501 characters; the limit is 1500" in result.err
    assert not (family["parent_path"] / "checkpoints" / "c0002.md").exists()
    # Exactly at the limit is fine, and a pasted facts block doesn't count toward it.
    pasted = "n" * 1500 + "\n\nRecorded by the tool at merge:\n- Final checkpoint: c0001, stale\n"
    assert run("merge", child, "--body", body(_merge_text(child, narrative=pasted)), "--root", root).code == 0
    written = (family["parent_path"] / "checkpoints" / "c0002.md").read_text(encoding="utf-8")
    assert "stale" not in written and written.count("Recorded by the tool at merge:") == 1


def test_merge_closes_the_task_that_promoted_the_child(root, run, body, origin, make_thread):
    parent = make_thread("Parent thread")
    assert run("task", "add", parent, "do the sub-piece", "--root", root).code == 0
    task_id = _task_ids(run, root, parent)[0]
    child = json.loads(run("promote", parent, task_id, "Child thread", "--origin", origin,
                           "--root", root, "--json").out)["id"]
    _cp(run, root, body, parent, PARENT_BODY)
    _cp(run, root, body, child, CHILD_BODY)

    assert run("merge", child, "--body", body(_merge_text(child)), "--root", root).code == 0
    board = yaml.safe_load((store.resolve_thread(root, parent) / "tasks.yml").read_text())
    assert [task["done"] for task in board["tasks"] if task["id"] == task_id] == [True]


# ── complete, drop, reopen ───────────────────────────────────────────────────


@pytest.fixture
def solo(root, run, body, make_thread):
    """A top-level thread with one checkpoint, clean."""
    identifier = make_thread("Solo thread")
    _cp(run, root, body, identifier, CHILD_BODY)
    return identifier


def _state(root, identifier):
    return events.state(store.resolve_thread(root, identifier))["state"]


def test_complete_refuses_a_subthread_and_points_to_merge(root, run, family):
    result = run("complete", family["child"], "--root", root)
    assert result.code == lifecycle.HAS_PARENT
    assert f"`thread merge {family['child']}`" in result.err
    assert "completion-and-merging.md" in result.err
    assert f"`thread drop {family['child']}`" in result.err
    # Nothing happened.
    assert _state(root, family["child"]) == "active"
    assert store.resolve_thread(root, family["child"]).parent.name == "threads"


def test_complete_requires_a_clean_checkpoint(root, run, solo):
    assert run("note", solo, "unfinished", "--root", root).code == 0
    result = run("complete", solo, "--root", root)
    assert result.code == lifecycle.DIRTY
    assert result.err.startswith(f"can't complete yet: {solo} has 1 event since its last checkpoint")
    assert "completion-and-merging.md" in result.err


def test_complete_archives_a_top_level_thread(root, run, solo):
    commits = len(git(root, "log", "--oneline").splitlines())
    result = run("complete", solo, "--root", root, "--json")
    assert result.code == 0, result.err
    assert json.loads(result.out)["state"] == "completed"

    archived = store.resolve_thread(root, solo)
    assert archived.parent.parent.name == "archived"
    assert _log(archived)[-1]["payload"] == {"from": "active", "to": "completed"}
    assert _state(root, solo) == "completed"
    log = git(root, "log", "--oneline").splitlines()
    assert len(log) == commits + 1
    assert log[0].endswith(f"complete {solo}@c0001: Child synthesis.")
    view = run("view", solo, "--root", root).out
    assert "> **Completed**" in view and f"`thread reopen {solo}`" in view


def test_complete_refuses_a_root_with_unfinished_children(root, run, family):
    result = run("complete", family["parent"], "--root", root)
    assert result.code == lifecycle.OPEN_CHILDREN
    assert "no parent to move them to" in result.err and "Merge or drop them first" in result.err


def test_complete_has_no_force_flag(root, run, family):
    # With no parent there is nowhere to reparent to, so --force would be a no-op.
    with pytest.raises(SystemExit):
        run("complete", family["parent"], "--force", "--root", root)


def test_drop_requires_a_clean_checkpoint(root, run, family):
    assert run("note", family["child"], "unfinished", "--root", root).code == 0
    result = run("drop", family["child"], "--root", root)
    assert result.code == lifecycle.DIRTY
    assert result.err.startswith(f"can't drop yet: {family['child']} has 1 event since its last checkpoint")


def test_drop_on_a_subthread_archives_it_and_tells_the_parent(root, run, family):
    commits = len(git(root, "log", "--oneline").splitlines())
    result = run("drop", family["child"], "--root", root, "--json")
    assert result.code == 0, result.err

    archived = store.resolve_thread(root, family["child"])
    assert archived.parent.parent.name == "archived"
    assert archived.parent.name == events.timestamp()[:7]
    assert _log(archived)[-1]["payload"] == {"from": "active", "to": "dropped"}
    assert _state(root, family["child"]) == "dropped"
    dropped = [e for e in _log(family["parent_path"]) if e["type"] == "child-dropped"]
    assert dropped[0]["payload"] == {"child": family["child"], "checkpoint": "c0001"}
    log = git(root, "log", "--oneline").splitlines()
    assert len(log) == commits + 1
    assert log[0].endswith(f"drop {family['child']}@c0001: Child synthesis.")

    # The drop changes the parent's picture: it counts as work since the
    # parent's checkpoint, shows in the list, and in the subthread row.
    assert events.state(family["parent_path"])["events-since-checkpoint"] == 1
    assert summary.children(root, family["parent"])[0]["state"] == "dropped"
    view = run("view", family["parent"], "--root", root).out
    assert "**1 event since the last checkpoint**" in view
    assert f"child-dropped by s1: child={family['child']}" in view
    assert f"- 1 dropped — `thread view {family['parent']} --deep` lists them" in view
    deep = run("view", family["parent"], "--deep", "--root", root).out
    assert f"- {family['child']} — Child thread (dropped) — `thread view {family['child']}`" in deep
    assert "> **Dropped**" in run("view", family["child"], "--root", root).out

    # Dropping is legitimate: no doctor finding on the parent about it.
    findings = run("doctor", family["parent"], "--root", root, "--json").out
    assert family["child"] not in findings


def test_drop_refuses_unfinished_children_and_force_reparents_them(root, run, body, family, make_thread):
    grandchild = make_thread("Grandchild thread", "--parent", family["child"])
    _cp(run, root, body, family["child"], CHILD_BODY)

    refused = run("drop", family["child"], "--root", root)
    assert refused.code == lifecycle.OPEN_CHILDREN
    assert grandchild in refused.err and "--force" in refused.err

    assert run("drop", family["child"], "--force", "--root", root).code == 0
    moved = store.resolve_thread(root, grandchild)
    assert metadata.read(moved)["parent"] == family["parent"]


def test_drop_refuses_a_root_with_unfinished_children_even_forced(root, run, family):
    result = run("drop", family["parent"], "--force", "--root", root)
    assert result.code == lifecycle.OPEN_CHILDREN
    assert "no parent to move them to" in result.err


def test_drop_refuses_a_thread_that_already_ended(root, run, solo):
    assert run("complete", solo, "--root", root).code == 0
    result = run("drop", solo, "--root", root)
    assert result.code == lifecycle.BAD_STATE
    assert f"{solo} is completed, so it can't be dropped" in result.err
    assert f"`thread reopen {solo}`" in result.err


def test_reopen_brings_back_a_dropped_subthread(root, run, family):
    assert run("drop", family["child"], "--root", root).code == 0
    result = run("reopen", family["child"], "--root", root, "--json")
    assert result.code == 0, result.err

    path = store.resolve_thread(root, family["child"])
    assert path.parent.name == "threads"
    assert _types(path)[-2:] == ["reopened", "state-changed"]
    assert _log(path)[-1]["payload"] == {"from": "dropped", "to": "active", "reason": "reopened"}
    assert _state(root, family["child"]) == "active"
    reopened = [e for e in _log(family["parent_path"]) if e["type"] == "child-reopened"]
    assert reopened[0]["payload"] == {"child": family["child"]}
    children = summary.children(root, family["parent"])
    assert children[0]["state"] == "active"
    assert git(root, "log", "--oneline").splitlines()[0].endswith(
        f"reopen {family['child']}@c0001: Child synthesis."
    )


def test_reopen_brings_back_a_completed_thread(root, run, solo):
    assert run("complete", solo, "--root", root).code == 0
    assert run("reopen", solo, "--root", root).code == 0
    assert _state(root, solo) == "active"
    assert store.resolve_thread(root, solo).parent.name == "threads"


def test_reopen_refuses_a_subthread_whose_parent_has_finished(root, run, body, family):
    parent, child = family["parent"], family["child"]
    assert run("merge", child, "--body", body(_merge_text(child)), "--root", root).code == 0
    assert run("complete", parent, "--root", root).code == 0
    commits = len(git(root, "log", "--oneline").splitlines())

    result = run("reopen", child, "--root", root)
    assert result.code == lifecycle.BAD_STATE
    assert f"{child}'s parent, {parent}, is completed" in result.err
    assert f"`thread reopen {parent}`" in result.err
    assert _state(root, child) == "merged"  # nothing moved or written
    assert len(git(root, "log", "--oneline").splitlines()) == commits

    # The way through: parent first, then the child.
    assert run("reopen", parent, "--root", root).code == 0
    assert run("reopen", child, "--root", root).code == 0
    assert _state(root, child) == "active"


def test_reopen_refuses_an_active_thread(root, run, solo):
    result = run("reopen", solo, "--root", root)
    assert result.code == lifecycle.BAD_STATE
    assert f"{solo} is already active; nothing to reopen" in result.err


# ── pivots ───────────────────────────────────────────────────────────────────


def test_revise_refuses_a_dirty_thread(root, run, tmp_path, family):
    source = tmp_path / "revision.md"
    source.write_text("We were wrong about the scope.\n", encoding="utf-8")
    assert run("note", family["child"], "loose end", "--root", root).code == 0
    result = run("revise", family["child"], source, "--root", root)
    assert result.code == lifecycle.DIRTY


def test_revise_appends_verbatim_and_leaves_the_original_alone(root, run, tmp_path, family):
    origin_path = family["child_path"] / "origin.md"
    before = origin_path.read_text(encoding="utf-8")
    source = tmp_path / "revision.md"
    source.write_text("We were wrong about the scope.\n\n- narrower now\n", encoding="utf-8")

    assert run("revise", family["child"], source, "--root", root, "--json").code == 0
    after = origin_path.read_text(encoding="utf-8")
    assert after.startswith(before.rstrip("\n"))
    assert "## Revisions" in after
    assert f"### {events.timestamp()[:10]} by s1" in after
    assert after.endswith("We were wrong about the scope.\n\n- narrower now\n")
    revised = [e for e in _log(family["child_path"]) if e["type"] == "origin-revised"]
    assert revised[0]["payload"] == {"revision": 1}
    assert git(root, "log", "--oneline").splitlines()[0].endswith(
        f"revise {family['child']}: revision 1"
    )

    # A second revision appends below the first, with one ## Revisions heading.
    source.write_text("And wrong again.\n", encoding="utf-8")
    assert run("checkpoint", family["child"], _write(tmp_path, "cp2.md", CHILD_BODY),
               "--root", root).code == 0
    assert run("revise", family["child"], source, "--root", root).code == 0
    text = origin_path.read_text(encoding="utf-8")
    assert text.count("## Revisions") == 1
    assert text.index("We were wrong") < text.index("And wrong again.")
    # view §2 shows the origin in full, revisions included.
    view = run("view", family["child"], "--root", root).out
    assert "We were wrong about the scope." in view and "And wrong again." in view


def _write(directory, name, text):
    path = directory / name
    path.write_text(text, encoding="utf-8")
    return path









def test_link_is_one_sided_and_renders_in_both_directions(root, run, make_thread):
    first = make_thread("First thread")
    second = make_thread("Second thread")
    first_path = store.resolve_thread(root, first)
    second_path = store.resolve_thread(root, second)

    result = run("link", first, "related", second, "--root", root)
    assert result.code == 0, result.err
    assert events.state(first_path)["links"] == [
        {"kind": "related", "target": second}
    ]
    assert all(event["type"] != "linked" for event in _log(second_path))
    assert f"- Related to {second}: Second thread" in run("view", first, "--root", root).out
    assert (
        f"- Related to {first}: First thread (linked from there)"
        in run("view", second, "--root", root).out
    )

    assert run("unlink", first, "related", second, "--root", root).code == 0
    assert events.state(first_path)["links"] == []


# ── archive, view, doctor ────────────────────────────────────────────────────


def test_archive_moves_a_stranded_dropped_thread(root, run, family):
    assert run("drop", family["child"], "--root", root).code == 0
    assert run("archive", "--root", root).out == "Nothing to archive\n"

    # Put it back by hand, as a pull from another machine might.
    archived = store.resolve_thread(root, family["child"])
    active = root / "default" / "threads" / archived.name
    old_relative = archived.relative_to(root).as_posix()
    shutil.move(str(archived), str(active))
    git(root, "add", "-A", "--", old_relative, active.relative_to(root).as_posix())
    git(root, "commit", "-m", "simulate a pull with the dropped thread still active")
    findings = run("doctor", family["child"], "--root", root, "--json")

    assert "unarchived" in findings.out
    assert run("note", family["parent"], "unrelated work", "--root", root).code == 0
    (root / "stray.txt").write_text("not part of any thread", encoding="utf-8")

    result = run("archive", "--root", root, "--json")
    assert result.code == 0
    moved = json.loads(result.out)
    assert len(moved) == 1 and family["child"] in moved[0]
    assert store.resolve_thread(root, family["child"]).parent.parent.name == "archived"
    committed = git(root, "show", "--name-only", "--format=", "HEAD").splitlines()
    assert committed and all(family["child"] in name for name in committed)
    status = git(root, "status", "--porcelain").splitlines()
    assert any(family["parent"] in line and line.endswith("log.jsonl") for line in status)
    assert any(line.endswith("stray.txt") for line in status)

    assert run("archive", "--root", root, "--json").out.strip() == "[]"


def test_view_deep_interleaves_the_child_arc(root, run, body, make_thread, monkeypatch):
    # Event timestamps have second resolution, so a whole test normally lands in
    # one second and §3's chronology is unobservable. Tick a fake clock instead.
    clock = itertools.count()
    start = datetime(2026, 9, 18, 9, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(events, "now", lambda: start + timedelta(seconds=next(clock)))

    parent = make_thread("Parent thread")
    child = make_thread("Child thread", "--parent", parent)
    _cp(run, root, body, parent, PARENT_BODY)
    _cp(run, root, body, child, CHILD_BODY)
    assert run("merge", child, "--body", body(_merge_text(child)), "--root", root).code == 0

    plain = run("view", parent, "--root", root).out
    assert f"  ↳ {child}:" not in plain
    assert f"- 1 merged — `thread view {parent} --deep` lists them" in plain

    deep = run("view", parent, "--deep", "--root", root).out
    arc = deep.split("# How it got here\n")[1].split("\n\n")[0].splitlines()[1:]  # after the italic line
    assert arc[0] == "- c0001: Parent synthesis."
    assert arc[1] == f"  ↳ {child}: c0001 Child synthesis. (merged)"
    assert arc[2].startswith("- c0002: Merged")
    assert f"- {child} — Child thread (merged) — `thread view {child}`" in deep


def test_doctor_reports_a_dangling_pointer(root, run, body, loaded):
    child = loaded["child"]
    assert run("merge", child, "--body", body(_merge_text(child)), "--root", root).code == 0
    shutil.rmtree(store.resolve_thread(root, child))
    findings = run("doctor", loaded["parent"], "--root", root, "--json")
    assert findings.code == 0
    assert "dangling-pointer" in findings.out


def test_claim_and_release_do_not_block_a_merge(root, run, body, family):
    """Presence isn't work: a clean parent someone claimed and released still merges."""
    assert run("claim", family["parent"], "--root", root).code == 0
    assert run("release", family["parent"], "--root", root).code == 0
    result = run("merge", family["child"], "--body", body(_merge_text(family["child"])), "--root", root)
    assert result.code == 0, result.err


def test_merge_leaves_the_childs_orientation_behind(root, run, body, loaded):
    """orientation.md is never registered, so merge neither points at it nor copies it."""
    parent, child = loaded["parent"], loaded["child"]
    (loaded["child_path"] / "orientation.md").write_text("1. `artifacts/guide.md`\n", encoding="utf-8")
    refused = run("merge", child, "--promote", "orientation.md", "--root", root)
    assert refused.code == lifecycle.NOT_REGISTERED
    assert run("merge", child, "--promote", "artifacts/guide.md", "--body", body(_merge_text(child)),
               "--root", root).code == 0
    assert not (loaded["parent_path"] / "orientation.md").exists()
    view = run("view", parent, "--root", root).out
    assert "# Orientation" not in view
    index_path = loaded["parent_path"] / "index.md"
    assert f"*2 artifacts remain in merged subthreads; `{index_path}` lists them.*" in view
    index = index_path.read_text(encoding="utf-8")
    assert "orientation.md" not in index and "Reading guide" not in index


def test_merge_with_old_doc_and_reading_guide_registrations(root, run, body, loaded):
    """A child logged before 10-04: its old reading guide is ignored, its old doc
    can't be promoted but stays behind as a pointer, and nothing copied into the
    parent carries a `kind`."""
    parent, child, path = loaded["parent"], loaded["child"], loaded["child_path"]
    (path / "docs").mkdir()
    (path / "docs" / "how.md").write_text("# how", encoding="utf-8")
    old = {"session": "s1", "agent": "a1"}  # the test session, as if it had written them itself
    events.append(path, "register", {"registration": {
        "path": "docs/how.md", "kind": "doc", "purpose": "how it works", "read-when": "before changing it",
    }, "checkpoint": "pending"}, old)
    events.append(path, "register", {"registration": {
        "path": "reading-guide.md", "kind": "reading-guide",
    }, "checkpoint": "pending"}, old)
    _cp(run, root, body, child, CHILD_BODY)

    refused = run("merge", child, "--promote", "docs/how.md", "--root", root)
    assert refused.code == lifecycle.NOT_REGISTERED and "before docs were retired" in refused.err
    assert run("merge", child, "--promote", "artifacts/guide.md", "--body", body(_merge_text(child)),
               "--root", root).code == 0
    copied = [event["payload"] for event in _log(loaded["parent_path"]) if event["type"] == "register"]
    assert all("kind" not in payload["registration"] for payload in copied)
    pointers = [payload for payload in copied if payload.get("pointer")]
    assert {payload["registration"]["path"] for payload in pointers} == {"artifacts/kept.csv", "artifacts/left.csv", "docs/how.md"}
    assert not (loaded["parent_path"] / "docs").exists()
