"""thread.yml as the thread's metadata: validated on every read,
edited by hand, diffed on the view page; orientation.md; old register kinds;
`list --flag`."""

from __future__ import annotations

import json
from datetime import timedelta

import yaml

from conftest import git
from spindle import events, metadata, render, store
from spindle.limits import LIMITS


def _yml(path):
    return metadata.path_of(path)


def _write_yml(path, text):
    _yml(path).write_text(text, encoding="utf-8")


# ── validation ───────────────────────────────────────────────────────────────


def test_project_is_no_longer_a_key(root, make_thread, run):
    """it's refused like any unknown key."""
    identifier = make_thread("Old project key")
    _write_yml(store.resolve_thread(root, identifier), "title: Old project key\nproject: spindle\n")
    assert run("view", identifier, "--root", root).code != 0


def test_an_unknown_key_is_named_with_a_guess_and_the_way_back(root, make_thread, run, body):
    identifier = make_thread("Typo thread")
    path = store.resolve_thread(root, identifier)
    _write_yml(path, "tittle: Typo thread\n")

    # Nothing committed yet (create doesn't commit): the error prints the shape.
    result = run("view", identifier, "--root", root)
    assert result.code != 0
    assert "unknown key `tittle` (did you mean `title`?)" in result.err
    assert "Your own keys go under `flags:`." in result.err
    assert "`title` is missing" in result.err
    assert "It should look like this:" in result.err and "checkout" not in result.err

    _write_yml(path, "title: Typo thread\n")
    assert run("checkpoint", identifier, body(), "--root", root).code == 0
    _write_yml(path, "tittle: Typo thread\n")
    result = run("view", identifier, "--root", root)
    relative = _yml(path).relative_to(root).as_posix()
    # Committed at the checkpoint, so the way back is a restore, not the schema.
    assert f"restore the last committed version: git -C {root} checkout -- {relative}" in result.err
    assert "It should look like this" not in result.err

    git(root, "checkout", "--", relative)
    assert run("view", identifier, "--root", root).code == 0


def test_a_file_with_nothing_committed_prints_the_schema(tmp_path):
    folder = tmp_path / "abc234-loose"
    folder.mkdir()
    (folder / "thread.yml").write_text("title: Fine\nflags:\n  tags: [a, b]\n", encoding="utf-8")
    try:
        metadata.read(folder)
    except metadata.MetadataError as error:
        text = str(error)
    else:
        raise AssertionError("a list-valued flag should not validate")
    assert "flag `tags` must be a single value" in text
    assert "It should look like this:" in text
    assert "kiln.autonomous: true" in text
    assert "checkout" not in text


def test_list_skips_and_counts_a_thread_it_cannot_read(root, make_thread, run):
    good = make_thread("Readable thread")
    bad = make_thread("Broken thread")
    _write_yml(store.resolve_thread(root, bad), "title: [not, text]\n")

    listing = run("list", "--root", root)
    assert listing.code == 0, listing.err
    assert good in listing.out and "Readable thread" in listing.out
    assert bad not in listing.out
    assert "1 thread couldn't be read and is left out; `thread doctor` says which." in listing.out

    as_json = run("list", "--root", root, "--json")
    assert as_json.code == 0
    assert [item["id"] for item in json.loads(as_json.out)] == [good]

    findings = json.loads(run("doctor", "--root", root, "--json").out)
    assert any(name == "metadata" for name, _ in findings[bad])


def test_a_dangling_parent_is_a_doctor_finding_and_the_view_still_renders(root, make_thread, run):
    parent = make_thread("Parent")
    child = make_thread("Child", "--parent", parent)
    path = store.resolve_thread(root, child)
    _write_yml(path, "title: Child\nparent: zzzz99\n")

    view = run("view", child, "--root", root)
    assert view.code == 0, view.err
    assert "- Parent zzzz99 (not found: no thread has that id, so this one is shown as top-level" in view.out
    findings = json.loads(run("doctor", child, "--root", root, "--json").out)[child]
    assert [name for name, _ in findings if name == "dangling-parent"] == ["dangling-parent"]
    assert run("list", "--root", root).code == 0
    # The old parent no longer lists it: subthreads come from the children's thread.yml.
    assert f"- {child}" not in run("view", parent, "--root", root).out


# ── what the view shows ──────────────────────────────────────────────────────


def test_hand_edits_show_as_a_diff_line_that_counts_nowhere(root, make_thread, run, body):
    other = make_thread("Another parent")
    identifier = make_thread("Diffed thread")
    path = store.resolve_thread(root, identifier)
    before = run("view", identifier, "--root", root).out
    assert "thread.yml since" not in before

    _write_yml(path, "title: Diffed thread\nflags:\n  kiln.autonomous: true\n")
    assert "> **thread.yml since the thread began:** 1 flag changed." in run("view", identifier, "--root", root).out

    assert run("checkpoint", identifier, body(), "--root", root).code == 0
    assert "thread.yml since" not in run("view", identifier, "--root", root).out

    # Shelve it, then edit by hand: the edit shows, and nothing else moves.
    _age_log(path, days=LIMITS["inactive_days"] + 1)
    assert run("doctor", identifier, "--root", root).code == 0
    assert events.state(path)["state"] == "inactive"
    log_before = events.read_events(path)
    count_before = events.state(path)["events-since-checkpoint"]

    _write_yml(path, (
        "# hand-edited\ntitle: Diffed thread, renamed\n"
        f"parent: {other}\nflags:\n  kiln.autonomous: false\n  owner: alice\n"
    ))
    view = run("view", identifier, "--root", root).out
    assert "> **thread.yml since the last checkpoint:** title, parent changed; 2 flags changed." in view
    assert events.read_events(path) == log_before
    assert events.state(path)["state"] == "inactive"
    assert events.state(path)["events-since-checkpoint"] == count_before


def _age_log(path, *, days):
    """Backdate every event so the thread reads as untouched for `days`."""
    moment = events.timestamp(events.now() - timedelta(days=days))
    lines = []
    for line in (path / "log.jsonl").read_text(encoding="utf-8").splitlines():
        event = json.loads(line)
        event["ts"] = moment
        lines.append(json.dumps(event, separators=(",", ":")))
    (path / "log.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_the_view_shows_flags_on_one_line(root, make_thread, run):
    identifier = make_thread("Flagged")
    _write_yml(store.resolve_thread(root, identifier), (
        "title: Flagged\nflags:\n  kiln.autonomous: true\n  priority: 2\n  due: 2026-10-01\n"
    ))
    view = run("view", identifier, "--root", root).out
    assert "Project:" not in view
    assert "\nFlags: kiln.autonomous=true, priority=2, due=2026-10-01\n" in view
    described = json.loads(run("view", identifier, "--root", root, "--json").out)
    assert described["flags"] == {"kiln.autonomous": True, "priority": 2, "due": "2026-10-01"}
    assert described["title"] == "Flagged" and described["state"] == "active"


# ── the tool's own writes ────────────────────────────────────────────────────


def test_update_changes_one_line_and_keeps_comments_and_flag_order(root, make_thread):
    identifier = make_thread("Commented")
    path = store.resolve_thread(root, identifier)
    text = (
        "# My notes stay put\n"
        "title: Commented  # the working title\n"
        "flags:\n"
        "  zeta: 1  # last alphabetically, first here\n"
        "  alpha: two\n"
    )
    _write_yml(path, text)
    metadata.update(path, "title", "Commented, renamed")
    metadata.update(path, "parent", "abc234")
    after = _yml(path).read_text(encoding="utf-8")
    assert after == (
        "# My notes stay put\n"
        "title: Commented, renamed\n"
        "parent: abc234\n"
        "flags:\n"
        "  zeta: 1  # last alphabetically, first here\n"
        "  alpha: two\n"
    )


def test_drop_force_writes_the_new_parent_into_the_grandchilds_thread_yml(root, make_thread, run, body):
    parent = make_thread("Parent")
    child = make_thread("Child", "--parent", parent)
    grandchild = make_thread("Grandchild", "--parent", child)
    for identifier in (parent, child, grandchild):
        assert run("checkpoint", identifier, body(), "--root", root).code == 0
    moved = store.resolve_thread(root, grandchild)
    _write_yml(moved, f"# keep me\ntitle: Grandchild\nparent: {child}\nflags:\n  a: 1\n")

    assert run("drop", child, "--force", "--root", root).code == 0
    text = _yml(moved).read_text(encoding="utf-8")
    assert text == f"# keep me\ntitle: Grandchild\nparent: {parent}\nflags:\n  a: 1\n"
    assert [e["payload"] for e in events.read_events(moved) if e["type"] == "reparented"] == [
        {"from": child, "to": parent}
    ]


def test_checkpoints_record_the_metadata_baseline(root, make_thread, run, body):
    identifier = make_thread("Baseline")
    path = store.resolve_thread(root, identifier)
    _write_yml(path, "title: Baseline\nflags:\n  a: 1\n")
    assert run("checkpoint", identifier, body(), "--root", root).code == 0
    front, _ = store.parse_frontmatter((path / "checkpoints" / "c0001.md").read_text(encoding="utf-8"))
    assert front["metadata"] == {"title": "Baseline", "flags": {"a": 1}}
    created = events.read_events(path)[0]
    assert created["type"] == "created" and created["payload"] == {"title": "Baseline"}


# ── register ─────────────────────────────────────────────────────────────────


def test_old_register_kinds_still_read(root, make_thread, run):
    identifier = make_thread()
    path = store.resolve_thread(root, identifier)
    (path / "artifacts" / "w.bin").write_text("x", encoding="utf-8")
    events.append(path, "register", {
        "registration": {"path": "artifacts/w.bin", "kind": "weights", "purpose": "old weights"},
        "checkpoint": "pending",
    }, {"session": "old", "agent": "old"})
    view = run("view", identifier, "--root", root)
    assert view.code == 0, view.err
    assert "- **artifacts/w.bin** (" in view.out and "— old weights" in view.out
    assert "weights," not in view.out.split("# Artifacts")[1]


def test_old_doc_and_reading_guide_registrations_in_the_log(root, make_thread, run):
    """Logs written before docs and the registered reading guide were retired:
    an old docs/ path lists as an artifact; a reading-guide registration is skipped."""
    identifier = make_thread()
    path = store.resolve_thread(root, identifier)
    (path / "docs").mkdir()
    (path / "docs" / "how.md").write_text("# how", encoding="utf-8")
    (path / "reading-guide.md").write_text("1. x\n", encoding="utf-8")
    old = {"session": "old", "agent": "old"}
    events.append(path, "register", {
        "registration": {"path": "docs/how.md", "kind": "doc", "purpose": "how it works",
                         "read-when": "before changing it"},
        "checkpoint": "pending",
    }, old)
    events.append(path, "register", {
        "registration": {"path": "reading-guide.md", "kind": "reading-guide", "purpose": "added a branch"},
        "checkpoint": "pending",
    }, old)
    view = run("view", identifier, "--root", root)
    assert view.code == 0, view.err
    listing = view.out.split("# Artifacts", 1)[1].split("# Related threads", 1)[0]
    assert "- **docs/how.md** (" in listing and ") — how it works\n  *Read when:* before changing it" in listing
    assert "reading-guide" not in listing
    render.write_index(path)
    index = (path / "index.md").read_text(encoding="utf-8")
    assert "- **docs/how.md** (" in index and "reading-guide" not in index
    # Moved into artifacts/ and registered there: the old doc entry drops out.
    (path / "artifacts").mkdir(exist_ok=True)
    (path / "docs" / "how.md").rename(path / "artifacts" / "how.md")
    assert run("register", identifier, "artifacts/how.md", "--purpose", "how it works", "--root", root).code == 0
    listing = run("view", identifier, "--root", root).out.split("# Artifacts", 1)[1]
    assert "docs/how.md" not in listing and "artifacts/how.md" in listing


# ── orientation.md ───────────────────────────────────────────────────────────


def test_the_view_shows_orientation_before_the_artifacts(root, make_thread, run):
    identifier = make_thread()
    path = store.resolve_thread(root, identifier)
    missing = run("view", identifier, "--root", root).out
    assert "# Orientation" not in missing  # no file, no section

    (path / "orientation.md").write_text(
        "<!-- the rule, hidden -->\n1. `artifacts/plan.md` first.\n2. Then ~/Git/Spindle on branch main.\n",
        encoding="utf-8",
    )
    view = run("view", identifier, "--root", root).out
    at = view.index("# Orientation\n1. `artifacts/plan.md` first.\n2. Then ~/Git/Spindle on branch main.")
    assert at < view.index("# Artifacts")
    assert "the rule, hidden" not in view
    # Never registered: not in the index, and no register event.
    assert "orientation" not in (path / "index.md").read_text(encoding="utf-8")
    assert not [e for e in events.read_events(path) if e["type"] == "register"]


def test_registering_a_path_again_replaces_its_entry(root, make_thread, run):
    identifier = make_thread()
    path = store.resolve_thread(root, identifier)
    (path / "artifacts" / "a.csv").write_text("a\n", encoding="utf-8")
    for purpose in ("first version", "second version"):
        assert run("register", identifier, "artifacts/a.csv",
                   "--purpose", purpose, "--root", root).code == 0
    view = run("view", identifier, "--root", root).out
    for listing in (view[view.index("# Artifacts"):], (path / "index.md").read_text(encoding="utf-8")):
        assert listing.count("**artifacts/a.csv**") == 1
        assert "second version" in listing and "first version" not in listing


def test_orientation_is_never_registered(root, make_thread, run):
    identifier = make_thread()
    path = store.resolve_thread(root, identifier)
    (path / "orientation.md").write_text("1. x\n", encoding="utf-8")
    findings = json.loads(run("doctor", identifier, "--root", root, "--json").out)[identifier]
    assert not any(name == "unregistered" for name, _ in findings)
    refused = run("register", identifier, "orientation.md", "--purpose", "p", "--root", root)
    assert refused.code == 2 and "under artifacts/" in refused.err
    assert not [e for e in events.read_events(path) if e["type"] == "register"]


def test_doctor_checks_orientations_cap_and_local_paths(root, make_thread, run, tmp_path):
    other = make_thread("Other thread")
    identifier = make_thread("Guided")
    path = store.resolve_thread(root, identifier)
    (path / "artifacts" / "here.md").write_text("x", encoding="utf-8")
    (store.resolve_thread(root, other) / "artifacts" / "there.md").write_text("x", encoding="utf-8")
    real = tmp_path / "real.txt"
    real.write_text("x", encoding="utf-8")
    (path / "orientation.md").write_text("\n".join([
        "1. `artifacts/here.md`, then `artifacts/gone.md`.",
        f"2. {real} and {tmp_path}/missing.txt",
        f"3. {other}:artifacts/there.md and {other}:artifacts/nope.md and zzzz99:artifacts/x.md",
        "4. https://example.com/artifacts/whatever and branch feature/artifacts-rework, PR #12",
        "5. ~/definitely-not-here-9eu8w2/file",
        # docs/ is no longer a path marker, bare or thread-qualified.
        f"6. docs/old.md and {other}:docs/old.md",
    ]) + "\n", encoding="utf-8")

    findings = json.loads(run("doctor", identifier, "--root", root, "--json").out)[identifier]
    dead = sorted(detail.split(" points at ")[1].split(",")[0] for name, detail in findings
                  if name == "orientation-dead-path")
    assert dead == sorted([
        "artifacts/gone.md", f"{tmp_path}/missing.txt", f"{other}:artifacts/nope.md", "zzzz99:artifacts/x.md",
        "~/definitely-not-here-9eu8w2/file",
    ])
    assert not any(name == "orientation-too-long" for name, _ in findings)
    assert not any(name.startswith("reading-guide") for name, _ in findings)

    (path / "orientation.md").write_text("x" * (LIMITS["orientation_chars"] + 1), encoding="utf-8")
    findings = json.loads(run("doctor", identifier, "--root", root, "--json").out)[identifier]
    loud = [detail for name, detail in findings if name == "orientation-too-long"]
    assert loud and loud[0].startswith("**orientation.md is 1,501 characters, over the 1,500 cap.**")
    # The view still shows orientation over the cap.
    assert "x" * 100 in run("view", identifier, "--root", root).out


# ── tasks ────────────────────────────────────────────────────────────────────


def test_tasks_sync_without_a_hash_emits_only_real_changes(root, make_thread, run):
    identifier = make_thread()
    path = store.resolve_thread(root, identifier)
    assert run("task", "add", identifier, "first", "--root", root).code == 0
    count = len(events.read_events(path))
    for _ in range(2):
        for command in (("view", identifier), ("list",), ("task", "list", identifier), ("doctor", identifier)):
            assert run(*command, "--root", root).code == 0
    assert len(events.read_events(path)) == count

    board = yaml.safe_load((path / "tasks.yml").read_text(encoding="utf-8"))
    board["tasks"].append({"text": "added by hand"})
    (path / "tasks.yml").write_text(yaml.safe_dump(board), encoding="utf-8")
    assert run("view", identifier, "--root", root).code == 0
    added = events.read_events(path)[count:]
    assert [(e["type"], e["payload"].get("hand-edit")) for e in added] == [("task-added", True)]
    assert run("view", identifier, "--root", root).code == 0
    assert len(events.read_events(path)) == count + 1


# ── list --flag ──────────────────────────────────────────────────────────────


def test_list_filters_by_flag(root, make_thread, run):
    """--flag key=value matches the value as typed (true, not True); --flag key
    matches any value; repeated flags must all hold; --json filters the same."""
    auto = make_thread("Autonomous one")
    manual = make_thread("Manual one")
    bare = make_thread("No flags")
    auto_path = store.resolve_thread(root, auto)
    manual_path = store.resolve_thread(root, manual)
    _write_yml(auto_path, "title: Autonomous one\nflags:\n  kiln.autonomous: true\n  owner: tav\n")
    _write_yml(manual_path, "title: Manual one\nflags:\n  kiln.autonomous: false\n  note: a=b\n")

    def listed(*args):
        result = run("list", "--root", root, *args)
        assert result.code == 0, result.err
        return {identifier for identifier in (auto, manual, bare) if identifier in result.out}

    assert listed("--flag", "kiln.autonomous=true") == {auto}
    assert listed("--flag", "kiln.autonomous=false") == {manual}
    assert listed("--flag", "kiln.autonomous") == {auto, manual}
    assert listed("--flag", "kiln.autonomous", "--flag", "owner=tav") == {auto}
    assert listed("--flag", "note=a=b") == {manual}  # split at the first `=`
    assert listed() == {auto, manual, bare}

    none = run("list", "--root", root, "--flag", "owner=beth")
    assert "No active threads with owner=beth." in none.out
    as_json = run("list", "--root", root, "--json", "--flag", "owner=tav")
    assert [item["id"] for item in json.loads(as_json.out)] == [auto]
    assert run("list", "--root", root, "--flag", "=x").code != 0
