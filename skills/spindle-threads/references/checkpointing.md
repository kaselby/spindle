# Checkpointing

Read this before your first checkpoint in a session.

Merge checkpoints have their own structure. See merging.md.

## What it's for

The next session to pick up the thread will read the origin and your
checkpoint, and not much else. So the test for a checkpoint is this:

> Could someone who reads only the origin and this checkpoint pick up the
> work and make the same decisions you would?

When a checkpoint fails that test, the missing part is usually what's still
open, what you were about to do and why, or a warning you're keeping in your
head.

Write a real one even at the end of a session, when it feels like
paperwork. Once you leave, the checkpoint is all that's left of what you
knew. "Wrapped up, everything current" tells the next session nothing.

## Writing it

`thread checkpoint <id>` with no body prints the template, along with a list
of everything that's happened since the last checkpoint. Fill it in and save
it in scratch, then run `thread checkpoint <id> <file>`. The tool adds the
event log itself. It also enforces the length limits below and refuses a
body that goes over them.

### Outline: the lines before the first heading (600 characters)

**The first line is the headline** (one line, 120 characters). The view page
lists every checkpoint's headline, so the headlines together show how the
thread evolved. Say what changed, not that work happened. "Tokenizer ruled
out; sampling change reproduces the drop" is useful. "Continued
investigation" is not.

After the headline, write a few sentences on what happened since the last
checkpoint. The event log of what happened will automatically be shown, this is just a brief narrative accompaniment to that to describe in a few sentences the key things that were done.

### `## Status` (3,000 characters)

The current status of the thread. Reading this on its own should bring a new session largely up to speed on where the work currently sits and what is on the horizon to be done next. Reading the statuses of each checkpoint in order should fully capture the narrative history of what happened in the thread.

Don't carry things over from previous statuses, write it fresh each time. Reread the origin before writing the status - it should be written with the origin's framing in mind.

Describe the state, not your session. "I ran X, then Y" belongs in the
outline, or nowhere at all.

### `## Inherited` (optional; 3 items, one line each, 160 characters)

For something that must not be lost and won't naturally come up in Status,
like a standing warning or a preference someone stated. End each line with
the checkpoint it came from: `(from c0004)`. Carry an item forward only
while it's still true. When you drop one, mention it in Status. To avoid
bloat, this is capped at three items. This is a hard rule, don't try to get around it.
If information needs to be carried forward that doesn't fit, consider writing a doc - but avoid just filling it up with individual gotchas.

## When other sessions are working

A checkpoint describes the whole thread, so the tool won't accept one
written without seeing what other sessions have done. If another session has
written since the last checkpoint, pass `--at <event-id>` with the latest
event id (shown at the top of `thread view`). If you leave it out, or newer
events have arrived, the tool refuses and prints them. Read them, rewrite
your checkpoint if they change the picture, and retry with the id it gives
you.
