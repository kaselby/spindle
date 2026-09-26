"""thread.yml as the thread's metadata: validated on every read,
edited by hand, diffed on the view page; the reading guide; register kinds;
`thread migrate` from the old cache."""

from __future__ import annotations

import json
from datetime import timedelta

import pytest
import yaml

from conftest import git
from spindle import events, metadata, store
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


def test_the_old_cache_points_at_thread_migrate(root, make_thread, run):
    identifier = make_thread("Old cache")
    path = store.resolve_thread(root, identifier)
    _write_yml(path, yaml.safe_dump({
        "id": identifier, "title": "Old cache", "state": "active", "tip": "x", "children": [],
    }))
    result = run("view", identifier, "--root", root)
    assert result.code != 0
    assert "is in the old format" in result.err
    assert "Run `thread migrate` once" in result.err
    assert "unknown key" not in result.err  # one clear message, not six unknown keys


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


def test_register_refuses_a_kind_that_does_not_match_the_folder(root, make_thread, run):
    identifier = make_thread()
    path = store.resolve_thread(root, identifier)
    (path / "artifacts" / "out.csv").write_text("a\n", encoding="utf-8")
    (path / "docs" / "how.md").write_text("# how", encoding="utf-8")

    wrong = run("register", identifier, "artifacts/out.csv", "--kind", "doc", "--purpose", "p",
                "--read-when", "w", "--root", root)
    assert wrong.code == 2
    assert "--kind doc is for files under docs/, and artifacts/out.csv is under artifacts/" in wrong.err
    assert "Use --kind artifact" in wrong.err
    wrong = run("register", identifier, "docs/how.md", "--kind", "artifact", "--purpose", "p", "--root", root)
    assert wrong.code == 2 and "Use --kind doc" in wrong.err
    with pytest.raises(SystemExit):  # argparse: the retired kinds aren't choices
        run("register", identifier, "docs/how.md", "--kind", "guide", "--purpose", "p",
            "--read-when", "w", "--root", root)
    assert not [e for e in events.read_events(path) if e["type"] == "register"]


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
    assert "weights," not in view.out.split("## Artifacts")[1]


# ── reading guide ────────────────────────────────────────────────────────────


def test_the_view_shows_the_reading_guide_before_the_docs(root, make_thread, run):
    identifier = make_thread()
    path = store.resolve_thread(root, identifier)
    missing = run("view", identifier, "--root", root).out
    assert "# Reading guide" not in missing
    assert f"*No reading guide. For pointers and a reading order, `thread reading-guide {identifier}` prints the template.*" in missing

    (path / "reading-guide.md").write_text(
        "<!-- the rule, hidden -->\n1. `docs/plan.md` first.\n2. Then ~/Git/Spindle on branch main.\n",
        encoding="utf-8",
    )
    view = run("view", identifier, "--root", root).out
    guide_at = view.index("# Reading guide\n1. `docs/plan.md` first.\n2. Then ~/Git/Spindle on branch main.")
    assert guide_at < view.index("# Docs and artifacts")
    assert "the rule, hidden" not in view
    assert "No reading guide" not in view
    # Not registered, not in the index.
    assert "reading-guide" not in (path / "index.md").read_text(encoding="utf-8")


def test_reading_guide_prints_the_template_then_the_size(root, make_thread, run):
    identifier = make_thread()
    path = store.resolve_thread(root, identifier)
    template = run("reading-guide", identifier, "--root", root)
    assert template.code == 0
    first = template.out.splitlines()[0]
    assert first.startswith("<!-- Where to look and in what order")
    assert "never status, next steps or handoff notes (those go in the checkpoint)" in first
    assert f"Save it as {path / 'reading-guide.md'}" in template.out
    assert not (path / "reading-guide.md").exists()  # printing it writes nothing

    (path / "reading-guide.md").write_text("1. `docs/a.md`\n", encoding="utf-8")
    shown = run("reading-guide", identifier, "--root", root)
    assert f"{path / 'reading-guide.md'} (14 of 1,500 characters)" in shown.out


def test_doctor_checks_the_reading_guides_cap_and_local_paths(root, make_thread, run, tmp_path):
    other = make_thread("Other thread")
    identifier = make_thread("Guided")
    path = store.resolve_thread(root, identifier)
    (path / "docs" / "here.md").write_text("x", encoding="utf-8")
    (store.resolve_thread(root, other) / "docs" / "there.md").write_text("x", encoding="utf-8")
    real = tmp_path / "real.txt"
    real.write_text("x", encoding="utf-8")
    (path / "reading-guide.md").write_text("\n".join([
        "1. `docs/here.md`, then `docs/gone.md`.",
        f"2. {real} and {tmp_path}/missing.txt",
        f"3. {other}:docs/there.md and {other}:docs/nope.md and zzzz99:docs/x.md",
        "4. https://example.com/docs/whatever and branch feature/docs-rework, PR #12",
        "5. ~/definitely-not-here-9eu8w2/file",
    ]) + "\n", encoding="utf-8")

    findings = json.loads(run("doctor", identifier, "--root", root, "--json").out)[identifier]
    dead = sorted(detail.split(" points at ")[1].split(",")[0] for name, detail in findings
                  if name == "reading-guide-dead-path")
    assert dead == sorted([
        "docs/gone.md", f"{tmp_path}/missing.txt", f"{other}:docs/nope.md", "zzzz99:docs/x.md",
        "~/definitely-not-here-9eu8w2/file",
    ])
    assert not any(name == "reading-guide-too-long" for name, _ in findings)

    (path / "reading-guide.md").write_text("x" * (LIMITS["reading_guide_chars"] + 1), encoding="utf-8")
    findings = json.loads(run("doctor", identifier, "--root", root, "--json").out)[identifier]
    loud = [detail for name, detail in findings if name == "reading-guide-too-long"]
    assert loud and loud[0].startswith("**reading-guide.md is 1,501 characters, over the 1,500 cap.**")
    # The view still shows a guide over the cap.
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


# ── migrate ──────────────────────────────────────────────────────────────────


def _to_old_format(path, *, parent=None, namespace=None, project=None):
    """Turn a thread written by this code into what the old code wrote: the
    metadata in origin.md's frontmatter, thread.yml a cache of the fold."""
    front, text = store.parse_frontmatter((path / "origin.md").read_text(encoding="utf-8"))
    title = metadata.read(path)["title"]
    front = {"thread": front["thread"], "title": title, "created": front["created"], "by": front["by"]}
    if parent:
        front["parent"] = parent
    if namespace:
        front["namespace"] = namespace
    if project:
        front["project"] = project
    (path / "origin.md").write_text(store.markdown(front, text), encoding="utf-8")
    log = events.read_events(path)
    _write_yml(path, yaml.safe_dump({
        "id": front["thread"], "slug": path.name.split("-", 1)[1], "title": title,
        "state": "active", "created": log[0]["ts"], "last-event": log[-1]["ts"], "tip": log[-1]["id"],
        "events-since-checkpoint": 0, "claims": [], "children": [], "tasks-hash": "abc",
        **({"parent": parent} if parent else {}),
    }, sort_keys=False))


def test_migrate_moves_metadata_once_and_commits_per_thread(root, make_thread, run):
    first = make_thread("First parent")
    second = make_thread("Second parent")
    child = make_thread("Moved child", "--parent", first)
    paths = {identifier: store.resolve_thread(root, identifier) for identifier in (first, second, child)}
    _to_old_format(paths[first], project="spindle")
    _to_old_format(paths[second])
    _to_old_format(paths[child], parent=first)
    # A later reparent outranks the origin's parent, as the old fold had it.
    events.append(paths[child], "reparented", {"from": first, "to": second}, {"session": "old", "agent": "old"})
    git(root, "add", "-A")
    git(root, "commit", "-qm", "old format")
    commits = len(git(root, "log", "--oneline").splitlines())
    assert "Run `thread migrate` once" in run("view", child, "--root", root).err

    dry = run("migrate", "--dry-run", "--root", root)
    assert dry.code == 0, dry.err
    assert f"- {child}: would migrate (title: Moved child, parent: {second})" in dry.out
    assert len(git(root, "log", "--oneline").splitlines()) == commits
    assert "state" in yaml.safe_load(_yml(paths[child]).read_text(encoding="utf-8"))

    done = json.loads(run("migrate", "--root", root, "--json").out)
    assert sorted(item["status"] for item in done) == ["migrated"] * 3
    assert metadata.read(paths[child]) == {"title": "Moved child", "parent": second}
    # `project` was removed: migrate drops it from origin.md rather than moving it.
    assert metadata.read(paths[first]) == {"title": "First parent"}
    front, _ = store.parse_frontmatter((paths[first] / "origin.md").read_text(encoding="utf-8"))
    assert "project" not in front
    front, _ = store.parse_frontmatter((paths[child] / "origin.md").read_text(encoding="utf-8"))
    assert set(front) == {"thread", "created", "by"}
    migrated = [e for e in events.read_events(paths[child]) if e["type"] == "migrated"]
    assert [e["payload"] for e in migrated] == [{"metadata": {"title": "Moved child", "parent": second}}]

    history = git(root, "log", "--format=%H", f"-{3}").split()
    assert len(git(root, "log", "--oneline").splitlines()) == commits + 3
    for sha in history:
        touched = git(root, "show", "--name-only", "--format=", sha).split()
        assert len({name.split("/")[2] for name in touched}) == 1, touched

    # The migrated event isn't work: no events since the checkpoint, no diff line.
    view = run("view", child, "--root", root)
    assert view.code == 0, view.err
    assert "thread.yml since" not in view.out
    assert f"- {child} — Moved child" in run("view", second, "--root", root).out

    again = json.loads(run("migrate", "--root", root, "--json").out)
    assert sorted(item["status"] for item in again) == ["already migrated"] * 3
    assert len(git(root, "log", "--oneline").splitlines()) == commits + 3
    assert len([e for e in events.read_events(paths[child]) if e["type"] == "migrated"]) == 1
