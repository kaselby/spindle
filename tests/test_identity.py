"""Which identity source wins, and how each host's variables are read."""

from spindle.identity import resolve


def test_kiln_lite_uses_agent_id_and_home_folder_name():
    env = {"AGENT_ID": "worker-loud-dune", "AGENT_HOME": "/Users/k/.kl/agents/worker"}
    assert resolve(env) == {"session": "worker-loud-dune", "agent": "worker"}


def test_kiln_lite_fork_ids_keep_the_agent_name():
    # Forked sessions carry an extra suffix; the agent still comes from AGENT_HOME.
    env = {"AGENT_ID": "worker-young-loch-36c9", "AGENT_HOME": "/Users/k/.kl/agents/worker/"}
    assert resolve(env) == {"session": "worker-young-loch-36c9", "agent": "worker"}


def test_kiln_lite_needs_both_variables():
    assert resolve({"AGENT_ID": "worker-loud-dune", "USER": "u"})["session"].startswith("u@")
    assert resolve({"AGENT_HOME": "/x/agents/worker", "USER": "u"})["session"].startswith("u@")


def test_kiln_lite_ignores_an_agent_id_that_does_not_match_the_home():
    env = {"AGENT_ID": "build-1234", "AGENT_HOME": "/x/agents/worker", "USER": "u"}
    assert resolve(env)["session"].startswith("u@")


def test_kiln_lite_outranks_the_harness_session():
    env = {
        "AGENT_ID": "worker-loud-dune", "AGENT_HOME": "/x/agents/worker",
        "SPINDLE_HARNESS_SESSION": "pi-0123abcd",
    }
    assert resolve(env)["session"] == "worker-loud-dune"


def test_explicit_and_kiln_outrank_kiln_lite():
    lite = {"AGENT_ID": "worker-loud-dune", "AGENT_HOME": "/x/agents/worker"}
    assert resolve({**lite, "THREAD_SESSION": "manual"})["session"] == "manual"
    assert resolve({**lite, "KILN_AGENT_ID": "scout-deep-reach"}) == {
        "session": "scout-deep-reach", "agent": "scout",
    }


def test_kiln_takes_the_agent_from_its_home_folder():
    # Forked Kiln ids carry a suffix; splitting the id would name the agent "scout-deep".
    env = {"KILN_AGENT_ID": "scout-deep-reach-36c9", "KILN_AGENT_HOME": "/Users/k/.kiln/agents/scout/"}
    assert resolve(env) == {"session": "scout-deep-reach-36c9", "agent": "scout"}


def test_kiln_splits_the_id_when_the_home_folder_does_not_prefix_it():
    # A home outside ~/.kiln/agents, such as ~/.scout, doesn't name the agent.
    env = {"KILN_AGENT_ID": "scout-calm-oak", "KILN_AGENT_HOME": "/Users/k/.scout"}
    assert resolve(env) == {"session": "scout-calm-oak", "agent": "scout"}
    assert resolve({"KILN_AGENT_ID": "scout-calm-oak"}) == {"session": "scout-calm-oak", "agent": "scout"}
