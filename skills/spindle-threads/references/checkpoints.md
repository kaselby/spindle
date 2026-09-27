# Checkpoints

A checkpoint records where the work stands. It's the part of the view page a new
session reads most closely, and often the only part it reads in full, so it has
to stand on its own. Each checkpoint replaces the last as the thread's current
state; older ones shrink to their headline on the view page.

## When

- After a milestone: something significant is done or decided.
- When your understanding changes: an approach failed, the problem turned out to
  be different, the plan changed.
- Before you stop. `thread release` refuses if you've done more than a few
  things since the last checkpoint. `--skip "<reason>"` releases without one,
  and the next session sees the reason.

Not after every small task. The view page shows the events since the last
checkpoint, and says so plainly when there are more than a handful.

## How

1. `thread checkpoint <id>` prints the template. It lists the events since the
   last checkpoint, which are your material.
2. Fill it in, save it to a file, and run `thread checkpoint <id> <file>`.

Writing one also commits the thread to git.

## What goes in it

**Headline** (the first line, at most 120 characters): what state the work is in
now. Past checkpoints show as their headlines, so together they read as the
thread's history. "Cause found: the cache key drops the locale" is a headline;
"Worked on the cache" isn't.

**Outline** (a few sentences after the headline; 600 characters with the
headline): the shape of where things are, for a reader deciding whether to read
on.

**Status** (required, at most 3,000 characters): where things stand, measured
against the origin. What's done, what's open, what's next, and anything the next
session needs that it can't get elsewhere: what was ruled out and why, where the
current attempt lives, what's half-finished. Write it in full; don't say "see
the previous checkpoint".

**Inherited** (optional, at most 3 one-line bullets): things from an earlier
checkpoint that are still true and still matter, each ending with where it came
from, like "(from c0003)". Drop one once it stops being true, and say so in
Status. Delete the section if nothing carries over.

Things that last belong elsewhere: how-tos and settled designs in docs, outputs
in artifacts (`references/artifacts-and-docs.md`).

## When someone else is writing too

Several sessions can work on a thread at once. If another session has written
since the last checkpoint, the template tells you to add `--at <event-id>`: the
latest event you've read. If newer events arrive before you write, the tool
refuses, so you don't write a checkpoint that misses them. Read what's new with
`thread replay <id>` and run it again.
