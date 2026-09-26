"""Commits stage only the threads a command touched, never the whole store."""

from __future__ import annotations

from conftest import git

from spindle import store

CP = "Synthesis.\n\n## Status\nHolding.\n"
MERGE = "Merged {c}: in.\n\n## From {c}\nIt finished.\n\n## Status\nThe parent has it.\n"


def _committed_files(root, rev="HEAD"):
    return {line for line in git(root, "show", "--name-only", "--format=", rev).splitlines() if line}


def _dirty(root):
    return git(root, "status", "--porcelain")


def test_init_commits_only_repo_files(root):
    assert _committed_files(root) == {".gitignore", ".gitattributes"}
    assert _dirty(root) == ""


def test_checkpoint_leaves_other_threads_uncommitted(root, run, body, make_thread):
    a = make_thread("Thread A")
    b = make_thread("Thread B")
    assert run("checkpoint", a, body(CP), "--root", root).code == 0
    b_folder = store.resolve_thread(root, b).relative_to(root).as_posix()
    assert run("note", b, "a finding in B", "--root", root).code == 0

    assert run("checkpoint", a, body(CP), "--root", root).code == 0

    a_folder = store.resolve_thread(root, a).relative_to(root).as_posix()
    assert all(path.startswith(a_folder + "/") for path in _committed_files(root))
    assert f"{b_folder}/" in _dirty(root)
    assert a_folder not in _dirty(root)


def test_merge_commit_holds_exactly_parent_and_child(root, run, body, make_thread):
    parent = make_thread("Parent")
    child = make_thread("Child", "--parent", parent)
    bystander = make_thread("Bystander")
    for identifier in (parent, child, bystander):
        assert run("checkpoint", identifier, body(CP), "--root", root).code == 0
    assert run("note", bystander, "unrelated", "--root", root).code == 0
    parent_folder = store.resolve_thread(root, parent).relative_to(root).as_posix()
    child_active = store.resolve_thread(root, child).relative_to(root).as_posix()

    merge_body = body(MERGE.format(c=child))
    result = run("merge", child, "--body", merge_body, "--root", root)
    assert result.code == 0, result.err

    child_archived = store.resolve_thread(root, child).relative_to(root).as_posix()
    committed = _committed_files(root)
    allowed = (parent_folder + "/", child_archived + "/", child_active + "/")
    assert all(path.startswith(allowed) for path in committed), committed
    assert any(path.startswith(parent_folder + "/") for path in committed)
    assert any(path.startswith(child_archived + "/") for path in committed)
    # The move is complete: nothing left behind at the child's old path.
    assert child_active not in _dirty(root)
    assert git(root, "ls-files", child_active) == ""
    bystander_folder = store.resolve_thread(root, bystander).relative_to(root).as_posix()
    assert f"{bystander_folder}/" in _dirty(root)


def test_archive_move_commits_with_no_strays(root, run, body, make_thread):
    done = make_thread("Done thread")
    other = make_thread("Other thread")
    for identifier in (done, other):
        assert run("checkpoint", identifier, body(CP), "--root", root).code == 0
    assert run("note", other, "pending", "--root", root).code == 0
    old = store.resolve_thread(root, done).relative_to(root).as_posix()

    result = run("complete", done, "--root", root)
    assert result.code == 0, result.err

    new = store.resolve_thread(root, done).relative_to(root).as_posix()
    assert new.startswith("default/threads/archived/")
    assert all(path.startswith((old + "/", new + "/")) for path in _committed_files(root))
    assert git(root, "ls-files", old) == ""
    other_folder = store.resolve_thread(root, other).relative_to(root).as_posix()
    assert f"{other_folder}/" in _dirty(root)


def test_scratch_is_never_committed(root, run, body, make_thread):
    identifier = make_thread("Scratchy")
    folder = store.resolve_thread(root, identifier)
    (folder / "scratch").mkdir(exist_ok=True)
    (folder / "scratch" / "draft.md").write_text("work in progress\n", encoding="utf-8")
    assert run("checkpoint", identifier, body(CP), "--root", root).code == 0
    assert "scratch/" not in git(root, "ls-files")
