"""A merge either refuses before writing anything, or goes through (the
first real merge half-applied when a check ran after its first write)."""

from __future__ import annotations

CP = "Synthesis.\n\n## Status\nHolding.\n"


def _merge_text(child, status="The parent has it."):
    return f"Merged {child}: in.\n\n## From {child}\nIt finished.\n\n## Status\n{status}\n"


def _tree(root):
    """Every file in the store except .git, as bytes."""
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*")) if path.is_file() and ".git" not in path.relative_to(root).parts
    }


def _family(run, root, body, make_thread):
    parent = make_thread("Parent")
    child = make_thread("Child", "--parent", parent)
    for identifier in (parent, child):
        assert run("checkpoint", identifier, body(CP), "--root", root).code == 0
    return parent, child


def test_a_parent_with_only_a_release_since_its_checkpoint_merges(root, run, body, make_thread):
    parent, child = _family(run, root, body, make_thread)
    assert run("claim", parent, "--root", root, "--by", "other-session").code == 0
    assert run("release", parent, "--root", root, "--by", "other-session").code == 0
    result = run("merge", child, "--body", body(_merge_text(child)), "--root", root)
    assert result.code == 0, result.err


def test_an_over_limit_body_refuses_and_changes_nothing(root, run, body, make_thread):
    parent, child = _family(run, root, body, make_thread)
    before = _tree(root)
    result = run("merge", child, "--body", body(_merge_text(child, status="s" * 3001)), "--root", root)
    assert result.code != 0 and "3001 characters" in result.err
    assert _tree(root) == before


def test_gates_ignore_presence_but_the_view_still_shows_it(root, run, body, make_thread):
    """carries_work is for gates only: another session's claim doesn't
    force --at on a checkpoint, and the claim is still listed and counted on view."""
    identifier = make_thread("Watched")
    assert run("checkpoint", identifier, body(CP), "--root", root).code == 0
    assert run("claim", identifier, "--root", root, "--by", "other-session").code == 0
    view = run("view", identifier, "--root", root).out
    assert "claim by other-session" in view and "**1 event since the last checkpoint**" in view
    result = run("checkpoint", identifier, body(CP), "--root", root)
    assert result.code == 0, result.err
