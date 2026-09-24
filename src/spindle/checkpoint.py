"""Checkpoint body validation, event-log injection, and commit."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from . import events, gitops, guide
from .limits import LIMITS
from .store import NeedsInput, ThreadError, atomic_text, markdown, strip_comments

_HEADING = re.compile(r"^##\s+(.+?)\s*$")
_PROVENANCE = re.compile(r"\(from (c\d{4})\)$")


def _refuse(problem: str, doc: str = "checkpointing.md") -> ThreadError:
    return ThreadError(f"{problem} ({guide.doc(doc)})")


def _headings(lines: list[str]) -> dict[str, tuple[int, int]]:
    """Each ``## `` section's (first body line, end) by lowercased name."""
    found: dict[str, tuple[int, int]] = {}
    headings: list[tuple[str, int]] = []
    for index, line in enumerate(lines):
        match = _HEADING.match(line)
        if match:
            headings.append((match.group(1).strip().lower(), index))
    for position, (name, start) in enumerate(headings):
        end = headings[position + 1][1] if position + 1 < len(headings) else len(lines)
        found[name] = (start + 1, end)
    return found


def _section(lines: list[str], span: tuple[int, int]) -> str:
    return "\n".join(lines[span[0]:span[1]]).strip()


def _check_headline(headline: str, doc: str, after: str) -> None:
    if len(headline) > LIMITS["headline_chars"]:
        raise _refuse(
            f"checkpoint headline (the first line) is {len(headline)} characters; the limit is "
            f"{LIMITS['headline_chars']}. Shorten it and put detail in {after}", doc,
        )


def _status(found: dict[str, tuple[int, int]], lines: list[str], doc: str, *,
            missing: str, empty: str) -> str:
    if "event log" in found:
        raise _refuse("remove the `## Event log` section; the tool writes it from the log", doc)
    if "status" not in found:
        raise _refuse(f"checkpoint needs a `## Status` section: {missing} "
                      f"(at most {LIMITS['status_chars']} characters)", doc)
    status = _section(lines, found["status"])
    if not status:
        raise _refuse(f"checkpoint `## Status` is empty; {empty}", doc)
    if len(status) > LIMITS["status_chars"]:
        raise _refuse(
            f"checkpoint `## Status` is {len(status)} characters; the limit is {LIMITS['status_chars']}. "
            "Keep what the next session needs to act on; the event log already keeps the history", doc,
        )
    return status


def _sections(text: str) -> tuple[str, str, str | None]:
    lines = text.strip().splitlines()
    first_heading = next((i for i, line in enumerate(lines) if line.startswith("## ")), len(lines))
    outline = "\n".join(lines[:first_heading]).strip()
    if not outline:
        raise _refuse(
            "checkpoint needs a headline and outline before `## Status`: a first line of at most "
            f"{LIMITS['headline_chars']} characters, then a few sentences"
        )
    headline = next((line.strip() for line in lines[:first_heading] if line.strip()), "")
    _check_headline(headline, "checkpointing.md", "the outline below it")
    if len(outline) > LIMITS["outline_chars"]:
        raise _refuse(
            f"checkpoint outline (everything before the first ## heading) is {len(outline)} characters; "
            f"the limit is {LIMITS['outline_chars']}. Keep it to a few sentences and move detail into ## Status"
        )
    found = _headings(lines)
    status = _status(found, lines, "checkpointing.md",
                      missing="where things stand against the origin, what's open, what's next",
                      empty="say where things stand, what's open, and what's next")
    inherited = _section(lines, found["inherited"]) or None if "inherited" in found else None
    return outline, status, inherited


def _inherited_items(inherited_text: str | None, doc: str = "checkpointing.md") -> list[dict[str, str]]:
    items: list[dict[str, str]] = []
    if not inherited_text:
        return items
    lines = [line for line in inherited_text.splitlines() if line.strip()]
    if len(lines) > LIMITS["inherited_items"]:
        raise _refuse(
            f"checkpoint `## Inherited` has {len(lines)} lines; the limit is "
            f"{LIMITS['inherited_items']} one-line bullets. Keep only what still matters", doc,
        )
    for line in lines:
        if not line.startswith(('- ', '* ')):
            raise _refuse(f"each `## Inherited` item must be a one-line bullet starting with \"- \"; got: {line[:60]}", doc)
        if len(line[2:]) > LIMITS["inherited_chars"]:
            raise _refuse(
                f"an `## Inherited` item is {len(line[2:])} characters; the limit is "
                f"{LIMITS['inherited_chars']}: {line[:60]}…", doc,
            )
        match = _PROVENANCE.search(line)
        if not match:
            raise _refuse(
                "each `## Inherited` item must end with the checkpoint it came from, like "
                f"\"(from c0003)\"; this one doesn't: {line[:80]}", doc,
            )
        items.append({"since": match.group(1), "text": line[2:]})
    return items


def _without_empty_section(source: str, name: str) -> str:
    lines = source.splitlines()
    found = _headings(lines)
    span = found.get(name)
    if span is None or _section(lines, span):
        return source
    del lines[span[0] - 1:span[1]]
    return "\n".join(lines).strip()


def parse_body(text: str) -> dict[str, Any]:
    source = strip_comments(text).strip()
    outline, status, inherited_text = _sections(source)
    if inherited_text is None:
        source = _without_empty_section(source, "inherited")
    items = _inherited_items(inherited_text)
    return {

        "headline": outline.splitlines()[0].strip(),
        "outline": outline,
        "status": status,
        "inherited-text": inherited_text,
        "inherited": items,
        "source": source,
    }


def _without_tool_block(text: str) -> str:
    """Drop a pasted copy of the tool's facts (guide.merge_facts) from a From
    narrative: the marker line and the bullets under it. The tool writes a
    fresh copy, so a pasted one would only duplicate it."""
    kept: list[str] = []
    skipping = False
    for line in text.splitlines():
        if guide.is_facts_marker(line):
            skipping = True
            continue
        if skipping and (line.startswith(("- ", "* ", "  ")) or not line.strip()):
            continue
        skipping = False
        kept.append(line)
    return "\n".join(kept).strip()


def parse_merge_body(text: str, child_id: str) -> dict[str, Any]:
    """A merge checkpoint: headline, `## From <child>`, `## Status`, optional
    `## Inherited`. The From narrative is the author's; the tool appends its
    facts when it writes the file (see create's ``merge_facts``)."""
    doc = "merging.md"
    source = strip_comments(text).strip()
    lines = source.splitlines()
    first_heading = next((i for i, line in enumerate(lines) if line.startswith("## ")), len(lines))
    before = [line.strip() for line in lines[:first_heading] if line.strip()]
    heading = f"## From {child_id}"
    if not before:
        raise _refuse(
            f"a merge checkpoint starts with a headline: one line of at most {LIMITS['headline_chars']} "
            f"characters before `{heading}`, like \"Merged {child_id}: <what it brought>\"", doc,
        )
    if len(before) > 1:
        raise _refuse(
            f"a merge checkpoint has only its headline before `{heading}`, but this one has "
            f"{len(before)} lines there. Keep the first line as the headline and move the rest into "
            f"`{heading}` (what the subthread did) or `## Status` (what it means for the parent)", doc,
        )
    headline = before[0]
    _check_headline(headline, doc, f"`{heading}`")
    found = _headings(lines)
    key = f"from {child_id}".lower()
    if key not in found:
        others = [name for name in found if name.startswith("from")]
        hint = f" (found `## {others[0]}`; the heading names the subthread being merged)" if others else ""
        raise _refuse(
            f"a merge checkpoint needs a `{heading}` section{hint}: what {child_id} did over its life "
            f"and the state it ended in, at most {LIMITS['from_chars']} characters. "
            f"`thread merge {child_id}` without --body prints the template", doc,
        )
    narrative = _without_tool_block(_section(lines, found[key]))
    if not narrative:
        raise _refuse(
            f"`{heading}` has no narrative. Above the tool's facts, write what {child_id} did over its "
            f"life and the state it ended in: what it found or produced, and what it left unfinished", doc,
        )
    if len(narrative) > LIMITS["from_chars"]:
        raise _refuse(
            f"`{heading}` is {len(narrative)} characters; the limit is {LIMITS['from_chars']}. Keep the "
            f"arc and the end state; {child_id}'s own checkpoints keep the detail, and the parent's view "
            "links to them", doc,
        )
    status = _status(found, lines, doc,
                     missing="how merging this subthread changes the parent's state, written against "
                             "the parent's origin",
                     empty="say how merging this subthread changes the parent's state: what it now "
                           "knows, what changes about its next steps")
    inherited_text = _section(lines, found["inherited"]) or None if "inherited" in found else None
    if inherited_text is None:
        source = _without_empty_section(source, "inherited")
    return {
        "headline": headline,

        "outline": headline,
        "from": narrative,
        "status": status,
        "inherited-text": inherited_text,
        "inherited": _inherited_items(inherited_text, doc),
        "source": source,
    }


def _inject_event_log(source: str, rendered_log: str) -> str:
    lines = source.splitlines()
    status_heading = _headings(lines)["status"][0] - 1
    lines[status_heading:status_heading] = ["## Event log", rendered_log, ""]
    return "\n".join(lines).strip() + "\n"


def _merge_source(source: str, child_id: str, narrative: str, facts: str) -> str:
    lines = source.splitlines()
    span = _headings(lines)[f"from {child_id}".lower()]
    replacement = [*narrative.splitlines(), "", *facts.strip().splitlines(), ""]
    lines[span[0]:span[1]] = replacement
    return "\n".join(lines).strip()


def next_id(thread: Path) -> str:
    ordinals = []

    for path in (thread / "checkpoints").glob("c*.md"):
        try:
            ordinals.append(int(path.stem[1:]))
        except ValueError:
            continue
    return f"c{max(ordinals, default=0) + 1:04d}"


def _events_since_previous(log: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return events.since_checkpoint(log)


def _render_event_log(log: list[dict[str, Any]]) -> str:
    if not log:
        return "- None."
    rows = []
    for event in log:
        summary = events.event_summary(event)
        rows.append(f"- {event['id']} by {event['by']['session']} {event['type']}: {summary}")
    return "\n".join(rows)


def _retry(identifier: str, latest_id: str) -> str:
    return (
        f"Read them with `thread replay {identifier} --since-checkpoint`, update your checkpoint "
        f"if they change the picture, and retry with `--at {latest_id}`."
    )


def template(thread: Path, by: dict[str, str]) -> str:
    """The checkpoint template, filled with the events it should cover."""
    log = events.read_events(thread)
    recent = events.since_checkpoint(log)
    foreign = [
        event for event in recent
        if event["by"]["session"] != by["session"] and events.carries_work(event)
    ]
    previous = next((e["payload"]["checkpoint"] for e in reversed(log) if e["type"] == "checkpoint"), None)
    return guide.checkpoint_template(thread.name.split("-", 1)[0], recent, foreign, log[-1]["id"], previous)


def create(
    root: Path,
    thread: Path,
    body_path: Path | None,
    by: dict[str, str],
    *,
    at: str | None,
    forced_by: str | None = None,
    body_text: str | None = None,
    commit: bool = True,
    merged: tuple[str, str] | None = None,
    skip_cas: bool = False,
) -> tuple[str, str]:
    """Write a checkpoint. ``commit=False`` leaves the commit to the caller,
    which is how merge gets one commit for the whole operation.

    ``merged`` is (child id, facts block) for a merge checkpoint: the body is
    parsed as one (parse_merge_body) and the facts go under the author's
    narrative in ``## From <child>``."""
    if body_text is None and body_path is None:
        raise NeedsInput(template(thread, by))
    if body_text is None:
        body_text = body_path.read_text(encoding="utf-8")  # type: ignore[union-attr]
    parsed = parse_merge_body(body_text, merged[0]) if merged else parse_body(body_text)
    log = events.read_events(thread)
    current_tip = log[-1]["id"]
    recent = _events_since_previous(log)
    foreign = [
        event for event in recent
        if event["by"]["session"] != by["session"] and events.carries_work(event)
    ]
    identifier = thread.name.split("-", 1)[0]
    if foreign and at is None and not skip_cas:
        raise ThreadError(
            f"another session has written to {identifier} since its last checkpoint:\n"
            + "\n".join(guide.event_lines(foreign)) + "\n"
            + _retry(identifier, current_tip), code=4,
        )
    expected = current_tip if skip_cas else (at or current_tip)
    if expected != current_tip:
        try:
            cursor = next(i for i, event in enumerate(log) if event["id"] == expected)
        except StopIteration:
            raise ThreadError(
                f"--at {expected} is not an event in {identifier}. --at takes the latest event id "
                f"you've read; right now that is {current_tip} (shown by `thread view {identifier}`).",
                code=4,
            ) from None
        new = log[cursor + 1 :]
        raise ThreadError(
            f"another session has written to {identifier} since you last looked "
            f"(after {expected}):\n" + "\n".join(guide.event_lines(new)) + "\n"
            + _retry(identifier, current_tip), code=4,
        )

    checkpoint_id = next_id(thread)
    metadata: dict[str, Any] = {
        "id": checkpoint_id,
        "thread": thread.name.split("-", 1)[0],
        "at": current_tip,
        "ts": events.timestamp(),
        "by": by,
        "headline": parsed["headline"],
    }
    if parsed["inherited"]:
        metadata["inherited"] = parsed["inherited"]
    if forced_by:
        metadata["forced-by"] = forced_by
    source = parsed["source"]
    if merged:
        source = _merge_source(source, merged[0], parsed["from"], merged[1])
    body = _inject_event_log(source, _render_event_log(recent))

    destination = thread / "checkpoints" / f"{checkpoint_id}.md"
    atomic_text(destination, markdown(metadata, body))
    try:
        events.append(thread, "checkpoint", {
            "checkpoint": checkpoint_id, "at": current_tip, "headline": parsed["headline"]
        }, by, expected_tip=current_tip)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    from .render import write_index

    write_index(thread)
    if not commit:
        return checkpoint_id, ""
    message = f"checkpoint {thread.name.split('-', 1)[0]}@{checkpoint_id}: {parsed['headline']}"
    sha = gitops.commit(root, message, [thread])
    return checkpoint_id, sha

