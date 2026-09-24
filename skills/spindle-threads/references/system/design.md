# Why threads are built the way they are

You don't need this for everyday use. Read it when you hit a situation the
other docs don't cover, and you need to understand what each part is for
well enough to work out what to do. Every part of the design answers a
specific way that long-running agent work goes wrong.

## The problem

A piece of work often outlasts one session. The next session starts with
no memory, and it needs more than the facts the last one had. It needs the
*understanding*: why the work matters, what's been decided, what's being
tried, and what to be careful of. That has to keep working across many
handoffs with no person stepping in to correct course.

Two failures keep coming up:

- **Drift.** Each handoff re-summarizes the goal. Each summary is a little
  off, and the errors add up. After ten sessions the work is aimed at
  something slightly different from what was asked, and nobody can tell,
  because nobody still has the original.
- **Bloat.** Recording everything feels safe. But a new session can't read
  everything, so it either reads too much and loses the thread, or skims
  and misses what mattered. Recording more makes the important parts harder
  to find.

A 17-day audit of an earlier version of this system, used across about a
hundred sessions, showed both failures. It also showed a third that
explains much of the design: **anything that depended on someone coming back
later to tidy up didn't happen.** Nobody merged children, rewrote pivots,
cleaned stale tasks, or acted on warnings. Writing was cheap and happened
while the work was fresh. Curating needed a later session to care, and none
did.

## The principles

**Separate things that change at different rates.** Why the work exists
(origin) almost never changes. Where it stands (checkpoint) changes every
session or so. What happened (the log) grows constantly. In a single file,
the fast-changing material buries the slow. Each gets its own place, with
its own rules.

**Every reason is anchored to one fixed point.** The origin is never
rewritten. Checkpoints are written against the origin, not against the
previous checkpoint, so a distortion in one checkpoint isn't carried into
the next. If understanding changes, a revision is appended with the
original still visible, so the change itself is on record.

**Record freely, show carefully.** The log takes anything, cheaply, and is
never shown on the orientation page. That's why recording freely is safe.
What *is* shown is either written deliberately (origin, checkpoint, docs)
or generated with a limit on its size.

**The tool enforces what it can, because rules in prompts don't hold.** The
earlier system asked for short status files. Agents wrote single lines of
900 characters, and the line-count check never fired. It asked for
checkpoints at meaningful moments, and got six sign-offs in 26 minutes.
So wherever a rule can be a check, it is: size limits on each part of a
checkpoint, refusal to end a thread that hasn't been checkpointed, a
checkpoint required before release. What's left for you is the judgment no
tool can make, and the docs explain why each of those judgments matters.

**Every duty has something that triggers it.** "Someone should come back and
tidy this" isn't a trigger. Duties happen at a moment the work already
passes through (merge requires a checkpoint), when a limit is crossed (the
nudge at 8 events), or on the next command anyone runs (expired claims get
released then). Nothing depends on a session remembering to do it.

**Nothing coordinates.** There's no lock, no central process, and no owner.
Claims show who's present. The one conflict check (`--at`) stops you from
writing a checkpoint over events you haven't seen. Problems like stale
claims or files nobody registered surface in `view`
and `doctor` for whoever arrives next.

## Why each part exists

| Part | Prevents | How |
|---|---|---|
| **Origin** | drift | Written once, in the asker's words where possible, and never rewritten. It's the fixed point everything else is measured against. |
| **Checkpoint** | drift, bloat | One deliberate statement of where things stand, with limited size, written against the origin. The latest one is the current state; all of them together show how the work evolved. |
| **Headline** | bloat | A one-line limit lets the view page show every checkpoint in the history without the history taking over the page. |
| **Inherited** (max 3) | silent loss, and pile-up | Keeps a critical warning from being dropped between checkpoints, capped because the earlier equivalent grew forever. |
| **Log** | lost information, bloat | Everything is kept, and nothing in it is shown by default. |
| **Notes** in the log | bloat | A place for findings that doesn't compete with the checkpoint. In the earlier system, notes on the orientation path had swallowed the real state. |
| **Docs with a read-when** | lost knowledge | Knowledge every future session needs, placed on the view page with when to read it. That turns "remember to read the notes" into a listed pointer. |
| **Subthreads** | tasks carrying hidden reasoning | Work big enough to need its own reasoning gets its own origin and checkpoints, instead of stuffing that reasoning into a task's one line. |
| **Merge writes the parent's checkpoint** | parents going stale | The moment a child finishes is the one moment someone is sure to be thinking about the parent. |
| **Size guard on register** | disk bloat | The earlier system ended up with 7 GB of model weights in one thread's scratch, committed to git forever. |
| **Scratch outside git** | the same | Work in progress is free to be messy and large. |

## What was deliberately left out

- **Decision records.** Agents tend to write down decisions nobody actually
  made yet, and a recorded decision is hard to undo. Settled things go in
  Status. If they need to last, they go in a doc.
- **Locks and exclusive claims.** They bring stale-lock recovery, heartbeats,
  and takeover rules. In the earlier system, many sessions shared threads with
  claims alone and nothing was corrupted. The `--at` check covers the
  one real risk, which is a checkpoint written over events you haven't
  seen.
- **Rules for when to hand off.** Threads describe how to capture state, not
  when a session should stop.
