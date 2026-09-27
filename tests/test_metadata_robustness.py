"""The metadata model under damage and odd hand edits. Display scans skip what they can't read;
gates refuse on it; nothing half-applies; nothing ends in a traceback."""

from __future__ import annotations

import json

import pytest

from spindle import lifecycle, metadata, store, summary

PARENT_BODY = "Parent synthesis.\n\n## Status\nThe parent holds.\n"
CHILD_BODY = "Child synthesis.\n\nA second outline line.\n\n## Status\nThe child is done.\n"


def _merge_text(child):
    return (f"Merged {child}: the result is in.\n\n## From {child}\nThe child finished clean.\n\n"
            "## Status\nThe parent now holds the child's result.\n")


def _cp(run, root, body, identifier, text=PARENT_BODY):
    result = run("checkpoint", identifier, body(text), "--root", root)
    assert result.code == 0, result.err


def _path(root, identifier):
    return store.resolve_thread(root, identifier)


def _yml(root, identifier):
    return metadata.path_of(_path(root, identifier))


def _logs(root, *identifiers):
    return {identifier: (_path(root, identifier) / "log.jsonl").read_text(encoding="utf-8")
            for identifier in identifiers}


@pytest.fixture
def tree3(root, run, body, make_thread):
    """grandparent > parent > child, each with one checkpoint, all clean."""
    top = make_thread("Grandparent")
    middle = make_thread("Parent", "--parent", top)
    leaf = make_thread("Child", "--parent", middle)
    for identifier in (top, middle, leaf):
        _cp(run, root, body, identifier)
    return top, middle, leaf


# ── 1. a subthread that can't be read blocks the gates ───────────────────────


def test_complete_refuses_when_a_subthread_has_a_broken_thread_yml(root, run, body, make_thread):
    parent = make_thread("Parent")
    child = make_thread("Child", "--parent", parent)
    _cp(run, root, body, parent)
    # A one-character typo in the open child's thread.yml.
    _yml(root, child).write_text(f"titel: Child\nparent: {parent}\n", encoding="utf-8")
    before = _logs(root, parent)

    result = run("complete", parent, "--root", root)
    assert result.code == lifecycle.OPEN_CHILDREN, result.err
    assert "couldn't be read" in result.err and _path(root, child).name in result.err
    assert "`thread doctor`" in result.err
    assert _logs(root, parent) == before
    # Display is unchanged: the view still renders, skipping the broken child.
    assert run("view", parent, "--root", root).code == 0


def test_drop_force_refuses_over_an_unreadable_subthread_and_moves_nothing(root, run, tree3):
    top, middle, leaf = tree3
    _yml(root, leaf).write_text(f"titel: Child\nparent: {middle}\n", encoding="utf-8")
    before = _logs(root, top, middle, leaf)
    for extra in ([], ["--force"]):
        result = run("drop", middle, "--root", root, *extra)
        assert result.code == lifecycle.OPEN_CHILDREN, result.err
        assert "couldn't be read" in result.err
    assert _logs(root, top, middle, leaf) == before
    assert store.is_active(_path(root, middle))


def test_a_subthread_whose_log_is_damaged_blocks_the_gate(root, run, body, make_thread):
    parent = make_thread("Parent")
    child = make_thread("Child", "--parent", parent)
    _cp(run, root, body, parent)
    with (_path(root, child) / "log.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")
    result = run("complete", parent, "--root", root)
    assert result.code == lifecycle.OPEN_CHILDREN
    assert "couldn't be read" in result.err


def test_merge_force_refuses_over_an_unreadable_grandchild(root, run, body, tree3):
    top, middle, leaf = tree3
    _yml(root, leaf).write_text(f"titel: Child\nparent: {middle}\n", encoding="utf-8")
    before = _logs(root, top, middle, leaf)
    result = run("merge", middle, "--force", "--body", body(_merge_text(middle)), "--root", root)
    assert result.code == lifecycle.OPEN_CHILDREN, result.err
    assert _logs(root, top, middle, leaf) == before


def test_broken_threads_that_cant_be_subthreads_dont_block(root, run, body, make_thread):
    parent = make_thread("Parent")
    _cp(run, root, body, parent)
    unrelated = make_thread("Unrelated")
    _yml(root, unrelated).write_text("titel: Unrelated\n", encoding="utf-8")
    # In another namespace it can't be a subthread, even if it names the parent.
    elsewhere = make_thread("Elsewhere", "--ns", "other")
    _yml(root, elsewhere).write_text(f"titel: Elsewhere\nparent: {parent}\n", encoding="utf-8")
    result = run("complete", parent, "--root", root)
    assert result.code == 0, result.err


def test_children_scan_reports_the_unknown_and_children_skips_it(root, make_thread):
    parent = make_thread("Parent")
    good = make_thread("Good", "--parent", parent)
    bad = make_thread("Bad", "--parent", parent)
    _yml(root, bad).write_text(f"titel: Bad\nparent: {parent}\n", encoding="utf-8")
    rows, unknown = summary.children_scan(root, parent)
    assert [row["id"] for row in rows] == [good]
    assert unknown == [_path(root, bad).name]
    assert [row["id"] for row in summary.children(root, parent)] == [good]


# ── 2. merge validates before its first write ────────────────────────────────


def test_merge_into_a_parent_with_a_bad_thread_yml_writes_nothing(root, run, body, make_thread):
    parent = make_thread("Parent")
    child = make_thread("Child", "--parent", parent)
    _cp(run, root, body, parent)
    _cp(run, root, body, child, CHILD_BODY)
    _yml(root, parent).write_text("titel: Parent\n", encoding="utf-8")
    before = _logs(root, parent, child)

    result = run("merge", child, "--body", body(_merge_text(child)), "--root", root)
    assert result.code == 2
    assert "isn't valid thread metadata" in result.err
    assert _logs(root, parent, child) == before
    assert store.is_active(_path(root, child))
    assert not (_path(root, parent) / "checkpoints" / "c0002.md").exists()


# ── 4. self-parent, cycles, cross-namespace parents ──────────────────────────


def test_a_thread_cant_name_itself_as_parent(root, run, make_thread):
    identifier = make_thread("Loop")
    _yml(root, identifier).write_text(f"title: Loop\nparent: {identifier}\n", encoding="utf-8")
    result = run("view", identifier, "--root", root)
    assert result.code == 2
    assert "`parent` is this thread's own id" in result.err
    findings = run("doctor", identifier, "--root", root).out
    assert "**metadata:**" in findings and "own id" in findings


def test_doctor_flags_a_parent_cycle(root, run, make_thread):
    first = make_thread("First")
    second = make_thread("Second", "--parent", first)
    _yml(root, first).write_text(f"title: First\nparent: {second}\n", encoding="utf-8")
    report = run("doctor", "--root", root).out
    assert report.count("**parent-cycle:**") == 2
    assert f"{first} → {second} → {first}" in report
    # Both still render and list.
    assert run("view", first, "--root", root).code == 0
    listed = run("list", "--root", root).out
    assert first in listed and second in listed


def test_a_hand_written_cross_namespace_parent_reads_as_top_level(root, run, body, make_thread):
    parent = make_thread("Parent")
    _cp(run, root, body, parent)
    stray = make_thread("Stray", "--ns", "other")
    _cp(run, root, body, stray, CHILD_BODY)
    _yml(root, stray).write_text(f"title: Stray\nparent: {parent}\n", encoding="utf-8")

    report = run("doctor", stray, "--root", root).out
    assert "**cross-namespace-parent:**" in report and "namespace default, not other" in report
    # Not a read error: the thread views, with the parent row explaining itself.
    view = run("view", stray, "--root", root)
    assert view.code == 0
    assert "in namespace default, and a subthread must share its parent's namespace" in view.out
    # Not the parent's subthread: it doesn't show there or hold the parent open.
    assert summary.children(root, parent) == []
    assert stray not in run("view", parent, "--root", root).out
    # Lifecycle refuses to treat it as a subthread, like a dangling parent.
    merged = run("merge", stray, "--body", body(_merge_text(stray)), "--root", root)
    assert merged.code == 2 and "A subthread lives in its parent's namespace" in merged.err
    assert run("complete", parent, "--root", root).code == 0


def test_reopen_refuses_a_dangling_parent_before_moving_anything(root, run, body, make_thread):
    parent = make_thread("Parent")
    child = make_thread("Child", "--parent", parent)
    _cp(run, root, body, child, CHILD_BODY)
    assert run("drop", child, "--root", root).code == 0
    archived = _path(root, child)
    metadata.path_of(archived).write_text("title: Child\nparent: zzzzz9\n", encoding="utf-8")
    before = (archived / "log.jsonl").read_text(encoding="utf-8")
    result = run("reopen", child, "--root", root)
    assert result.code == 2 and "no thread has that id" in result.err
    assert _path(root, child) == archived
    assert (archived / "log.jsonl").read_text(encoding="utf-8") == before


# ── 5. non-UTF-8 files ───────────────────────────────────────────────────────


def test_a_non_utf8_reading_guide_doesnt_break_view_or_doctor(root, run, make_thread):
    identifier = make_thread("Guide")
    (_path(root, identifier) / "reading-guide.md").write_bytes(b"Read docs/plan.md first \xff\xfe\n")
    view = run("view", identifier, "--root", root)
    assert view.code == 0, view.err
    assert "# Reading guide" in view.out and "Read docs/plan.md first" in view.out
    report = run("doctor", identifier, "--root", root).out
    assert "**unreadable:**" not in report
    assert "reading-guide-dead-path" in report  # the other checks still ran


def test_a_non_utf8_thread_yml_is_a_metadata_error(root, run, make_thread):
    identifier = make_thread("Bytes")
    _yml(root, identifier).write_bytes(b"title: Caf\xe9\n")
    result = run("view", identifier, "--root", root)
    assert result.code == 2
    assert "isn't UTF-8 text" in result.err
    assert "Traceback" not in result.err


def test_main_turns_any_other_decode_error_into_a_message(root, run, make_thread):
    identifier = make_thread("Origin bytes")
    (_path(root, identifier) / "origin.md").write_bytes(b"\xff\xfe broken\n")
    result = run("view", identifier, "--root", root)
    assert result.code == 2
    assert "isn't UTF-8 text" in result.err


# ── 6. a damaged linked thread doesn't take down view or list ───────────────


def test_a_linked_thread_with_a_malformed_state_event(root, run, make_thread):
    blocked = make_thread("Blocked")
    blocker = make_thread("Blocker")
    assert run("link", blocked, "blocked-by", blocker, "--root", root).code == 0
    with (_path(root, blocker) / "log.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "id": "20990101T000000-zzzz", "ts": "2099-01-01T00:00:00Z",
            "by": {"session": "s1", "agent": "a1"}, "type": "state-changed", "payload": {},
        }) + "\n")
    view = run("view", blocked, "--root", root)
    assert view.code == 0, view.err
    assert f"Blocked by {blocker}: Blocker (state unknown: its log can't be read)" in view.out
    listed = run("list", "--root", root)
    assert listed.code == 0, listed.err
    assert blocked in listed.out


# ── 7. archive isn't blocked by one damaged log ─────────────────────────────


def test_archive_skips_a_damaged_log_and_archives_the_rest(root, run, body, make_thread):
    done = make_thread("Done")
    _cp(run, root, body, done)
    assert run("complete", done, "--root", root).code == 0
    # Put it back as an unarchived finished thread, as a pull might.
    archived = _path(root, done)
    active = root / "default" / "threads" / archived.name
    archived.rename(active)
    broken = make_thread("Broken")
    with (_path(root, broken) / "log.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")
    result = run("archive", "--root", root)
    assert result.code == 0, result.err
    assert done in result.out
    assert "archived" in _path(root, done).parts


# ── 8. the tool's own reparenting isn't a hand edit ──────────────────────────


def test_a_forced_reparent_doesnt_show_as_a_thread_yml_change(root, run, tree3):
    top, middle, leaf = tree3
    assert run("drop", middle, "--force", "--root", root).code == 0
    assert metadata.read(_path(root, leaf))["parent"] == top
    view = run("view", leaf, "--root", root).out
    assert "thread.yml since" not in view
    # A real hand edit after it still shows.
    _yml(root, leaf).write_text(f"title: Renamed\nparent: {top}\n", encoding="utf-8")
    assert "thread.yml since the last checkpoint:** title changed." in run("view", leaf, "--root", root).out


# ── 9. all-digit ids typed without quotes ────────────────────────────────────


def test_an_unquoted_all_digit_parent_reads_as_an_id(tmp_path):
    folder = tmp_path / "abc234-loose"
    folder.mkdir()
    (folder / "thread.yml").write_text("title: Digits\nparent: 234567\n", encoding="utf-8")
    assert metadata.read(folder) == {"title": "Digits", "parent": "234567"}
    (folder / "thread.yml").write_text("title: Digits\nparent: true\n", encoding="utf-8")
    with pytest.raises(metadata.MetadataError):
        metadata.read(folder)


# ── the possible-subthread test ──────────────────────────────────────────────


def _break_yml(root, identifier):
    _yml(root, identifier).write_text("titel: Broken\n", encoding="utf-8")


@pytest.mark.parametrize("mention", ["note", "checkpoint", "continues-link"])
def test_a_broken_thread_that_only_mentions_the_id_doesnt_block(root, run, body, make_thread, mention):
    top = make_thread("Top")
    other = make_thread("Other")
    _cp(run, root, body, top)
    _cp(run, root, body, other)
    if mention == "note":
        assert run("note", other, f"see also {top}", "--root", root).code == 0
    elif mention == "checkpoint":
        _cp(run, root, body, other, f"Builds on {top}.\n\n## Status\nStill tied to {top}.\n")
    else:
        assert run("link", other, "continues", top, "--root", root).code == 0
    _break_yml(root, other)
    assert top.encode() in (_path(root, other) / "log.jsonl").read_bytes()
    assert summary.children_scan(root, top) == ([], [])
    result = run("complete", top, "--root", root)
    assert result.code == 0, result.err


def test_a_broken_grandparent_doesnt_block_dropping_its_own_child(root, run, body, make_thread):
    top = make_thread("Grandparent")
    middle = make_thread("Parent", "--parent", top)
    _cp(run, root, body, top)
    _cp(run, root, body, middle, CHILD_BODY)
    _break_yml(root, top)  # its log has child-created naming middle
    assert summary.children_scan(root, middle) == ([], [])
    result = run("drop", middle, "--root", root)
    assert result.code == 0, result.err
    assert "subthread of" not in result.err


def test_a_missing_thread_yml_blocks_only_when_the_log_names_the_parent(root, run, body, make_thread):
    parent = make_thread("Parent")
    child = make_thread("Child", "--parent", parent)
    unrelated = make_thread("Unrelated")
    _cp(run, root, body, parent)
    _yml(root, unrelated).unlink()
    assert summary.children_scan(root, parent)[1] == []
    _yml(root, child).unlink()
    assert summary.children_scan(root, parent)[1] == [_path(root, child).name]
    result = run("complete", parent, "--root", root)
    assert result.code == lifecycle.OPEN_CHILDREN, result.err


@pytest.mark.parametrize("damage", ["empty", "utf16", "binary", "hand-edit"])
def test_a_real_subthread_with_a_mangled_thread_yml_still_blocks(root, run, body, make_thread, damage):
    parent = make_thread("Parent")
    child = make_thread("Child", "--parent", parent)
    _cp(run, root, body, parent)
    yml = _yml(root, child)
    if damage == "empty":
        yml.write_text("", encoding="utf-8")
    elif damage == "utf16":
        yml.write_bytes(yml.read_text(encoding="utf-8").encode("utf-16"))
    elif damage == "binary":
        yml.write_bytes(b"\x00\x01")
    else:
        yml.write_text(f"title: Child\nparent: {parent}\nunknown-key: 1\n", encoding="utf-8")
    result = run("complete", parent, "--root", root)
    assert result.code == lifecycle.OPEN_CHILDREN, result.err


def test_the_log_patterns_match_what_events_append_writes(root, make_thread):
    # The byte test relies on compact JSON; if events.append ever changes its
    # separators, this fails before the gate quietly stops seeing subthreads.
    parent = make_thread("Parent")
    child = make_thread("Child", "--parent", parent)
    assert f'"parent":"{parent}"'.encode() in (_path(root, child) / "log.jsonl").read_bytes()


def test_a_non_utf8_log_elsewhere_doesnt_break_view(root, run, make_thread):
    shown = make_thread("Shown")
    other = make_thread("Other")
    with (_path(root, other) / "log.jsonl").open("ab") as handle:
        handle.write(b"\xff\xfe\n")
    result = run("view", shown, "--root", root)
    assert result.code == 0, result.err
    assert summary.linked_from(root, shown) == []


def test_reopen_refuses_an_unreadable_parent_log_before_moving_anything(root, run, body, make_thread):
    parent = make_thread("Parent")
    child = make_thread("Child", "--parent", parent)
    _cp(run, root, body, parent)
    _cp(run, root, body, child, CHILD_BODY)
    assert run("merge", child, "--body", body(_merge_text(child)), "--root", root).code == 0
    archived = _path(root, child)
    with (_path(root, parent) / "log.jsonl").open("a", encoding="utf-8") as handle:
        handle.write("{not json\n")
    before = (archived / "log.jsonl").read_text(encoding="utf-8")
    result = run("reopen", child, "--root", root)
    assert result.code != 0
    assert "not valid JSON" in result.err
    assert _path(root, child) == archived
    assert (archived / "log.jsonl").read_text(encoding="utf-8") == before


def test_view_counts_a_subthread_it_couldnt_read(root, run, make_thread):
    parent = make_thread("Parent")
    good = make_thread("Good", "--parent", parent)
    bad = make_thread("Bad", "--parent", parent)
    _break_yml(root, bad)
    view = run("view", parent, "--root", root)
    assert view.code == 0, view.err
    section = view.out.split("# Subthreads", 1)[1].split("\n# ", 1)[0]
    assert good in section and bad not in section
    assert "1 thread couldn't be read and is left out" in section
