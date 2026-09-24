"""Claims, the release gate, and the doctor's maintenance passes."""

from __future__ import annotations

import json
from datetime import timedelta

from spindle import events, store
from spindle.limits import LIMITS


def _backdate(path, hours, by=None, kind="note", payload=None):
    """Append a real event with an older timestamp, to age presence."""
    return events.append(
        path, kind, payload if payload is not None else {"text": "older work"},
        by or {"session": "s1", "agent": "a1"},
        event_ts=events.timestamp(events.now() - timedelta(hours=hours)),
    )


def test_claim_and_release_round_trip(root, make_thread, run):
    identifier = make_thread()
    path = store.resolve_thread(root, identifier)
    assert run("claim", identifier, "--intent", "reading the log", "--root", root).code == 0

    view = run("view", identifier, "--root", root).out
    assert "> **Working here:** s1 (reading the log)." in view
    assert "don't lock anything" in view
    assert "- s1: reading the log (last event" in view

    assert run("release", identifier, "--root", root).code == 0
    assert "> **Working here:** nobody has claimed it." in run("view", identifier, "--root", root).out
    assert events.read_events(path)[-1]["type"] == "release"


def test_release_is_refused_past_k_own_events_and_skip_logs_the_reason(root, make_thread, run):
    identifier = make_thread()
    path = store.resolve_thread(root, identifier)
    # `created` + `claim` are ceremony and don't count; add k+1 notes so this session is over k.
    for n in range(LIMITS["release_events"] + 1):
        assert run("note", identifier, f"note {n}", "--root", root).code == 0

    refused = run("release", identifier, "--root", root)
    assert refused.code == 3
    assert "Write a checkpoint before you release" in refused.err
    assert "--skip" in refused.err
    assert "--skip \"<reason>\"" in refused.err
    assert events.read_events(path)[-1]["type"] == "note"

    # Another session is unaffected by the first session's event count.
    assert run("release", identifier, "--root", root, "--by", "s2/a2").code == 0

    ok = run("release", identifier, "--root", root, "--skip", "handing off mid-stream", "--json")
    assert ok.code == 0, ok.err
    event = json.loads(ok.out)
    assert event["type"] == "release"
    assert event["payload"] == {"skipped-checkpoint": "handing off mid-stream"}


def test_skipped_checkpoint_banner_reports_event_kinds_and_clears_at_checkpoint(root, make_thread, run, body):
    identifier = make_thread()
    path = store.resolve_thread(root, identifier)
    assert run("checkpoint", identifier, body(), "--root", root).code == 0
    for n in range(2):
        artifact = path / "artifacts" / f"run-{n}.txt"
        artifact.write_text(str(n), encoding="utf-8")
        assert run(
            "register", identifier, f"artifacts/run-{n}.txt", "--kind", "experiment",
            "--purpose", f"run {n}", "--root", root,
        ).code == 0
    for n in range(3):
        assert run("task", "add", identifier, f"follow-up {n}", "--root", root).code == 0
    assert run("note", identifier, "one caveat", "--root", root).code == 0
    assert run(
        "release", identifier, "--skip", "the registrations are the handoff", "--root", root,
        "--by", "tav-still-drake/tav",
    ).code == 0

    view = run("view", identifier, "--root", root).out
    assert (
        '> **Released without a checkpoint** by tav-still-drake: '
        '"the registrations are the handoff". Since c0001: '
    ) in view
    assert "2 registrations" in view
    assert "3 tasks added" in view
    assert "1 note" in view

    tip = events.tip(path)
    assert run("checkpoint", identifier, body(), "--root", root, "--at", tip).code == 0
    assert "Released without a checkpoint" not in run("view", identifier, "--root", root).out


def test_release_gate_resets_after_a_checkpoint(root, make_thread, run, body):

    identifier = make_thread()
    for n in range(LIMITS["release_events"]):
        run("note", identifier, f"note {n}", "--root", root)
    assert run("checkpoint", identifier, body(), "--root", root).code == 0
    assert run("release", identifier, "--root", root).code == 0


def test_stale_claims_are_marked_in_view(root, make_thread, run):
    identifier = make_thread()
    path = store.resolve_thread(root, identifier)
    _backdate(path, hours=6)
    out = run("view", identifier, "--root", root).out
    # The cheap doctor pass expires it, so presence is empty and a release was logged.
    assert "> **Working here:** nobody has claimed it." in out
    assert events.read_events(path)[-1]["type"] == "release"


def test_doctor_expires_a_five_hour_old_claim_with_the_unsynced_count(root, make_thread, run):
    identifier = make_thread()
    path = store.resolve_thread(root, identifier)
    _backdate(path, hours=5)
    unsynced = len(events.read_events(path))  # no checkpoint yet

    result = run("doctor", identifier, "--root", root, "--json")
    assert result.code == 0, result.err
    findings = json.loads(result.out)[identifier]
    assert any(
        name == "expired-claims" and f"has {unsynced} events since the last checkpoint" in text
        for name, text in findings
    )

    released = events.read_events(path)[-1]
    assert released["type"] == "release"
    assert released["by"] == {"session": "doctor", "agent": "doctor"}
    assert released["payload"] == {"session": "s1", "expired": True, "unsynced-events": unsynced}

    # Idempotent: the claim is gone, so a second run says nothing about it.
    again = json.loads(run("doctor", identifier, "--root", root, "--json").out)[identifier]
    assert not any(name == "expired-claims" for name, _ in again)


def test_doctor_full_checks(root, make_thread, run, body, tmp_path):
    identifier = make_thread()
    path = store.resolve_thread(root, identifier)
    assert run("checkpoint", identifier, body(), "--root", root).code == 0

    (path / "scratch" / "notes.txt").write_text("thinking out loud", encoding="utf-8")
    (path / "docs" / "guide.md").write_text("# guide", encoding="utf-8")

    findings = json.loads(run("doctor", "--root", root, "--json").out)[identifier]
    names = {name for name, _ in findings}
    assert "scratch-newer" in names
    assert any(name == "unregistered" and text.startswith("docs/guide.md isn't registered") for name, text in findings)

    text = run("doctor", "--root", root).out
    assert text.startswith(f"## {path.name}")
    assert "- **scratch-newer:**" in text


def test_doctor_shelves_an_inactive_thread_and_any_event_reopens_it(root, make_thread, run):
    identifier = make_thread()
    path = store.resolve_thread(root, identifier)
    _backdate(path, hours=24 * (LIMITS["inactive_days"] + 1))

    findings = json.loads(run("doctor", identifier, "--root", root, "--json").out)[identifier]
    assert any(name == "inactive" for name, _ in findings)
    shelved = [event for event in events.read_events(path) if event["type"] == "state-changed"]
    assert shelved[-1]["payload"]["from"] == "active" and shelved[-1]["payload"]["to"] == "inactive"
    assert shelved[-1]["by"]["session"] == "doctor"
    # D6: stored state, not derived.
    assert store.read_yaml(path / "thread.yml", {})["state"] == "inactive"

    assert run("note", identifier, "picking this back up", "--root", root).code == 0
    reopened = [event for event in events.read_events(path) if event["type"] == "state-changed"]
    assert reopened[-1]["payload"] == {"from": "inactive", "to": "active"}
    assert reopened[-1]["by"]["session"] == "s1"
    assert store.read_yaml(path / "thread.yml", {})["state"] == "active"


def test_unsynced_nudge_appears_in_view(root, make_thread, run):
    identifier = make_thread()
    for n in range(LIMITS["unsynced_nudge"]):
        run("note", identifier, f"note {n}", "--root", root)
    out = run("view", identifier, "--root", root).out
    assert "events since the last checkpoint.** If the work has moved on, write a checkpoint" in out
    findings = json.loads(run("doctor", identifier, "--root", root, "--json").out)[identifier]
    assert any(name == "events-since-checkpoint" for name, _ in findings)


def test_list_shows_each_thread_state_word(root, make_thread, run, body):
    busy = make_thread("Busy thread")
    idle = make_thread("Idle thread")
    gone = make_thread("Gone thread")
    idle_path = store.resolve_thread(root, idle)
    _backdate(idle_path, hours=24 * (LIMITS["inactive_days"] + 1))
    assert run("doctor", idle, "--root", root).code == 0
    # A dropped thread put back in active/ by hand (a pull from another machine, say).
    assert run("checkpoint", gone, body(), "--root", root).code == 0
    assert run("drop", gone, "--root", root).code == 0
    dropped = store.resolve_thread(root, gone)
    dropped.rename(root / "default" / "threads" / dropped.name)

    lines = run("list", "--root", root).out.splitlines()
    assert any(line.startswith(f"{busy} (active) Busy thread") for line in lines)
    assert any(line.startswith(f"{idle} (inactive) Idle thread") for line in lines)
    assert any(line.startswith(f"{gone} (dropped) Gone thread") for line in lines)


def test_inactive_finding_names_the_right_way_to_finish(root, make_thread, run):
    parent = make_thread("Parent")
    child = make_thread("Child", "--parent", parent)
    for identifier, verb in ((parent, "complete"), (child, "merge")):
        path = store.resolve_thread(root, identifier)
        _backdate(path, hours=24 * (LIMITS["inactive_days"] + 1))
        findings = json.loads(run("doctor", identifier, "--root", root, "--json").out)[identifier]
        detail = dict(findings)["inactive"]
        assert f"`thread {verb} {identifier}`" in detail and f"`thread drop {identifier}`" in detail
