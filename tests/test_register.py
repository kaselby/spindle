"""Registration guards and the generated index, plus root layout."""

from __future__ import annotations

import json

from conftest import git
from spindle import events, store

from spindle.limits import LIMITS


def test_init_lays_out_the_root(root):
    assert (root / "default" / "threads").is_dir()
    assert (root / ".git").is_dir()
    # D9: only scratch/ is ignored; thread.yml and index.md are committed.
    ignore = (root / ".gitignore").read_text(encoding="utf-8")
    assert ignore.strip() == "scratch/"
    assert (root / ".gitattributes").read_text(encoding="utf-8").strip() == "**/log.jsonl merge=union"
    assert git(root, "log", "--format=%s").strip() == "initialize thread store"
    assert set(git(root, "show", "--name-only", "--format=", "HEAD").split()) == {
        ".gitignore", ".gitattributes",
    }


def test_init_is_idempotent(root, run):
    before = git(root, "rev-list", "--count", "HEAD").strip()
    assert run("init", "--root", root).code == 0
    assert (root / "default" / "threads").is_dir()
    assert git(root, "rev-list", "--count", "HEAD").strip() == before



def test_register_requires_read_when_for_docs(root, make_thread, run):
    identifier = make_thread()
    path = store.resolve_thread(root, identifier)
    (path / "docs" / "orientation.md").write_text("# how to read this thread", encoding="utf-8")

    refused = run(
        "register", identifier, "docs/orientation.md", "--kind", "guide",
        "--purpose", "how to read this thread", "--root", root,
    )
    assert refused.code == 2
    assert "docs need --read-when" in refused.err
    assert not [e for e in events.read_events(path) if e["type"] == "register"]

    ok = run(
        "register", identifier, "docs/orientation.md", "--kind", "guide",
        "--purpose", "how to read this thread", "--read-when", "before your first checkpoint",
        "--root", root, "--json",
    )
    assert ok.code == 0, ok.err
    payload = json.loads(ok.out)["payload"]
    assert payload["registration"] == {
        "path": "docs/orientation.md", "kind": "guide",
        "purpose": "how to read this thread", "read-when": "before your first checkpoint",
    }
    assert payload["checkpoint"] == "pending"  # D8: registration is not gated on checkpointing

    index = (path / "index.md").read_text(encoding="utf-8")
    assert "- **docs/orientation.md** (guide) — how to read this thread" in index
    assert "  *Read when:* before your first checkpoint" in index

    assert "# Docs and artifacts" in run("view", identifier, "--root", root).out


def test_register_refuses_a_six_megabyte_file(root, make_thread, run):
    identifier = make_thread()
    path = store.resolve_thread(root, identifier)
    big = path / "artifacts" / "weights.bin"
    with big.open("wb") as handle:
        handle.truncate(6 * 1024 * 1024)
    assert big.stat().st_size > LIMITS["register_bytes"]

    result = run(
        "register", identifier, "artifacts/weights.bin", "--kind", "weights",
        "--purpose", "trained weights", "--root", root,
    )
    assert result.code == 2
    assert "is over 5 MB" in result.err
    assert "register a small artifact that says where it is" in result.err
    assert not [e for e in events.read_events(path) if e["type"] == "register"]

    # Just under the guard is accepted.
    small = path / "artifacts" / "report.md"
    small.write_text("x" * 1024, encoding="utf-8")
    assert run(
        "register", identifier, "artifacts/report.md", "--kind", "report",
        "--purpose", "the write-up", "--root", root,
    ).code == 0


def test_register_path_guards(root, make_thread, run):
    identifier = make_thread()
    path = store.resolve_thread(root, identifier)
    (path / "notes.md").write_text("loose file", encoding="utf-8")
    for candidate in ("notes.md", "scratch/x.md", "../escape.md", "/etc/hosts"):
        result = run(
            "register", identifier, candidate, "--kind", "other",
            "--purpose", "nope", "--root", root,
        )
        assert result.code == 2, candidate
    missing = run(
        "register", identifier, "docs/absent.md", "--kind", "guide", "--purpose", "p",
        "--read-when", "w", "--root", root,
    )
    assert missing.code == 2 and "doesn't exist" in missing.err


def test_directory_registration_covers_its_files_and_shows_a_live_count(root, make_thread, run):
    identifier = make_thread()
    path = store.resolve_thread(root, identifier)
    schemas = path / "docs" / "schemas"
    schemas.mkdir()
    for name in ("one.json", "two.json"):
        (schemas / name).write_text("{}", encoding="utf-8")

    assert run(
        "register", identifier, "docs/schemas", "--kind", "guide",
        "--purpose", "all schema definitions", "--read-when", "changing stored data",
        "--root", root,
    ).code == 0
    # Files added after registration are covered too. A file inside the directory
    # can still have its own, more specific registration.
    (schemas / "three.json").write_text("{}", encoding="utf-8")
    assert run(
        "register", identifier, "docs/schemas/one.json", "--kind", "guide",
        "--purpose", "the root schema", "--read-when", "changing the root object",
        "--root", root,
    ).code == 0

    findings = json.loads(run("doctor", identifier, "--root", root, "--json").out)[identifier]
    assert not any(name == "unregistered" for name, _ in findings)
    index = (path / "index.md").read_text(encoding="utf-8")
    assert "**docs/schemas** (guide, directory, 3 files)" in index
    assert "**docs/schemas/one.json** (guide)" in index


def test_index_is_uncapped_while_view_caps_and_points_to_it(root, make_thread, run):
    identifier = make_thread()
    path = store.resolve_thread(root, identifier)
    cap = LIMITS["artifact_index"]
    for n in range(cap + 2):
        name = f"artifacts/run-{n}.md"
        (path / "artifacts" / f"run-{n}.md").write_text(str(n), encoding="utf-8")
        assert run(
            "register", identifier, name, "--kind", "experiment",
            "--purpose", f"run {n}", "--root", root,
        ).code == 0

    index = (path / "index.md").read_text(encoding="utf-8")
    indexed = [line for line in index.splitlines() if line.startswith("- **artifacts/")]
    assert len(indexed) == cap + 2
    assert indexed[0].startswith(f"- **artifacts/run-{cap + 1}.md**")  # newest first
    assert "… 2 more" not in index

    view = run("view", identifier, "--root", root).out
    artifact_section = view.split("## Artifacts", 1)[1].split("# Related threads", 1)[0]
    shown = [line for line in artifact_section.splitlines() if line.startswith("- **artifacts/")]
    assert len(shown) == cap
    assert "**artifacts/run-0.md**" not in artifact_section
    assert f"… 2 more; see `{path / 'index.md'}`" in artifact_section

