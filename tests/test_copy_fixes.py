"""Fixes from a first-time-user pass."""

from __future__ import annotations


def test_release_gate_ignores_ceremony_events(root, make_thread, run):
    identifier = make_thread("Gate")
    for text in ("one", "two", "three"):
        assert run("note", identifier, text, "--root", root).code == 0
    # created + claim + 3 notes = 5 own events, 3 of them work: still under the gate
    assert run("release", identifier, "--root", root).code == 0
    assert run("claim", identifier, "--root", root).code == 0
    assert run("note", identifier, "four", "--root", root).code == 0
    assert run("release", identifier, "--root", root).code == 3


def test_template_comments_do_not_become_headlines(root, make_thread, run, body, tmp_path):
    identifier = make_thread("Comments")
    text = "<!-- line one is the headline -->\nReal headline.\n\nOutline.\n\n## Status\n<!-- state, not diary -->\nFine.\n"
    assert run("checkpoint", identifier, body(text), "--root", root).code == 0
    view = run("view", identifier, "--root", root).out
    assert "Real headline." in view and "line one is the headline" not in view and "state, not diary" not in view


def test_origin_comments_are_stripped_on_write(root, origin, run, tmp_path):
    path = tmp_path / "commented.md"
    path.write_text("## Context & Motivation\n<!-- why -->\nBecause.\n\n## Done looks like\n<!-- criteria -->\nDone.\n", encoding="utf-8")
    result = run("create", "Commented", "--origin", path, "--root", root, "--json")
    assert result.code == 0, result.err
    written = next(p for p in (root / "default" / "threads").iterdir()) / "origin.md"
    assert "<!--" not in written.read_text(encoding="utf-8")

