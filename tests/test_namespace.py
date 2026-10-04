"""Namespaces: an organizing label, not a separate space.
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
    identifier = make_thread("Mine", "--ns", "research")
    view = run("view", identifier, "--root", root).out
    assert "Namespace: research" in view
    listing = json.loads(run("list", "--root", root, "--json").out)
    assert [t["namespace"] for t in listing if t["id"] == identifier] == ["research"]


def test_env_var_is_the_default_for_create_only(root, make_thread, run, monkeypatch):
    monkeypatch.setenv("SPINDLE_NAMESPACE", "research")
    mine = make_thread("Mine")
    monkeypatch.delenv("SPINDLE_NAMESPACE")
    plain = make_thread("Plain")
    listing = json.loads(run("list", "--root", root, "--json").out)
    by_id = {t["id"]: t.get("namespace") for t in listing}
    assert by_id[mine] == "research" and by_id[plain] is None
    monkeypatch.setenv("SPINDLE_NAMESPACE", "research")
    # env never filters reads: list still shows everything
    text = run("list", "--root", root).out
    assert mine in text and plain in text


def test_list_groups_default_first_and_ns_filters(root, make_thread, run):
    plain = make_thread("Plain")
    a = make_thread("A thing", "--ns", "research")
    t = make_thread("T thing", "--ns", "team")
    text = run("list", "--root", root).out
    lines = text.splitlines()
    # a heading per namespace, the default first, one footer at the bottom
    assert lines[0] == "# Namespace: default" and lines[1].startswith(plain)
    assert "# Namespace: research" in lines and "# Namespace: team" in lines
    assert lines.index("# Namespace: research") < lines.index("# Namespace: team")
    assert "`thread list --ns <name>`" in lines[-1]
    assert sum("don't lock" in line for line in lines) == 1
    only = run("list", "--root", root, "--ns", "team").out
    assert t in only and a not in only and plain not in only
    default_only = run("list", "--root", root, "--ns", "default").out
    assert plain in default_only and a not in default_only


def test_ns_and_default_are_the_same_thing(root, make_thread, run):
    identifier = make_thread("Plain", "--ns", "default")
    listing = json.loads(run("list", "--root", root, "--json").out)
    assert "namespace" not in next(t for t in listing if t["id"] == identifier)


def test_bad_namespace_is_refused_before_anything_is_written(root, origin, run):
    result = run("create", "Bad", "--origin", origin, "--root", root, "--ns", "Research Space")
    assert result.code != 0
    assert "isn't a valid namespace" in result.err
    assert "--ns research-space" in result.err  # names the fix
    assert list((root / "default" / "threads").iterdir()) == []


def test_promote_inherits_the_parent_namespace_and_refuses_another(root, make_thread, run, origin):
    parent = make_thread("Parent", "--ns", "research")
    assert run("task", "add", parent, "child work", "--root", root).code == 0
    board = json.loads(run("task", "list", parent, "--root", root, "--json").out)
    task_id = board[0]["id"] if isinstance(board, list) else board["tasks"][0]["id"]
    child = json.loads(run("promote", parent, task_id, "Child", "--origin", origin, "--root", root, "--json").out)["id"]
    listing = {t["id"]: t.get("namespace") for t in json.loads(run("list", "--root", root, "--json").out)}
    assert listing[child] == "research"
    assert run("task", "add", parent, "other work", "--root", root).code == 0
    board = json.loads(run("task", "list", parent, "--root", root, "--json").out)
    tasks = board if isinstance(board, list) else board["tasks"]
    other = next(t["id"] for t in tasks if not t.get("promoted"))
    # A subthread lives in its parent's namespace.
    before = sorted(t["id"] for t in json.loads(run("list", "--root", root, "--json").out))
    result = run("promote", parent, other, "Child two", "--origin", origin, "--root", root, "--ns", "default")
    assert result.code == 2
    assert "a subthread lives in its parent's namespace" in result.err
    assert sorted(t["id"] for t in json.loads(run("list", "--root", root, "--json").out)) == before
    board = json.loads(run("task", "list", parent, "--root", root, "--json").out)
    tasks = board if isinstance(board, list) else board["tasks"]
    assert not next(t for t in tasks if t["id"] == other).get("promoted")
    assert child in run("view", parent, "--root", root).out


def test_create_puts_a_subthread_in_its_parents_namespace(root, make_thread, run, origin, monkeypatch):
    parent = make_thread("Parent", "--ns", "research")
    # --parent without --ns: the parent's namespace, even over SPINDLE_NAMESPACE.
    monkeypatch.setenv("SPINDLE_NAMESPACE", "team")
    child = make_thread("Child", "--parent", parent)
    listing = {t["id"]: t.get("namespace") for t in json.loads(run("list", "--root", root, "--json").out)}
    assert listing[child] == "research"
    assert make_thread("Same", "--parent", parent, "--ns", "research")
    # Refused before the origin template, so nothing is written either way.
    for extra in ([], ["--origin", origin]):
        result = run("create", "Elsewhere", "--parent", parent, "--ns", "team", "--root", root, *extra)
        assert result.code == 2
        assert f"{parent} is in namespace research" in result.err
    assert not (root / "team").exists()


def test_namespaced_threads_live_in_subfolders(root, make_thread, run):
    plain = make_thread("Plain")
    mine = make_thread("Mine", "--ns", "research")
    plain_path = next(p for p in (root / "default" / "threads").iterdir() if p.name.startswith(plain))
    assert plain_path.parent == root / "default" / "threads"
    mine_path = next(p for p in (root / "research" / "threads").iterdir() if p.name.startswith(mine))
    assert mine_path.parent == root / "research" / "threads"
    # both resolve by id from the root
    from spindle import store
    assert store.resolve_thread(root, mine) == mine_path
    assert store.namespace_of(mine_path) == "research" and store.namespace_of(plain_path) is None
    assert store.root_of(mine_path) == root and store.is_active(mine_path)


def test_complete_and_reopen_keep_the_namespace_subfolder(root, make_thread, run, body):
    from spindle import store, events
    mine = make_thread("Mine", "--ns", "research")
    assert run("checkpoint", mine, body("Headline\n\nOutline line.\n\n## Status\nFine.\n"), "--root", root).code == 0
    assert run("complete", mine, "--root", root).code == 0
    archived = store.resolve_thread(root, mine)
    assert archived.parent == root / "research" / "threads" / "archived" / events.timestamp()[:7]
    assert not store.is_active(archived) and store.namespace_of(archived) == "research"
    assert run("reopen", mine, "--root", root).code == 0
    back = store.resolve_thread(root, mine)
    assert back.parent == root / "research" / "threads"


def test_list_without_namespaces_has_no_headings(root, make_thread, run):
    plain = make_thread("Plain")
    lines = run("list", "--root", root).out.splitlines()
    assert lines[0].startswith(plain)
    assert not any(line.startswith("# Namespace") for line in lines)


def test_list_filter_with_no_match_says_so(root, make_thread, run):
    make_thread("Plain")
    out = run("list", "--root", root, "--ns", "team").out
    assert "No active threads in namespace team" in out and "`thread list`" in out


def test_bad_env_namespace_names_the_variable(root, origin, run, monkeypatch):
    monkeypatch.setenv("SPINDLE_NAMESPACE", "Bad Name")
    result = run("create", "Bad", "--origin", origin, "--root", root)
    assert result.code != 0
    assert "SPINDLE_NAMESPACE" in result.err and "unset" in result.err
    assert list((root / "default" / "threads").iterdir()) == []
    # --ns overrides the variable
    assert run("create", "Good", "--origin", origin, "--root", root, "--ns", "default").code == 0


def test_bad_namespace_is_caught_before_the_template(root, run):
    result = run("create", "Bad", "--root", root, "--ns", "Research Space")
    assert result.code != 0 and "isn't a valid namespace" in result.err
    assert "Origin template" not in result.out


def test_template_command_keeps_the_ns_flag(root, run):
    result = run("create", "Mine", "--root", root, "--ns", "research")
    assert '--ns research --origin <file>' in result.out


def test_layout_names_cannot_confuse_anchoring(root, run, make_thread):
    from spindle import store
    # A namespace may be called "threads" or "archived"; anchoring is on the store's .git.
    for name in ("threads", "archived"):
        identifier = make_thread("Odd", "--ns", name)
        path = store.resolve_thread(root, identifier)
        assert path.parent == root / name / "threads"
        assert store.root_of(path) == root and store.namespace_of(path) == name
        assert store.is_active(path)




def test_list_nests_subthreads_under_their_parent(root, make_thread, run):
    parent = make_thread("Parent")
    child = make_thread("Child", "--parent", parent)
    grandchild = make_thread("Grandchild", "--parent", child)
    lines = run("list", "--root", root).out.splitlines()
    assert lines[0].startswith(f"{parent} (active) Parent")
    assert lines[1].startswith(f"  {child} (active) Child")
    assert lines[2].startswith(f"    {grandchild} (active) Grandchild")
    assert "subthread of" not in "\n".join(lines)


def test_list_names_a_parent_that_is_not_nested_above(root, make_thread, run):
    from spindle import metadata, store

    parent = make_thread("Parent")
    child = make_thread("Elsewhere", "--ns", "team")
    # Only a hand edit can name a parent in another namespace.
    metadata.path_of(store.resolve_thread(root, child)).write_text(
        f"title: Elsewhere\nparent: {parent}\n", encoding="utf-8")
    text = run("list", "--root", root).out
    assert f"\n{child} (active) Elsewhere" in text
    assert f"subthread of {parent}" in text
