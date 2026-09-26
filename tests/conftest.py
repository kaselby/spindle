"""Shared fixtures: a throwaway threads root per test, and a CLI runner."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from spindle import cli

ORIGIN_BODY = """## Context & Motivation
The thread CLI needs a thread to exercise it.

## Done looks like
The tests pass.
"""

CHECKPOINT_BODY = """Wired the store and the log together.

Two sessions can append without stepping on each other.

## Status
Store, events, and the fold are working; tasks are next.
"""


@dataclass
class Result:
    code: int
    out: str
    err: str


@pytest.fixture(autouse=True)
def identity(monkeypatch, tmp_path):
    """Deterministic identity; never inherit the developer's environment."""
    monkeypatch.setenv("THREAD_SESSION", "s1")
    monkeypatch.setenv("THREAD_AGENT", "a1")
    monkeypatch.delenv("THREADS_ROOT", raising=False)
    # Never touch the real ~/.spindle: tests get their own home and store.
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SPINDLE_ROOT", str(tmp_path / ".spindle"))
    # Nor the real git config or global git ignore (project stores append to it),
    # nor a launch folder pinned by the harness running the tests.
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(tmp_path / "gitconfig"))
    monkeypatch.delenv("SPINDLE_PROJECT", raising=False)
    monkeypatch.delenv("SPINDLE_PROJECT_PID", raising=False)


@pytest.fixture
def run(capsys):
    def _run(*args) -> Result:
        code = cli.main([str(arg) for arg in args])
        captured = capsys.readouterr()
        return Result(code, captured.out, captured.err)

    return _run


@pytest.fixture
def root(tmp_path, monkeypatch, run) -> Path:
    monkeypatch.chdir(tmp_path)
    path = tmp_path / ".spindle"
    assert run("init", "--root", path).code == 0
    return path


@pytest.fixture
def origin(tmp_path) -> Path:
    path = tmp_path / "origin-body.md"
    path.write_text(ORIGIN_BODY, encoding="utf-8")
    return path


@pytest.fixture
def make_thread(root, origin, run):
    def _make(title: str = "Thread CLI tests", *args) -> str:
        result = run("create", title, "--origin", origin, "--root", root, "--json", *args)
        assert result.code == 0, result.err
        import json

        return json.loads(result.out)["id"]

    return _make


@pytest.fixture
def body(tmp_path):
    """Write a checkpoint body file and return its path."""
    counter = iter(range(1000))

    def _body(text: str = CHECKPOINT_BODY) -> Path:
        path = tmp_path / f"checkpoint-body-{next(counter)}.md"
        path.write_text(text, encoding="utf-8")
        return path

    return _body


def git(root: Path, *args: str) -> str:
    """git in the threads root; tolerates an empty repository (no commits yet)."""
    return subprocess.run(
        ["git", *args], cwd=root, check=False, text=True, capture_output=True
    ).stdout
