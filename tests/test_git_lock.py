"""The store is one repo, so concurrent commits collide on .git/index.lock.
Commits wait the lock out; if it never clears, say so plainly (no traceback)."""

from __future__ import annotations

import threading

from conftest import git

from spindle import gitops, store

CP = "Synthesis.\n\n## Status\nHolding.\n"


def test_a_briefly_held_lock_is_waited_out(root, run, body, make_thread):
    thread = make_thread("Locked")
    lock = root / ".git" / "index.lock"
    lock.write_text("", encoding="utf-8")
    threading.Timer(0.25, lock.unlink).start()  # another commit finishing
    result = run("checkpoint", thread, body(CP), "--root", root)
    assert result.code == 0, result.err
    assert git(root, "status", "--porcelain") == ""


def test_a_lock_that_never_clears_is_a_plain_refusal(root, run, body, make_thread, monkeypatch):
    monkeypatch.setattr(gitops, "LOCK_WAITS", (0.01,))
    thread = make_thread("Stuck")
    (root / ".git" / "index.lock").write_text("", encoding="utf-8")
    result = run("checkpoint", thread, body(CP), "--root", root)
    assert result.code == 5
    assert "Recorded, but not committed" in result.err
    assert "Traceback" not in result.err
    # The checkpoint itself is on disk; the next commit on the thread picks it up.
    assert (store.resolve_thread(root, thread) / "checkpoints" / "c0001.md").exists()
    (root / ".git" / "index.lock").unlink()
    assert run("note", thread, "later", "--root", root).code == 0
    assert run("checkpoint", thread, body(CP), "--root", root).code == 0
    assert git(root, "status", "--porcelain") == ""
