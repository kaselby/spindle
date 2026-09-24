"""Namespaces (Kira 09-23): an organizing label, not a separate space.
Ids stay unique per root, disk stays flat, list groups, promote inherits."""

from __future__ import annotations

import json


def test_default_namespace_is_absent_everywhere(root, make_thread, run):
    identifier = make_thread("Plain")
    path = next(p for p in (root / "default" / "threads").iterdir() if p.name.startswith(identifier))
    assert "namespace" not in (path / "origin.md").read_text(encoding="utf-8")
    view = run("view", identifier, "--root", root).out
    assert "Namespace:" not in view


def test_create_with_ns_lands_in_origin_cache_and_view(root, make_thread, run):
    identifier = make_thread("Mine", "--ns", "ayin")
    view = run("view", identifier, "--root", root).out
    assert "Namespace: ayin" in view
    listing = json.loads(run("list", "--root", root, "--json").out)
    assert [t["namespace"] for t in listing if t["id"] == identifier] == ["ayin"]


def test_env_var_is_the_default_for_create_only(root, make_thread, run, monkeypatch):
    monkeypatch.setenv("SPINDLE_NAMESPACE", "ayin")
    mine = make_thread("Mine")
    monkeypatch.delenv("SPINDLE_NAMESPACE")
    plain = make_thread("Plain")
    listing = json.loads(run("list", "--root", root, "--json").out)
    by_id = {t["id"]: t.get("namespace") for t in listing}
    assert by_id[mine] == "ayin" and by_id[plain] is None
    monkeypatch.setenv("SPINDLE_NAMESPACE", "ayin")
    # env never filters reads: list still shows everything
    text = run("list", "--root", root).out
    assert mine in text and plain in text


def test_list_groups_default_first_and_ns_filters(root, make_thread, run):
    plain = make_thread("Plain")
    a = make_thread("A thing", "--ns", "ayin")
    t = make_thread("T thing", "--ns", "tav")
    text = run("list", "--root", root).out
    lines = text.splitlines()
    # a heading per namespace, the default first, one footer at the bottom
    assert lines[0] == "# Namespace: default" and lines[1].startswith(plain)
    assert "# Namespace: ayin" in lines and "# Namespace: tav" in lines
    assert lines.index("# Namespace: ayin") < lines.index("# Namespace: tav")
    assert "`thread list --ns <name>`" in lines[-1]
    assert sum("don't lock" in line for line in lines) == 1
    only = run("list", "--root", root, "--ns", "tav").out
    assert t in only and a not in only and plain not in only
    default_only = run("list", "--root", root, "--ns", "default").out
    assert plain in default_only and a not in default_only


def test_ns_and_default_are_the_same_thing(root, make_thread, run):
    identifier = make_thread("Plain", "--ns", "default")
    listing = json.loads(run("list", "--root", root, "--json").out)
    assert "namespace" not in next(t for t in listing if t["id"] == identifier)


def test_bad_namespace_is_refused_before_anything_is_written(root, origin, run):
    result = run("create", "Bad", "--origin", origin, "--root", root, "--ns", "Ayin Space")
    assert result.code != 0
    assert "isn't a valid namespace" in result.err
    assert "--ns ayin-space" in result.err  # names the fix
    assert list((root / "default" / "threads").iterdir()) == []


def test_promote_inherits_the_parent_namespace_unless_told(root, make_thread, run, origin):
    parent = make_thread("Parent", "--ns", "ayin")
    assert run("task", "add", parent, "child work", "--root", root).code == 0
    board = json.loads(run("task", "list", parent, "--root", root, "--json").out)
    task_id = board[0]["id"] if isinstance(board, list) else board["tasks"][0]["id"]
    child = json.loads(run("promote", parent, task_id, "Child", "--origin", origin, "--root", root, "--json").out)["id"]
    listing = {t["id"]: t.get("namespace") for t in json.loads(run("list", "--root", root, "--json").out)}
    assert listing[child] == "ayin"
    assert run("task", "add", parent, "other work", "--root", root).code == 0
    board = json.loads(run("task", "list", parent, "--root", root, "--json").out)
    tasks = board if isinstance(board, list) else board["tasks"]
    other = next(t["id"] for t in tasks if not t.get("promoted"))
    child2 = json.loads(run("promote", parent, other, "Child two", "--origin", origin, "--root", root, "--json", "--ns", "default").out)["id"]
    listing = {t["id"]: t.get("namespace") for t in json.loads(run("list", "--root", root, "--json").out)}
    assert listing[child2] is None
    # cross-namespace parent/child is allowed and the parent still sees the child
    view = run("view", parent, "--root", root).out
    assert child in view and child2 in view


def test_namespaced_threads_live_in_subfolders(root, make_thread, run):
    plain = make_thread("Plain")
    mine = make_thread("Mine", "--ns", "ayin")
    plain_path = next(p for p in (root / "default" / "threads").iterdir() if p.name.startswith(plain))
    assert plain_path.parent == root / "default" / "threads"
    mine_path = next(p for p in (root / "ayin" / "threads").iterdir() if p.name.startswith(mine))
    assert mine_path.parent == root / "ayin" / "threads"
    # both resolve by id from the root
    from spindle import store
    assert store.resolve_thread(root, mine) == mine_path
    assert store.namespace_of(mine_path) == "ayin" and store.namespace_of(plain_path) is None
    assert store.root_of(mine_path) == root and store.is_active(mine_path)


def test_complete_and_reopen_keep_the_namespace_subfolder(root, make_thread, run, body):
    from spindle import store, events
    mine = make_thread("Mine", "--ns", "ayin")
    assert run("checkpoint", mine, body("Headline\n\nOutline line.\n\n## Status\nFine.\n"), "--root", root).code == 0
    assert run("complete", mine, "--root", root).code == 0
    archived = store.resolve_thread(root, mine)
    assert archived.parent == root / "ayin" / "threads" / "archived" / events.timestamp()[:7]
    assert not store.is_active(archived) and store.namespace_of(archived) == "ayin"
    assert run("reopen", mine, "--root", root).code == 0
    back = store.resolve_thread(root, mine)
    assert back.parent == root / "ayin" / "threads"


def test_list_without_namespaces_has_no_headings(root, make_thread, run):
    plain = make_thread("Plain")
    lines = run("list", "--root", root).out.splitlines()
    assert lines[0].startswith(plain)
    assert not any(line.startswith("# Namespace") for line in lines)


def test_list_filter_with_no_match_says_so(root, make_thread, run):
    make_thread("Plain")
    out = run("list", "--root", root, "--ns", "tav").out
    assert "No active threads in namespace tav" in out and "`thread list`" in out


def test_bad_env_namespace_names_the_variable(root, origin, run, monkeypatch):
    monkeypatch.setenv("SPINDLE_NAMESPACE", "Bad Name")
    result = run("create", "Bad", "--origin", origin, "--root", root)
    assert result.code != 0
    assert "SPINDLE_NAMESPACE" in result.err and "unset" in result.err
    assert list((root / "default" / "threads").iterdir()) == []
    # --ns overrides the variable
    assert run("create", "Good", "--origin", origin, "--root", root, "--ns", "default").code == 0


def test_bad_namespace_is_caught_before_the_template(root, run):
    result = run("create", "Bad", "--root", root, "--ns", "Ayin Space")
    assert result.code != 0 and "isn't a valid namespace" in result.err
    assert "Origin template" not in result.out


def test_template_command_keeps_the_ns_flag(root, run):
    result = run("create", "Mine", "--root", root, "--ns", "ayin")
    assert '--ns ayin --origin <file>' in result.out


def test_layout_names_cannot_confuse_anchoring(root, run, make_thread):
    from spindle import store
    # A namespace may be called "threads" or "archived"; anchoring is on the store's .git.
    for name in ("threads", "archived"):
        identifier = make_thread("Odd", "--ns", name)
        path = store.resolve_thread(root, identifier)
        assert path.parent == root / name / "threads"
        assert store.root_of(path) == root and store.namespace_of(path) == name
        assert store.is_active(path)


def test_reanchor_keeps_the_namespace(root, make_thread, run, origin, body):
    from spindle import store

    identifier = make_thread("Old", "--ns", "ayin")
    assert run("checkpoint", identifier, body(), "--root", root).code == 0
    new_origin = origin.parent / "reanchor-origin.md"
    new_origin.write_text("## Context & Motivation\nThe work, framed as if new.\n\n## Previous origin\nIt used to be narrower.\n", encoding="utf-8")
    assert run(
        "reanchor", identifier, "--origin", new_origin, "--title", "Old, reanchored",
        "--body", body(), "--root", root,
    ).code == 0
    path = store.resolve_thread(root, identifier)
    assert store.namespace_of(path) == "ayin"
    assert store.read_yaml(path / "thread.yml", {})["title"] == "Old, reanchored"
