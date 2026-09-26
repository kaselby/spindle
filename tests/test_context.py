"""The startup snapshot (spindle.context): nesting, order, and the inactive cap."""

from __future__ import annotations

import itertools

from spindle import context, events, metadata, store
from spindle.doctor import DOCTOR
from spindle.limits import LIMITS


def _sections(root):
    """The listed lines under each heading, keyed by the heading's first word."""
    sections: dict[str, list[str]] = {}
    current = None
    for line in context.render(root).splitlines():
        if line.endswith(":") and not line.startswith(" "):
            current = line.split()[0]
            sections[current] = []
        elif current and line.lstrip().startswith("- "):
            sections[current].append(line)
    return sections


def _ids(lines):
    return [line.split(":")[0] for line in lines]


def _clock(monkeypatch):
    """Distinct, increasing timestamps, so creation and activity order are deterministic."""
    ticks = itertools.count()

    def stamp(moment=None):
        tick = next(ticks)
        return f"2026-09-25T{tick // 3600:02d}:{tick // 60 % 60:02d}:{tick % 60:02d}Z"

    monkeypatch.setattr(events, "timestamp", stamp)


def _shelve(root, identifier):
    path = store.resolve_thread(root, identifier)
    events.append(path, "state-changed", {"from": "active", "to": "inactive"}, DOCTOR, reopen=False)


def test_subthreads_nest_under_their_parent_oldest_first(root, make_thread, monkeypatch):
    _clock(monkeypatch)
    parent = make_thread("Parent")
    first = make_thread("First child", "--parent", parent)
    grandchild = make_thread("Grandchild", "--parent", first)
    second = make_thread("Second child", "--parent", parent)
    lines = _sections(root)["Active"]
    assert _ids(lines) == [f"- {parent}", f"  - {first}", f"    - {grandchild}", f"  - {second}"]
    # Nesting says it; the line doesn't repeat it.
    assert not any("subthread of" in line for line in lines)


def test_top_level_trees_are_ordered_by_latest_activity(root, make_thread, run, monkeypatch):
    _clock(monkeypatch)
    old = make_thread("Old but busy")
    new = make_thread("New but quiet")
    assert _ids(_sections(root)["Active"]) == [f"- {new}", f"- {old}"]
    child = make_thread("Child", "--parent", old)
    run("note", child, "activity deep in the old tree")
    assert _ids(_sections(root)["Active"]) == [f"- {old}", f"  - {child}", f"- {new}"]


def test_every_active_thread_is_listed(root, make_thread):
    made = {make_thread(f"Thread number {n} with a reasonably long title to fill space") for n in range(40)}
    listed = {line.split(":")[0][2:] for line in _sections(root)["Active"]}
    assert listed == made
    assert "more" not in context.render(root)


def test_inactive_threads_are_capped_to_the_most_recent(root, make_thread, run, monkeypatch):
    _clock(monkeypatch)
    cap = LIMITS["context_inactive"]
    quiet = [make_thread(f"Quiet {n}") for n in range(cap + 2)]
    live = make_thread("Live")
    for identifier in quiet:
        _shelve(root, identifier)
    sections = _sections(root)
    assert _ids(sections["Active"]) == [f"- {live}"]
    # Newest first; the doctor's own marking events don't count as activity.
    assert _ids(sections["Inactive"]) == [f"- {i}" for i in reversed(quiet[-cap:])] + ["- … 2 more; `thread list` shows all"]
    assert f"{cap + 2} in all, the {cap} most recently active shown" in context.render(root)


def test_an_active_subthread_of_an_inactive_parent_names_it(root, make_thread):
    parent = make_thread("Shelved parent")
    child = make_thread("Still going", "--parent", parent)
    _shelve(root, parent)
    sections = _sections(root)
    assert sections["Active"] == [f"- {child}: Still going (subthread of {parent}; claimed by s1)"]
    assert _ids(sections["Inactive"]) == [f"- {parent}"]


def test_a_hand_written_parent_in_another_namespace_reads_as_top_level(root, make_thread):
    # The tool refuses a cross-namespace parent; a hand edit can
    # still write one, and the thread then sits at the top of its own group.
    parent = make_thread("Parent")
    child = make_thread("Elsewhere", "--ns", "other")
    yml = metadata.path_of(store.resolve_thread(root, child))
    yml.write_text(f"title: Elsewhere\nparent: {parent}\n", encoding="utf-8")
    text = context.render(root)
    assert "Namespace other:" in text
    assert f"- {child}: Elsewhere (subthread of {parent}; claimed by s1)" in text


def test_the_snapshot_writes_nothing(root, make_thread):
    make_thread("Untouched")
    before = {path: path.stat().st_mtime_ns for path in root.rglob("*") if path.is_file()}
    context.render(root)
    after = {path: path.stat().st_mtime_ns for path in root.rglob("*") if path.is_file()}
    assert after == before


def test_expired_claims_are_not_shown(root, make_thread):
    from datetime import timedelta

    identifier = make_thread("Abandoned")
    later = events.now() + timedelta(hours=LIMITS["stale_claim_hours"], minutes=1)
    [line] = [line for line in context.render(root, now=later).splitlines() if identifier in line]
    assert "claimed by" not in line
    [line] = [line for line in context.render(root).splitlines() if identifier in line]
    assert "claimed by s1" in line


def test_a_damaged_thread_is_left_out_not_fatal(root, make_thread):
    good = make_thread("Fine")
    bad = make_thread("Broken")
    (store.resolve_thread(root, bad) / "log.jsonl").write_text("{not json\n", encoding="utf-8")
    text = context.render(root)
    assert f"- {good}: Fine" in text
    assert bad not in text
    assert "1 thread folder couldn't be read and is left out" in text


def test_doctor_names_every_damaged_thread_and_keeps_going(root, make_thread, run):
    # The snapshot's "`thread doctor` says which" has to be true: doctor reports
    # each unreadable thread with its error instead of stopping at the first.
    good = make_thread("Fine")
    bad_json = make_thread("Broken json")
    bad_shape = make_thread("Broken shape")
    (store.resolve_thread(root, bad_json) / "log.jsonl").write_text("{not json\n", encoding="utf-8")
    (store.resolve_thread(root, bad_shape) / "log.jsonl").write_text("{}\n", encoding="utf-8")
    assert "left out" in context.render(root)
    result = run("doctor", "--root", root)
    assert result.code == 0, result.err
    assert "not valid JSON" in result.out
    assert "is malformed (missing id, ts, by, type)" in result.out
    assert good in result.out
