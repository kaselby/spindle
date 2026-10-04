# Why threads are built the way they are

You don't need this for everyday use. Read it when you hit a situation the other
docs don't cover, and you need to understand what each part is for well enough
to work out what to do. Every part of the design answers a specific way that
long-running agent work goes wrong.

## The problem

A piece of work often outlasts one session. The next session starts with no
memory, and it needs more than the facts the last one had. It needs the
*understanding*: why the work matters, what's been decided, what's being tried,
and what to be careful of. That has to keep working across many handoffs with no
person stepping in to correct course.

Two failures keep coming up:

- **Drift.** Each handoff re-summarizes the goal. Each summary is a little off,
  and the errors add up. After ten sessions the work is aimed at something
  slightly different from what was asked, and nobody can tell, because nobody
  still has the original.
- **Bloat.** Recording everything feels safe. But a new session can't read
  everything, so it either reads too much and loses the thread, or skims and
  misses what mattered. Recording more makes the important parts harder to find.

A 17-day audit of an earlier version of this system, used across about a hundred
sessions, showed both failures. It also showed a third that explains much of the
design: **anything that depended on someone coming back later to tidy up didn't
happen.** Nobody merged children, rewrote pivots, cleaned stale tasks, or acted
on warnings. Writing was cheap and happened while the work was fresh. Curating
needed a later session to care, and none did.

## The principles

**Separate things that change at different rates.** Why the work exists (origin)
almost never changes. Where it stands (checkpoint) changes every session or so.
What happened (the log) grows constantly. In a single file, the fast-changing
material buries the slow. Each gets its own place, with its own rules.

**Metadata is a file you edit; the log is what happened.** What a thread *is*
(its title, its parent, flags other tools set) lives in thread.yml, and people
and agents edit it directly. What *happened* lives in the log, append-only. What
*state* the thread is in (active or ended, who's working, how much is unsynced,
its subthreads) is computed from the log whenever it's read and never stored, so
there is no copy to drift. The origin is narrative only. An earlier design made
the log the only way anything changes, with thread.yml a cache rebuilt from it.
Its main benefit, conflict-free sync of one store across machines, doesn't
apply, because threads aren't synced between computers, and a single metadata
file that you edit when you need to is simpler. What the log gave up is a record
of hand edits; the view recovers the part that matters by diffing thread.yml
against the copy each checkpoint keeps.

**Every reason is anchored to one fixed point.** The origin is never edited in
place. Checkpoints are written against the origin, not against the previous
checkpoint, so a distortion in one checkpoint isn't carried into the next. If
understanding changes, a revision is appended with the original still visible,
so the change itself is on record. If the work becomes something else, it
becomes a new thread with its own origin.

**Record freely, show carefully.** The log takes anything, cheaply, and is never
shown on the orientation page. That's why recording freely is safe. What *is*
shown is either written deliberately (origin, checkpoint, orientation) or
generated with a limit on its size.

**The tool enforces what it can, because rules in prompts don't hold.** The
earlier system asked for short status files. Agents wrote single lines of 900
characters, and the line-count check never fired. It asked for checkpoints at
meaningful moments, and got six sign-offs in 26 minutes. So wherever a rule can
be a check, it is: size limits on each part of a checkpoint, refusal to end a
thread that hasn't been checkpointed, a checkpoint required before release.
What's left for you is the judgment no tool can make, and the docs explain why
each of those judgments matters.

**Every duty has something that triggers it.** "Someone should come back and
tidy this" isn't a trigger. Duties happen at a moment the work already passes
through (merge requires a checkpoint), when a limit is crossed (the nudge at 8
events), or on the next command anyone runs (expired claims get released then).
Nothing depends on a session remembering to do it.

**Nothing coordinates.** There's no lock, no central process, and no owner.
Claims show who's present. The one conflict check (`--at`) stops you from
writing a checkpoint over events you haven't seen. Problems like stale claims or
files nobody registered surface in `view` and `doctor` for whoever arrives next.

## Why each part exists

| Part | Prevents | How |
|---|---|---|
| **Origin** | drift | Written once, in the asker's words where possible, and never edited in place (revise appends; different work gets a new thread). It's the fixed point everything else is measured against. |
| **Checkpoint** | drift, bloat | One deliberate statement of where things stand, with limited size, written against the origin. The latest one is the current state; all of them together show how the work evolved. |
| **Headline** | bloat | A one-line limit lets the view page show every checkpoint in the history without the history taking over the page. |
| **Inherited** (max 3) | silent loss, and pile-up | Keeps a critical warning from being dropped between checkpoints, capped because the earlier equivalent grew forever. |
| **Log** | lost information, bloat | Everything is kept, and nothing in it is shown by default. |
| **Notes** in the log | bloat | A place for findings that doesn't compete with the checkpoint. In the earlier system, notes on the orientation path had swallowed the real state. |
| **thread.yml** | a second copy of the truth | The one place metadata lives, edited directly and checked on every read. State is computed, never stored beside it. |
| **Orientation** (max 1,500 characters) | slow orientation | Hand-written pointers and what to read first, including things outside the thread that registration can't point at. Capped and checked, because one that grows is status moving to the wrong place. |
| **Decisions** | lost reasons | Each choice later work depends on, with the reason, so a later session can judge whether it still holds. Working by default and settled only when the user addressed it, because agents tend to record decisions nobody made. Superseded rather than edited, so the change of mind is on record. |
| **Subthreads** | tasks carrying hidden reasoning | Work big enough to need its own reasoning gets its own origin and checkpoints, instead of stuffing that reasoning into a task's one line. |
| **Merge writes the parent's checkpoint** | parents going stale | The moment a child finishes is the one moment someone is sure to be thinking about the parent. |
| **Size guard on register** | disk bloat | The earlier system ended up with 7 GB of model weights in one thread's scratch, committed to git forever. |
| **Scratch outside git** | the same | Work in progress is free to be messy and large. |

## What was deliberately left out

- **Locks and exclusive claims.** They bring stale-lock recovery, heartbeats,
  and takeover rules. In the earlier system, many sessions shared threads with
  claims alone and nothing was corrupted. The `--at` check covers the one real
  risk, which is a checkpoint written over events you haven't seen.
- **Rules for when to hand off.** Threads describe how to capture state, not
  when a session should stop.
