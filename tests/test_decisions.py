"""Decisions: decide, supersede, look up; working vs settled; not on the view page."""

import json

from spindle import events, store

GOOD = "## Decision\nOne artifacts folder.\n\n## Why\nDocs decayed.\n"


def _file(tmp_path, name: str, text: str):
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return path


def test_decide_without_a_body_prints_the_template(make_thread, run, root):
    identifier = make_thread()
    result = run("decide", identifier, "One folder", "--settled", "--root", root)
    assert result.code != 0
    assert f'thread decide {identifier} "One folder" <file> --settled' in result.out
    assert "## Decision" in result.out and "## Why" in result.out


def test_decide_writes_the_file_and_the_event(make_thread, run, root, tmp_path):
    identifier = make_thread()
    result = run("decide", identifier, "One artifacts folder", _file(tmp_path, "d.md", GOOD),
                 "--root", root, "--json")
    assert result.code == 0, result.err
    value = json.loads(result.out)
    assert value["decision"] == "D001" and value["status"] == "working"
    thread = store.resolve_thread(root, identifier)
    front, text = store.parse_frontmatter((thread / value["file"]).read_text(encoding="utf-8"))
    assert front["id"] == "D001" and front["status"] == "working"
    assert "## Why\n\nDocs decayed." in text
    decided = [event for event in events.read_events(thread) if event["type"] == "decided"]
    assert decided[-1]["payload"]["file"] == value["file"]


def test_a_decision_needs_its_reason_and_known_sections(make_thread, run, root, tmp_path):
    identifier = make_thread()
    no_why = run("decide", identifier, "x", _file(tmp_path, "a.md", "## Decision\nx\n"), "--root", root)
    assert no_why.code == 2 and "`## Why`" in no_why.err
    template_left = _file(tmp_path, "b.md", "## Decision\nx\n\n## Why\n<!-- the reason -->\n")
    assert run("decide", identifier, "x", template_left, "--root", root).code == 2
    extra = _file(tmp_path, "c.md", GOOD + "\n## Notes\ny\n")
    result = run("decide", identifier, "x", extra, "--root", root)
    assert result.code == 2 and "`## Notes`" in result.err
    long_title = run("decide", identifier, "t" * 81, _file(tmp_path, "d.md", GOOD), "--root", root)
    assert long_title.code == 2 and "80 characters" in long_title.err


def test_supersede_marks_the_old_one_and_hides_it_from_the_live_list(make_thread, run, root, tmp_path):
    identifier = make_thread()
    decision = _file(tmp_path, "d.md", GOOD)
    assert run("decide", identifier, "First", decision, "--root", root).code == 0
    assert run("decide", identifier, "Ruled on", decision, "--settled", "--root", root).code == 0
    assert run("decide", identifier, "Second", decision, "--supersedes", "d001", "--root", root).code == 0

    live = run("decisions", identifier, "--root", root).out
    assert "- D001" not in live
    assert "- D002 [settled] Ruled on" in live
    assert "- D003 [working] Second" in live and "replaces D001" in live
    every = run("decisions", identifier, "--all", "--root", root).out
    assert "- D001 [superseded by D003] First" in every

    thread = store.resolve_thread(root, identifier)
    old = next((thread / "decisions").glob("D001-*.md"))
    front, _ = store.parse_frontmatter(old.read_text(encoding="utf-8"))
    assert front["superseded-by"] == "D003"
    assert "superseded-by: D003" in run("decisions", identifier, "D001", "--root", root).out


def test_supersede_refuses_unknown_and_already_superseded(make_thread, run, root, tmp_path):
    identifier = make_thread()
    decision = _file(tmp_path, "d.md", GOOD)
    unknown = run("decide", identifier, "x", decision, "--supersedes", "D009", "--root", root)
    assert unknown.code == 2 and "no decision D009" in unknown.err
    assert run("decide", identifier, "First", decision, "--root", root).code == 0
    assert run("decide", identifier, "Second", decision, "--supersedes", "D001", "--root", root).code == 0
    again = run("decide", identifier, "Third", decision, "--supersedes", "D001", "--root", root)
    assert again.code == 2 and "Supersede D002 instead" in again.err


def test_view_points_to_decisions_without_listing_them(make_thread, run, root, tmp_path):
    identifier = make_thread()
    assert "Decisions:" not in run("view", identifier, "--root", root).out
    decision = _file(tmp_path, "d.md", GOOD)
    assert run("decide", identifier, "A working one", decision, "--root", root).code == 0
    assert run("decide", identifier, "A settled one", decision, "--settled", "--root", root).code == 0
    view = run("view", identifier, "--root", root).out
    assert f"*Decisions: 1 working and 1 settled. `thread decisions {identifier}` lists them.*" in view
    assert "A working one" not in view.split("# Since the last checkpoint", 1)[0]


def test_decisions_without_a_thread_covers_active_threads(make_thread, run, root, tmp_path):
    first = make_thread("First thread")
    make_thread("Second thread")
    assert run("decisions", "--root", root).out == "No decisions in active threads.\n"
    assert run("decide", first, "Pick A", _file(tmp_path, "d.md", GOOD), "--root", root).code == 0
    out = run("decisions", "--root", root).out
    assert f"## {first}: First thread" in out and "- D001 [working] Pick A" in out
    assert "Second thread" not in out


def test_show_refuses_an_unknown_decision(make_thread, run, root):
    identifier = make_thread()
    result = run("decisions", identifier, "D004", "--root", root)
    assert result.code == 2 and "no decision D004" in result.err


def test_text_above_the_first_heading_is_refused(make_thread, run, root, tmp_path):
    identifier = make_thread()
    result = run("decide", identifier, "One folder", _file(tmp_path, "d.md", "Preamble.\n\n" + GOOD), "--root", root)
    assert result.code != 0 and "above the first heading" in result.err
    assert not list((store.resolve_thread(root, identifier) / "decisions").glob("D*.md"))


def test_inline_text_where_a_file_belongs_is_a_clean_error(make_thread, run, root):
    identifier = make_thread()
    for text in ("## Decision\nshort", "## Decision\n" + "x" * 2000):
        result = run("decide", identifier, "Inline", text, "--root", root)
        assert result.code == 2
        assert "pass its path" in result.err and "Traceback" not in result.err
