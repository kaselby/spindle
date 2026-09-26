"""create → view: the origin is shown in full, the arc starts empty."""

from __future__ import annotations

import json

from spindle import events, store


from conftest import ORIGIN_BODY


def test_create_lays_out_the_folder(root, make_thread, run):
    identifier = make_thread("Thread CLI tests")
    path = root / "default" / "threads" / next(p.name for p in (root / "default" / "threads").iterdir())
    assert path.name.startswith(f"{identifier}-")
    assert path.name == f"{identifier}-thread-cli-tests"
    for name in ("origin.md", "log.jsonl", "tasks.yml", "thread.yml", "index.md"):
        assert (path / name).is_file(), name
    for name in ("checkpoints", "docs", "artifacts", "scratch"):
        assert (path / name).is_dir(), name
    # D13: created, then a claim for the creating session.
    log = events.read_events(path)
    assert [event["type"] for event in log] == ["created", "claim"]
    assert log[0]["by"] == {"session": "s1", "agent": "a1"}


def test_slug_truncation_stops_at_a_word_boundary():
    title = "Treat the kiln memory primitive as a shared durable layer"
    assert store.slugify(title) == "treat-the-kiln-memory-primitive-as-a"
    assert len(store.slugify(title)) <= 40
    assert store.slugify("x" * 50) == "x" * 40


def test_create_refuses_an_origin_missing_a_required_heading(root, tmp_path, run):

    path = tmp_path / "thin.md"
    path.write_text("## Context & Motivation\n\n## Scope\nSome.\n", encoding="utf-8")
    result = run("create", "Thin", "--origin", path, "--root", root)
    assert result.code == 2
    assert "Context & Motivation" in result.err


def test_template_prints_the_four_headings(run):
    result = run("create", "--template")
    assert result.code == 0
    for heading in ("## Context & Motivation", "## Scope", "## Constraints", "## Completion criteria"):
        assert heading in result.out
    assert "Don't invent any" in result.out
    assert "thread-creation.md" in result.out


def test_view_renders_the_origin_in_full_and_an_empty_arc(root, make_thread, run):
    identifier = make_thread()
    result = run("view", identifier, "--root", root)
    assert result.code == 0, result.err
    out = result.out
    for line in ORIGIN_BODY.strip().splitlines():
        assert line in out
    assert "# How it got here" in out
    assert "- No checkpoints yet." in out
    assert "No checkpoint yet." in out
    assert "> **Working here:** s1 (claimed)." in out


def test_view_does_not_print_origin_frontmatter(root, make_thread, run):
    identifier = make_thread()
    result = run("view", identifier, "--root", root)
    assert result.code == 0, result.err
    section = result.out.split("# Origin: why")[1].split("# How it got here")[0]
    section = section.split("\n", 1)[1]  # drop the rest of the heading line
    assert "---" not in section
    assert "thread:" not in section
    assert "created:" not in section
    assert section.strip().startswith("## Context & Motivation")


def test_list_and_path(root, make_thread, run):
    identifier = make_thread("Listed thread")
    listing = run("list", "--root", root)
    assert listing.code == 0
    assert listing.out.startswith(f"{identifier} (active) Listed thread · claimed by s1 · 2 events since checkpoint")
    where = run("path", identifier, "--root", root, "--json")
    assert json.loads(where.out)["path"].endswith(f"{identifier}-listed-thread")


def test_unique_prefix_resolves(root, make_thread, run):
    identifier = make_thread()
    assert run("path", identifier[:3], "--root", root).code == 0
    assert run("path", "zzzzzz", "--root", root).code == 2


def test_create_without_origin_prints_the_template_and_fails(root, run):
    result = run("create", "No origin yet", "--root", root)
    assert result.code == 2
    assert 'thread create "No origin yet" --origin <file>' in result.out
    assert "## Completion criteria" in result.out
    assert not list((root / "default" / "threads").iterdir())


def test_template_comments_are_not_kept_in_the_origin(root, tmp_path, run):
    template = run("create", "--template").out
    filled = template.replace(
        "## Context & Motivation\n", "## Context & Motivation\nBecause.\n"
    )
    path = tmp_path / "filled.md"
    path.write_text(filled, encoding="utf-8")
    created = run("create", "Filled", "--origin", path, "--root", root, "--json")
    assert created.code == 0, created.err
    origin = (root / "default" / "threads" / next(p.name for p in (root / "default" / "threads").iterdir()) / "origin.md").read_text()
    assert "<!--" not in origin
    assert "Because." in origin


def test_view_counts_add_up_and_notes_are_accounted_for(root, make_thread, run):
    identifier = make_thread()
    run("note", identifier, "a finding", "--root", root)
    out = run("view", identifier, "--root", root).out
    # created + claim + note = 3; the note is counted but not listed.
    assert "> **3 events since the last checkpoint** (1 note, not listed on this page;" in out
    since = out.split("# Since the last checkpoint")[1].split("# Subthreads")[0]
    assert len([line for line in since.splitlines() if line.startswith("- 2")]) == 2
    assert "claim by s1: claimed" in since
    tip = events.read_events(next((root / "default" / "threads").iterdir()))[-1]["id"]
    assert f"> **Latest event id:** {tip}" in out


def test_replay_with_nothing_to_show_says_so(root, make_thread, run):
    identifier = make_thread()
    result = run("replay", identifier, "--type", "register", "--root", root)
    assert result.out.startswith("No events matching type register since the last checkpoint.")
    assert "--all" in result.out


def test_completion_criteria_is_optional(root, tmp_path, run):
    path = tmp_path / "context-only.md"
    path.write_text("## Context & Motivation\nThe user asked for it.\n", encoding="utf-8")
    result = run("create", "Context only", "--origin", path, "--root", root)
    assert result.code == 0


def test_store_without_git_is_refused(tmp_path, run):
    store = tmp_path / "bare"
    (store / "active").mkdir(parents=True)
    result = run("list", "--root", store)
    assert result.code != 0 and "isn't a git repository" in result.err
