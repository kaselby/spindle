"""Project-scoped thread stores: the scope setting in
~/.spindle/config.yml, the launch folder, first-use creation on `thread create`,
and the line in the user's global git ignore. The global default is unchanged."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from conftest import git
from spindle import scope, store

REPO = Path(__file__).resolve().parents[1]


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    """No --root, no SPINDLE_ROOT: the scope setting decides."""
    monkeypatch.delenv("SPINDLE_ROOT", raising=False)
    return tmp_path


def _scope(home: Path, value: str) -> None:
    (home / ".spindle").mkdir(exist_ok=True)
    (home / ".spindle" / "config.yml").write_text(f"scope: {value}\n", encoding="utf-8")


def _project(home: Path, name: str = "proj") -> Path:
    path = home / "work" / name
    path.mkdir(parents=True)
    return path


def _ignore(home: Path) -> Path:
    return home / "xdg" / "git" / "ignore"


def test_resolution_order(home, monkeypatch):
    project, other = _project(home), _project(home, "other")
    monkeypatch.chdir(project)
    global_store = (home / ".spindle").resolve()
    assert scope.locate()[0] == global_store  # no config: global
    _scope(home, "global")
    assert scope.locate()[0] == global_store
    _scope(home, "project")
    assert scope.locate()[0] == project.resolve() / ".spindle"  # the current folder
    monkeypatch.setenv("SPINDLE_PROJECT", str(other))
    assert scope.locate()[0] == other.resolve() / ".spindle"  # the pinned launch folder
    monkeypatch.setenv("SPINDLE_ROOT", str(home / "env"))
    assert scope.locate()[0] == (home / "env").resolve()  # the environment wins
    assert scope.locate(str(home / "flag"))[0] == (home / "flag").resolve()  # so does --root


def test_global_scope_never_starts_a_store(home, run, origin, monkeypatch):
    monkeypatch.chdir(_project(home))
    assert "Run `thread init`" in run("list").err
    assert run("create", "A thread", "--origin", origin).code != 0
    assert not (home / ".spindle").exists() and not _ignore(home).exists()


def test_the_first_create_starts_a_project_store_and_reads_dont(home, run, origin, monkeypatch):
    _scope(home, "project")
    project = _project(home)
    subprocess.run(["git", "init", "-q"], cwd=project, check=True)
    (project / ".gitignore").write_text("build/\n", encoding="utf-8")
    monkeypatch.chdir(project)

    assert run("list").code != 0
    assert not (project / ".spindle").exists() and not _ignore(home).exists()

    first = run("create", "First", "--origin", origin)
    assert first.code == 0, first.err
    root = project.resolve() / ".spindle"
    assert (root / ".git").is_dir() and len(store.iter_threads(root)) == 1
    assert "**/.spindle/" in _ignore(home).read_text(encoding="utf-8")
    # The project's own .gitignore is untouched, and the store stays out of its repo.
    assert (project / ".gitignore").read_text(encoding="utf-8") == "build/\n"
    assert ".spindle" not in git(project, "status", "--porcelain", "--untracked-files=all")

    second = run("create", "Second", "--origin", origin)
    assert second.code == 0 and "git ignore" not in second.out
    assert _ignore(home).read_text(encoding="utf-8").count("**/.spindle/") == 1
    assert "Second" in run("list").out


def test_an_existing_ignore_line_and_core_excludesfile_are_respected(home):
    excludes = home / "my-excludes"
    excludes.write_text("*.swp\n.spindle/\n", encoding="utf-8")
    subprocess.run(["git", "config", "--global", "core.excludesfile", "~/my-excludes"], check=True)
    assert scope.global_ignore_file() == excludes
    assert scope.ensure_global_ignore() is None
    assert excludes.read_text(encoding="utf-8") == "*.swp\n.spindle/\n"


def test_setup_writes_the_scope(home, run, monkeypatch):
    monkeypatch.chdir(_project(home))
    assert run("setup", "--harness", "claude-code", "--scope", "project").code == 0
    assert scope.scope() == "project"


def test_claude_code_hook_exports_the_project_folder(tmp_path):
    env_file = tmp_path / "claude-env"
    env_file.write_text("", encoding="utf-8")
    folder = tmp_path / "it's a project"
    subprocess.run(
        ["/bin/sh", str(REPO / "hooks" / "claude-code.sh"), "SessionStart"],
        input=json.dumps({"session_id": "s", "cwd": "/from/input"}), text=True, capture_output=True,
        check=True,
        env={"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "CLAUDE_ENV_FILE": str(env_file),
             "CLAUDE_PROJECT_DIR": str(folder)},
    )
    sourced = subprocess.run(
        ["/bin/sh", "-c", f'. "{env_file}"; printf %s "$SPINDLE_PROJECT"'],
        text=True, capture_output=True, check=True, env={"PATH": "/usr/bin:/bin"},
    ).stdout
    assert sourced == str(folder)


PI_DRIVER = r"""
const [, , extension, cwd] = process.argv;
const handlers = {};
const pi = { on: (e, h) => { handlers[e] = h; }, exec: async () => ({ code: 0, stdout: "" }), sendMessage: () => {} };
const { default: spindle } = await import(extension);
spindle(pi);
const ctx = { cwd, sessionManager: { getSessionId: () => "0190-abcd-ef01", getEntries: () => [] } };
await handlers.session_start({ type: "session_start", reason: "startup" }, ctx);
console.log(process.env.SPINDLE_PROJECT);
"""


def test_pi_extension_pins_the_session_cwd(tmp_path):
    node = shutil.which("node")
    if not node:
        pytest.skip("node isn't installed")
    driver = tmp_path / "driver.mjs"
    driver.write_text(PI_DRIVER, encoding="utf-8")
    result = subprocess.run(
        [node, "--experimental-strip-types", "--no-warnings", str(driver), str(REPO / "extensions" / "pi.ts"), "/proj"],
        text=True, capture_output=True, env={"PATH": os.environ.get("PATH", ""), "HOME": str(tmp_path)},
    )
    if result.returncode and "strip-types" in result.stderr:
        pytest.skip("this node can't load TypeScript directly")
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "/proj"
