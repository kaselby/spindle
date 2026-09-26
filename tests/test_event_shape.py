"""A malformed log line is named on read, not a traceback later."""

from __future__ import annotations

import json
from pathlib import Path

from spindle import events, store

SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"


def test_a_state_change_without_to_is_named_not_a_traceback(root, make_thread, run):
    identifier = make_thread("Damaged")
    log = store.resolve_thread(root, identifier) / "log.jsonl"
    bad = {"id": "20260101T000000-abcd", "ts": "2026-01-01T00:00:00Z",
           "by": {"session": "s1"}, "type": "state-changed", "payload": {"from": "active"}}
    with log.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(bad, separators=(",", ":")) + "\n")
    result = run("view", identifier, "--root", root)
    assert result.code != 0
    assert "malformed (state-changed payload is missing to)" in result.err
    assert "Traceback" not in result.err


def test_payload_keys_match_the_event_schema():
    schema = json.loads((SCHEMAS / "event.schema.json").read_text(encoding="utf-8"))
    assert tuple(schema["required"]) == events.EVENT_KEYS
    from_schema = {}
    for block in schema["allOf"]:
        kind = block["if"]["properties"]["type"]
        required = tuple(block["then"].get("properties", {}).get("payload", {}).get("required", []))
        for name in kind.get("enum", [kind.get("const")]):
            if required:
                from_schema[name] = required
    assert from_schema == events.PAYLOAD_KEYS
