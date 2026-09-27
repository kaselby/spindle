"""Checkpoint: CAS on the tip, body validation, event-log injection, commit."""

from __future__ import annotations

import json

from conftest import CHECKPOINT_BODY, git

from spindle import events, store


def _thread_path(root, identifier):
    return store.resolve_thread(root, identifier)


def test_cas_refuses_a_stale_at_and_accepts_a_fresh_one(root, make_thread, run, body):
    identifier = make_thread()
    path = _thread_path(root, identifier)
    stale_tip = events.tip(path)

    # A second session appends while the first was composing its checkpoint.
    assert run("note", identifier, "second session was here", "--root", root, "--by", "s2/a2").code == 0
    fresh_tip = events.tip(path)

    # Without --at at all: refused, because another session has events.
    refused = run("checkpoint", identifier, body(), "--root", root)
    assert refused.code == 4
    assert "another session has written" in refused.err
    assert "retry with `--at " in refused.err
    assert fresh_tip in refused.err

    # With the tip the first session last read: refused, with the new events listed.
    stale = run("checkpoint", identifier, body(), "--root", root, "--at", stale_tip)
    assert stale.code == 4
    assert f"since you last looked (after {stale_tip})" in stale.err
    assert f"{fresh_tip} note by" in stale.err
    assert f"retry with `--at {fresh_tip}`" in stale.err
    assert not (path / "checkpoints" / "c0001.md").exists()

    # Retry against the fresh tip: accepted.
    ok = run("checkpoint", identifier, body(), "--root", root, "--at", fresh_tip, "--json")
    assert ok.code == 0, ok.err
    value = json.loads(ok.out)
    assert value["checkpoint"] == "c0001"
    assert (path / "checkpoints" / "c0001.md").is_file()
    assert events.read_events(path)[-1]["type"] == "checkpoint"


def test_checkpoint_injects_the_event_log_section(root, make_thread, run, body):
    identifier = make_thread()
    path = _thread_path(root, identifier)
    assert run("note", identifier, "first line\nsecond line", "--root", root).code == 0
    assert run("checkpoint", identifier, body(), "--root", root).code == 0

    text = (path / "checkpoints" / "c0001.md").read_text(encoding="utf-8")
    metadata, rendered = store.parse_frontmatter(text)
    assert metadata["id"] == "c0001"
    assert metadata["thread"] == identifier
    assert metadata["headline"] == "Wired the store and the log together."
    assert metadata["at"] == [e["id"] for e in events.read_events(path)][-2]
    assert "forced-by" not in metadata

    section = rendered.split("## Event log\n")[1].split("\n\n## Status")[0]
    lines = section.splitlines()
    assert [line.split(" ")[4].rstrip(":") for line in lines] == ["created", "claim", "note"]
    assert all(line.startswith("- ") and " by s1 " in line for line in lines)
    # Notes are truncated to one line.
    assert lines[-1].endswith("note: first line second line")
    # The caller's outline precedes the injected section; Status survives.
    assert rendered.index("Wired the store") < rendered.index("## Event log")
    assert "## Status" in rendered


def test_checkpoint_body_limits(root, make_thread, run, body):
    identifier = make_thread()

    long_headline = "h" * 121 + "\n\n## Status\nfine\n"
    result = run("checkpoint", identifier, body(long_headline), "--root", root)
    assert result.code == 2 and "headline (the first line) is 121 characters; the limit is 120" in result.err

    long_status = "Headline.\n\n## Status\n" + "s" * 3001 + "\n"
    result = run("checkpoint", identifier, body(long_status), "--root", root)
    assert result.code == 2 and "`## Status` is 3001 characters; the limit is 3000" in result.err

    inherited = (
        "Headline.\n\n## Status\nfine\n\n## Inherited\n"
        + "".join(f"- item {n} (from c0001)\n" for n in range(4))
    )
    result = run("checkpoint", identifier, body(inherited), "--root", root)
    assert result.code == 2 and "`## Inherited` has 4 lines; the limit is 3" in result.err

    no_provenance = "Headline.\n\n## Status\nfine\n\n## Inherited\n- item without provenance\n"
    result = run("checkpoint", identifier, body(no_provenance), "--root", root)
    assert result.code == 2 and 'like "(from c0003)"' in result.err

    missing_status = "Headline.\n\nMore outline.\n"
    result = run("checkpoint", identifier, body(missing_status), "--root", root)
    assert result.code == 2 and "needs a `## Status` section" in result.err

    assert not list((_thread_path(root, identifier) / "checkpoints").glob("*.md"))


def test_unknown_sections_are_preserved_in_checkpoint_and_current_view(root, make_thread, run, body):
    identifier = make_thread()
    path = _thread_path(root, identifier)
    text = (
        "A checkpoint with local structure.\n\n"
        "## Evidence the user asked us to keep\n"
        "- first result\n- second result\n\n"
        "## Status\nReady for the next pass.\n\n"
        "## Risks and oddities\nThe edge case is still open.\n"
    )
    assert run("checkpoint", identifier, body(text), "--root", root).code == 0

    written = (path / "checkpoints" / "c0001.md").read_text(encoding="utf-8")
    assert "## Evidence the user asked us to keep\n- first result\n- second result" in written
    assert "## Risks and oddities\nThe edge case is still open." in written
    view = run("view", identifier, "--root", root).out
    assert "## Evidence the user asked us to keep" in view
    assert "## Risks and oddities" in view


def test_inherited_is_mirrored_into_frontmatter(root, make_thread, run, body):

    identifier = make_thread()
    text = (
        "Headline.\n\n## Status\nfine\n\n## Inherited\n"
        "- the store owns atomic writes (from c0001)\n"
        "- the log is the only mutation path (from c0002)\n"
    )
    assert run("checkpoint", identifier, body(text), "--root", root).code == 0
    metadata, _ = store.parse_frontmatter(
        (_thread_path(root, identifier) / "checkpoints" / "c0001.md").read_text(encoding="utf-8")
    )
    assert metadata["inherited"] == [
        {"since": "c0001", "text": "the store owns atomic writes (from c0001)"},
        {"since": "c0002", "text": "the log is the only mutation path (from c0002)"},
    ]


def test_forced_by_choices(root, make_thread, run, body, capsys):
    identifier = make_thread()
    assert run("checkpoint", identifier, body(), "--root", root, "--forced-by", "merge").code == 0
    metadata, _ = store.parse_frontmatter(
        (_thread_path(root, identifier) / "checkpoints" / "c0001.md").read_text(encoding="utf-8")
    )
    assert metadata["forced-by"] == "merge"
    import pytest

    with pytest.raises(SystemExit):  # argparse rejects retired choices
        run("checkpoint", identifier, body(), "--root", root, "--forced-by", "unsynced-bound")


def test_one_commit_per_checkpoint(root, make_thread, run, body):
    identifier = make_thread()
    assert git(root, "log", "--format=%s").strip() == "initialize thread store"


    assert run("checkpoint", identifier, body(), "--root", root).code == 0
    assert run("note", identifier, "more work", "--root", root).code == 0
    # Between checkpoints the tree is dirty and nothing is committed (D10).
    assert git(root, "status", "--porcelain").strip() != ""

    second = "Second pass over the fold.\n\n## Status\nGreen.\n"
    assert run("checkpoint", identifier, body(second), "--root", root).code == 0

    log = git(root, "log", "--format=%s").strip().splitlines()
    assert log == [
        f"checkpoint {identifier}@c0002: Second pass over the fold.",
        f"checkpoint {identifier}@c0001: Wired the store and the log together.",
        "initialize thread store",
    ]

    # The caches are committed, scratch is not (D9).
    tracked = git(root, "ls-files").splitlines()
    assert any(name.endswith("/thread.yml") for name in tracked)
    assert any(name.endswith("/index.md") for name in tracked)


def test_checkpoint_commit_leaves_another_threads_work_uncommitted(root, make_thread, run, body):
    first = make_thread("First thread")
    second = make_thread("Second thread")
    assert run("checkpoint", second, body(), "--root", root).code == 0
    second_path = _thread_path(root, second)
    assert run("note", second, "still in flight", "--root", root).code == 0

    assert run("checkpoint", first, body(), "--root", root).code == 0
    committed = git(root, "show", "--name-only", "--format=", "HEAD").splitlines()
    assert committed and all(first in name for name in committed)
    status = git(root, "status", "--porcelain").splitlines()
    second_log = (second_path / "log.jsonl").relative_to(root).as_posix()
    assert any(line.endswith(second_log) for line in status)


def test_view_shows_the_arc_and_the_latest_status(root, make_thread, run, body):

    identifier = make_thread()
    assert run("checkpoint", identifier, body(), "--root", root).code == 0
    assert run("note", identifier, "after the checkpoint", "--root", root).code == 0
    second = "Second pass over the fold.\n\n## Status\nGreen everywhere.\n"
    assert run("checkpoint", identifier, body(second), "--root", root).code == 0

    out = run("view", identifier, "--root", root).out
    arc = out.split("# How it got here")[1].split("# Where it stands")[0]
    assert "- c0001: Wired the store and the log together." in arc
    assert "- c0002: Second pass over the fold. ← current" in arc
    stands = out.split("# Where it stands")[1].split("# Since the last checkpoint")[0]
    assert "Green everywhere." in stands
    assert "## Event log" not in stands


def test_replay_scopes(root, make_thread, run, body):
    identifier = make_thread()
    assert run("note", identifier, "before", "--root", root).code == 0
    assert run("checkpoint", identifier, body(), "--root", root).code == 0
    assert run("note", identifier, "after one\nafter two", "--root", root).code == 0

    since = run("replay", identifier, "--root", root)
    assert since.code == 0
    # One event since the checkpoint; notes are rendered in full, newlines and all.
    assert len([line for line in since.out.splitlines() if line.startswith("2026")]) == 1
    assert since.out.endswith("note by s1: after one\nafter two\n")

    everything = run("replay", identifier, "--root", root, "--all")
    assert len(everything.out.strip().splitlines()) >= 5
    notes = run("replay", identifier, "--root", root, "--all", "--type", "note")
    assert len(notes.out.strip().splitlines()) == 3  # "after one\nafter two" is rendered in full
    assert run("replay", identifier, "--root", root, "--all", "--session", "nobody").out.startswith("No events matching session nobody")


def test_checkpoint_without_body_prints_the_template_with_the_events(root, make_thread, run):
    identifier = make_thread()
    run("note", identifier, "other session's finding", "--root", root, "--by", "s2/a2")
    result = run("checkpoint", identifier, "--root", root)
    assert result.code == 2
    tip = events.read_events(_thread_path(root, identifier))[-1]["id"]
    assert f"thread checkpoint {identifier} <file> --at {tip}" in result.out
    assert "note by s2: other session's finding" in result.out
    assert "## Status" in result.out and "checkpoints.md" in result.out
    assert not list((_thread_path(root, identifier) / "checkpoints").glob("*.md"))


def test_template_comments_left_in_a_body_are_ignored(root, make_thread, run, body):
    identifier = make_thread()
    template = run("checkpoint", identifier, "--root", root).out
    filled = template.replace("## Status\n", "Headline here.\n\n## Status\nAll good.\n", 1)
    assert run("checkpoint", identifier, body(filled), "--root", root).code == 0
    written = (_thread_path(root, identifier) / "checkpoints" / "c0001.md").read_text()
    assert "<!--" not in written
    assert "headline: Headline here." in written
    assert "## Inherited" not in written
