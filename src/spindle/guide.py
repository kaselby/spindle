"""Text the tool prints to teach itself: templates, doc pointers, event lists.

Most readers meet the tool through what it prints, not through the skill, so
the wording here matches the skill's (see skills/spindle-threads/SKILL.md).
"""

from __future__ import annotations

import re
from typing import Any

from . import store
from .limits import LIMITS

EVENT_LIST_CAP = 15
CLAIMS_DONT_LOCK = "Claims show who's working; they don't lock anything."

NAMESPACE_HELP = "put the thread in this namespace (<store>/<ns>/), a folder that groups threads"
NAMESPACE_RULE = "1-32 characters: lowercase letters, digits, '-' and '_', starting with a letter or digit"


def doc(name: str) -> str:
    """Pointer to one of the moment docs in the spindle-threads skill."""
    return f"see references/{name} in the spindle-threads skill"


def strip_comments(text: str) -> str:
    """Drop <!-- --> comments (store.strip_comments) and tidy the blank runs they leave."""
    text = store.strip_comments(text)
    text = "\n".join(line.rstrip() for line in text.splitlines())
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


def _clip(text: str, limit: int = 100) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def event_lines(log: list[dict[str, Any]], *, cap: int = EVENT_LIST_CAP,
                ids: bool = True, indent: str = "- ") -> list[str]:
    """One line per event, newest last, capped with an "and N more" line."""
    from .events import event_summary

    shown = log[:cap]
    rows = []
    for event in shown:
        head = f"{event['id']} " if ids else ""
        rows.append(
            f"{indent}{head}{event['type']} by {event['by']['session']}: "
            f"{_clip(event_summary(event))}"
        )
    if len(log) > cap:
        rows.append(f"{indent}… and {len(log) - cap} more")
    return rows


ORIGIN_TEMPLATE = """## Context & Motivation
<!-- Required. Why this work exists. Quote whoever asked, in their words. -->

## Scope
<!-- Optional. What's in and what's out. Not a plan. -->

## Constraints
<!-- Optional, usually empty. Only real hard constraints, written "X, because Y". Don't invent any. -->

## Completion criteria
<!-- Optional, usually omitted. A hard target, if there is one (common for automated work). -->
"""


def origin_template(command: str) -> str:
    """The origin template with a header saying how to use it.

    ``command`` is the command to rerun, with ``<file>`` where the path goes.
    """
    return (
        f"<!-- Origin template. Fill it in, save it to a file, and run:\n"
        f"       {command}\n"
        f"     The origin is the thread's fixed point: every checkpoint is measured against it.\n"
        f"     Comment lines like this one are ignored. Guide: {doc('creating-a-thread.md')}. -->\n\n"
        + ORIGIN_TEMPLATE
    )


def checkpoint_template(thread_id: str, recent: list[dict[str, Any]],
                        foreign: list[dict[str, Any]], latest_id: str,
                        previous: str | None) -> str:
    command = f"thread checkpoint {thread_id} <file>"
    at_line = ""
    if foreign:
        sessions = ", ".join(sorted({event["by"]["session"] for event in foreign}))
        command += f" --at {latest_id}"
        at_line = (
            f"\n     --at is needed because another session ({sessions}) wrote since the last checkpoint;"
            f"\n     it is the latest event id, and the tool refuses if newer events arrive first."
        )
    since = f"since {previous}" if previous else "since the thread was created"
    if recent:
        material = "\n".join(event_lines(recent, ids=False, indent="     - "))
        events_block = (
            f"<!-- {len(recent)} events {since} (the material for this checkpoint;\n"
            f"     full text: `thread replay {thread_id} --since-checkpoint`):\n"
            f"{material.replace('-->', '->')}\n-->\n\n"
        )
    else:
        events_block = f"<!-- No events {since}. -->\n\n"
    replaces = (
        f"\n     This checkpoint replaces {previous} as the thread's current state, so write it in full."
        if previous else ""
    )
    return (
        f"<!-- Checkpoint template for {thread_id}. Fill it in, save it to a file, and run:\n"
        f"       {command}{at_line}{replaces}\n"
        f"     Comment lines like this one are ignored. Guide: {doc('checkpoints.md')}. -->\n\n"
        f"{events_block}"
        f"<!-- First line: a headline, at most {LIMITS['headline_chars']} characters.\n"
        f"     Then a few sentences of outline. Headline and outline together: at most "
        f"{LIMITS['outline_chars']} characters. -->\n\n\n"
        f"## Status\n"
        f"<!-- Required, at most {LIMITS['status_chars']} characters. Where things stand, measured against the "
        f"origin:\n     the current state, what's open, what's next. -->\n\n\n"
        f"## Inherited\n"
        f"<!-- Optional; delete this section if nothing carries over. At most {LIMITS['inherited_items']} "
        f"one-line bullets,\n     each ending with the checkpoint it came from, like \"(from c0003)\". -->\n"
    )


FACTS_MARKER = "Recorded by the tool at merge:"


def is_facts_marker(line: str) -> bool:
    """True for FACTS_MARKER, however an author may have restyled it."""
    return line.strip().strip("*_ ").lower().startswith(FACTS_MARKER.lower().rstrip(":"))


def _count(number: int, noun: str) -> str:
    return f"{number} {noun}{'' if number == 1 else 's'}"


def merge_facts(child_id: str, parent_id: str, child_checkpoint: str, child_headline: str,
                promoted: list[str], moved: list[tuple[str, str | None]],
                carried: list[tuple[str, str, str | None]], left_artifacts: int, left_tasks: int) -> str:
    """The block the tool writes under the author's narrative in `## From <child>`.

    ``moved`` is (task text, its new id on the parent) and ``carried`` is (the
    child's decision id, its title, its new id on the parent); the new ids are None in the
    template, before the merge has added them."""
    tasks = ", ".join(
        f"\"{_clip(text, 60)}\"" + (f" (now {new_id})" if new_id else "") for text, new_id in moved
    ) or "none"
    return "\n".join([
        FACTS_MARKER,
        f"- Final checkpoint: {child_checkpoint}, \"{child_headline}\"",
        f"- Promoted to {parent_id}: {', '.join(promoted) or 'none'}",
        f"- Tasks moved to {parent_id}: {tasks}",
        f"- Decisions carried to {parent_id}: " + (", ".join(
            f"{old} \"{_clip(title, 60)}\"" + (f" (now {new})" if new else "") for old, title, new in carried
        ) or "none"),
        f"- Left in {child_id}: {_count(left_artifacts, 'artifact')}, "
        f"{_count(left_tasks, 'open task')} (`thread view {child_id}`)",
    ]) + "\n"


def merge_template(child_id: str, parent_id: str, parent_checkpoint: str, command: str,
                   child_headline: str, facts: str, inherited: list[str] | None = None) -> str:
    """What `thread merge <child>` prints without --body: the parent's merge
    checkpoint, with the headline suggested and the tool's facts filled in."""
    carried = ""
    if inherited:
        rows = "\n".join(f"     - {item.replace('-->', '->')}" for item in inherited)
        carried = (f"\n     {parent_id}'s items now (carry one forward only while it's still true; "
                   f"if you drop one, say so in Status):\n{rows}")
    suggested = f"Merged {child_id}: {child_headline}"
    if len(suggested) > LIMITS["headline_chars"]:
        suggested = suggested[: LIMITS["headline_chars"] - 1].rstrip() + "…"
    return (
        f"<!-- Merge template: {child_id} into {parent_id}. Fill it in, save it to a file, and run:\n"
        f"       {command}\n"
        f"     This becomes {parent_id}'s next checkpoint, replacing {parent_checkpoint} as its current "
        f"state,\n     so write it in full. Comment lines like this one are ignored. "
        f"Guide: {doc('completion-and-merging.md')}. -->\n\n"
        f"<!-- First line: the headline, at most {LIMITS['headline_chars']} characters, and nothing else "
        f"before `## From {child_id}`.\n     A suggestion is filled in; say what the merge brought. -->\n"
        f"{suggested}\n\n"
        f"## From {child_id}\n"
        f"<!-- Required, at most {LIMITS['from_chars']} characters. What {child_id} did over its life and "
        f"the state it ended in:\n     what it found or produced, and what it left unfinished. "
        f"`thread view {child_id}` shows its checkpoints.\n"
        f"     The \"{FACTS_MARKER}\" lines below are the tool's: it writes them under your\n"
        f"     narrative when it merges, so you can leave them or delete them. -->\n\n\n"
        f"{facts.strip()}\n\n"
        f"## Status\n"
        f"<!-- Required, at most {LIMITS['status_chars']} characters. How does merging this subthread "
        f"change the parent's state?\n     What does the parent now know, what changes about its next "
        f"steps, what's newly open or no longer needed?\n     Write it against the parent's origin. -->\n\n\n"
        f"## Inherited\n"
        f"<!-- Optional; delete this section if nothing carries over. At most {LIMITS['inherited_items']} "
        f"one-line bullets,\n     each ending with the checkpoint it came from, like \"(from c0003)\".{carried} -->\n"
    )


def bad_namespace(value: str, source: str) -> str:
    """Refusal for a namespace that doesn't fit NAMESPACE_RULE, naming the fix.

    ``source`` is ``--ns`` or ``SPINDLE_NAMESPACE``: where the value came from.
    """
    suggestion = re.sub(r"[^a-z0-9_-]+", "-", value.lower()).strip("-_")[:32].rstrip("-_")
    example = f"--ns {suggestion}" if suggestion else "--ns research"
    if source == "SPINDLE_NAMESPACE":
        fix = (f"Fix or unset SPINDLE_NAMESPACE, or override it for this command "
               f"with {example} (or --ns default).")
    else:
        fix = f"Try {example}, or leave out --ns for the default namespace."
    return f"{source} {value!r} isn't a valid namespace. A namespace is {NAMESPACE_RULE}. {fix}"


ORIENTATION = "orientation.md"
