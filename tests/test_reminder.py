"""The mid-session reminder's header: which threads this session holds, and the
events-since-checkpoint count only past the doctor's threshold."""

from spindle import reminder
from spindle.limits import LIMITS


def test_no_claim_says_so(root, make_thread):
    make_thread()
    text = reminder.text(root, "another-session")  # creating a thread claims it, so s1 holds it
    assert text.startswith("You haven't claimed a thread.")
    assert "Spindle reminder: check that your threads are up to date." in text


def test_held_thread_is_named_and_the_count_appears_only_past_the_threshold(root, make_thread, run, body):
    identifier = make_thread()
    assert run("claim", identifier, "--root", root).code == 0
    assert run("checkpoint", identifier, body(), "--root", root).code == 0
    assert run("claim", identifier, "--root", root).code == 0
    assert reminder.header(root, "s1") == f"You hold {identifier}."
    assert reminder.header(root, "someone-else").startswith("You haven't claimed")
    for number in range(LIMITS["unsynced_nudge"] + 1):
        assert run("note", identifier, f"finding {number}", "--root", root).code == 0
    assert reminder.header(root, "s1").startswith(f"You hold {identifier}: ")
    assert "events since its last checkpoint (c0001)" in reminder.header(root, "s1")


def test_missing_store_gives_just_the_text(tmp_path):
    assert reminder.text(tmp_path / "nowhere", "s1").startswith("Spindle reminder:")
