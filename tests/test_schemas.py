"""Every file the tool writes must validate against schemas/*.json.

This is the one test allowed a dev-only dependency on jsonschema.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

jsonschema = pytest.importorskip("jsonschema")
referencing = pytest.importorskip("referencing")

from spindle import events, store  # noqa: E402

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"


@pytest.fixture(scope="module")
def validators():
    loaded = {path.name: json.loads(path.read_text(encoding="utf-8")) for path in sorted(SCHEMAS.glob("*.schema.json"))}
    for schema in loaded.values():
        jsonschema.Draft202012Validator.check_schema(schema)
    registry = referencing.Registry().with_resources(
        [(name, referencing.Resource.from_contents(schema)) for name, schema in loaded.items()]
        + [(schema["$id"], referencing.Resource.from_contents(schema)) for schema in loaded.values()]
    )
    return {
        name: jsonschema.Draft202012Validator(
            schema, registry=registry, format_checker=jsonschema.FormatChecker()
        )
        for name, schema in loaded.items()
    }


def check(validators, name, instance, label):
    errors = sorted(validators[name].iter_errors(instance), key=lambda error: error.path)
    assert not errors, f"{label} fails {name}: " + "; ".join(
        f"{list(error.path)}: {error.message}" for error in errors
    )


@pytest.fixture
def exercised(root, make_thread, run, origin, body, tmp_path):
    """Drive a thread through every phase-1 verb that writes a file."""
    identifier = make_thread("Schema exercise")
    path = store.resolve_thread(root, identifier)

    assert run("claim", identifier, "--intent", "exercising the schemas", "--root", root).code == 0
    assert run("note", identifier, "a note\nover two lines", "--tag", "design", "--root", root).code == 0
    task = json.loads(run("task", "add", identifier, "a task", "--root", root, "--json").out)
    assert run("task", "close", identifier, task["id"], "--root", root).code == 0
    promoted = json.loads(run("task", "add", identifier, "a promotable task", "--root", root, "--json").out)
    child = json.loads(
        run("promote", identifier, promoted["id"], "Child thread", "--origin", origin,
            "--root", root, "--json").out
    )["id"]
    assert run("link", identifier, "related", child, "--root", root).code == 0
    assert run("unlink", identifier, "related", child, "--root", root).code == 0
    assert run("link", identifier, "blocked-by", child, "--root", root).code == 0

    (path / "docs" / "guide.md").write_text("# guide", encoding="utf-8")
    assert run(
        "register", identifier, "docs/guide.md", "--kind", "doc", "--purpose", "orientation",
        "--read-when", "before checkpointing", "--root", root,
    ).code == 0
    (path / "artifacts" / "report.md").write_text("# report", encoding="utf-8")
    assert run(
        "register", identifier, "artifacts/report.md", "--kind", "artifact",
        "--purpose", "the write-up", "--root", root,
    ).code == 0

    first = "First synthesis of the thread.\n\n## Status\nAll the verbs have run once.\n"
    assert run("checkpoint", identifier, body(first), "--root", root).code == 0
    assert run("note", identifier, "post-checkpoint note", "--root", root).code == 0
    second = (
        "Second synthesis.\n\n## Status\nStill green.\n\n## Inherited\n"
        "- the log is the only mutation path (from c0001)\n"
    )
    assert run("checkpoint", identifier, body(second), "--root", root, "--forced-by", "pivot").code == 0
    assert run("release", identifier, "--root", root, "--skip", "handing off").code == 0
    assert run("doctor", "--root", root).code == 0
    return root, path, identifier, child


def test_schemas_validate_every_written_file(validators, exercised):
    root, path, identifier, child = exercised
    for thread in (path, store.resolve_thread(root, child)):
        label = thread.name

        metadata, _ = store.parse_frontmatter((thread / "origin.md").read_text(encoding="utf-8"))
        check(validators, "origin.schema.json", metadata, f"{label} origin.md")

        log = events.read_events(thread)
        assert log, label
        for event in log:
            check(validators, "event.schema.json", event, f"{label} event {event['id']} ({event['type']})")

        cache = yaml.safe_load((thread / "thread.yml").read_text(encoding="utf-8"))
        check(validators, "thread.schema.json", cache, f"{label} thread.yml")

        board = yaml.safe_load((thread / "tasks.yml").read_text(encoding="utf-8"))
        check(validators, "tasks.schema.json", board, f"{label} tasks.yml")

        for checkpoint in sorted((thread / "checkpoints").glob("c*.md")):
            front, _ = store.parse_frontmatter(checkpoint.read_text(encoding="utf-8"))
            check(validators, "checkpoint.schema.json", front, f"{label} {checkpoint.name}")


def test_the_exercise_actually_produced_each_shape(exercised):
    _, path, _, _ = exercised
    kinds = {event["type"] for event in events.read_events(path)}
    assert kinds >= {
        "created", "claim", "release", "note", "checkpoint", "register",
        "task-added", "task-closed", "task-edited", "child-created", "linked", "unlinked",
    }
    assert len(list((path / "checkpoints").glob("c*.md"))) == 2


def test_ids_follow_the_build_brief_forms(exercised):
    _, path, identifier, _ = exercised
    import re

    assert re.fullmatch(r"[23456789abcdefghjkmnpqrstuvwxyz]{6}", identifier)
    for event in events.read_events(path):
        assert re.fullmatch(r"[0-9]{8}T[0-9]{6}-[23456789abcdefghjkmnpqrstuvwxyz]{4}", event["id"])
        # `format: date-time` is inert without rfc3339-validator, so check it here.
        assert re.fullmatch(r"20[0-9]{2}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z", event["ts"])
    assert [p.stem for p in sorted((path / "checkpoints").glob("*.md"))] == ["c0001", "c0002"]


def test_the_validator_rejects_the_shapes_the_schemas_retired(validators, exercised):
    """Guard against a validator that passes everything."""
    _, path, _, _ = exercised
    event = dict(events.read_events(path)[0])
    assert list(validators["event.schema.json"].iter_errors({**event, "id": 1}))  # integer event id
    merged = {**event, "type": "child-merged", "payload": {"child": "k7q2m9xa", "checkpoint": "c0003"}}
    assert not list(validators["event.schema.json"].iter_errors(merged))
    assert list(validators["event.schema.json"].iter_errors({**merged, "type": "child-landed"}))
    # The child's final checkpoint is what makes the squashed event useful.
    assert list(validators["event.schema.json"].iter_errors(
        {**merged, "payload": {"child": "k7q2m9xa"}}
    ))
    checkpoint, _ = store.parse_frontmatter(
        (path / "checkpoints" / "c0001.md").read_text(encoding="utf-8")
    )
    assert list(validators["checkpoint.schema.json"].iter_errors({**checkpoint, "id": "0001"}))
    assert list(
        validators["checkpoint.schema.json"].iter_errors({**checkpoint, "forced-by": "unsynced-bound"})
    )


@pytest.fixture
def exercised_phase_two(root, make_thread, run, origin, body, tmp_path):
    """Drive a parent, a child and a grandchild through every phase-2 verb."""
    def checkpoint(identifier, text):
        assert run("checkpoint", identifier, body(text), "--root", root).code == 0

    parent = make_thread("Phase two parent")
    child = make_thread("Phase two child", "--parent", parent)
    grandchild = make_thread("Phase two grandchild", "--parent", child)
    child_path = store.resolve_thread(root, child)
    (child_path / "docs" / "guide.md").write_text("# guide", encoding="utf-8")
    (child_path / "artifacts" / "data.csv").write_text("a\n1\n", encoding="utf-8")
    assert run("register", child, "docs/guide.md", "--kind", "doc", "--purpose", "orientation",
               "--read-when", "before merging", "--root", root).code == 0
    assert run("register", child, "artifacts/data.csv", "--kind", "artifact",
               "--purpose", "the numbers", "--root", root).code == 0
    assert run("task", "add", child, "carry this to the parent", "--root", root).code == 0
    for identifier in (child, grandchild, parent):
        checkpoint(identifier, "A synthesis.\n\n## Status\nGreen.\n")

    merge_body = body(f"Merged {child}: phase two is in.\n\n## From {child}\n"
                      "It ran every verb once.\n\n## Status\nGreen.\n")
    assert run("merge", child, "--promote", "docs/guide.md", "--all-tasks", "--force",
               "--body", merge_body, "--root", root).code == 0
    # The merge reparented the grandchild, so it needs a checkpoint before it can be dropped.
    checkpoint(grandchild, "Adopted by the parent.\n\n## Status\nStill green.\n")
    assert run("drop", grandchild, "--root", root).code == 0
    assert run("reopen", grandchild, "--root", root).code == 0
    checkpoint(grandchild, "Reopened and re-synthesised.\n\n## Status\nGreen again.\n")

    revision = tmp_path / "revision.md"
    revision.write_text("The scope narrowed.\n", encoding="utf-8")
    assert run("revise", grandchild, revision, "--root", root).code == 0
    checkpoint(grandchild, "After the revision.\n\n## Status\nStill green.\n")
    assert run("archive", "--root", root).code == 0
    assert run("doctor", "--root", root).code == 0
    return root


def test_phase_two_writes_only_schema_valid_files(validators, exercised_phase_two):
    root = exercised_phase_two
    threads = store.iter_threads(root)
    assert len(threads) == 3
    seen: set[str] = set()
    for thread in threads:
        label = thread.name
        metadata, _ = store.parse_frontmatter((thread / "origin.md").read_text(encoding="utf-8"))
        check(validators, "origin.schema.json", metadata, f"{label} origin.md")
        for event in events.read_events(thread):
            check(validators, "event.schema.json", event, f"{label} event {event['id']} ({event['type']})")
            seen.add(event["type"])
        cache = yaml.safe_load((thread / "thread.yml").read_text(encoding="utf-8"))
        check(validators, "thread.schema.json", cache, f"{label} thread.yml")
        board = yaml.safe_load((thread / "tasks.yml").read_text(encoding="utf-8"))
        check(validators, "tasks.schema.json", board, f"{label} tasks.yml")
        for checkpoint in sorted((thread / "checkpoints").glob("c*.md")):
            front, _ = store.parse_frontmatter(checkpoint.read_text(encoding="utf-8"))
            check(validators, "checkpoint.schema.json", front, f"{label} {checkpoint.name}")
    assert seen >= {
        "merged-into", "child-merged", "child-dropped", "child-reopened",
        "child-adopted", "reparented", "reopened", "origin-revised", "state-changed",
    }


def test_spec_sample_instances_still_match_the_schemas():
    """schemas/validate.py carries the hand-written examples; keep them honest."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, str(SCHEMAS / "validate.py")], capture_output=True, text=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "failures: 0" in result.stdout
