# Thread lifecycle

Read this before completing, dropping, revising, reanchoring, or reopening a
thread. For merging a subthread into its parent, see merging.md.

## States

- **active:** being worked on, or available to be. New threads start here.
- **inactive:** 14 days with no activity. `thread doctor` sets this, and
  any new activity (a claim, a note, anything) makes the thread active
  again. You don't need to do anything about it. It keeps `thread list`
  focused on live work.

A thread ends in one of three states. Each one moves it to
`threads/archived/<year-month>/` in its namespace:

- **merged:** a finished subthread whose result went into its parent. See
  merging.md.
- **completed:** a finished thread with no parent.
- **dropped:** a thread that was stopped because it wasn't worth pursuing.

The state is shown in `thread list`, in `thread view`, and in a parent's
list of subthreads, so anyone looking back can tell finished work from
abandoned work without opening it. Archived threads keep everything, and
`thread view <id>` still works on them.

## Before any ending

Completing, dropping, merging, revising, and reanchoring all need the thread
to be checkpointed first, with no events since the last checkpoint. If it
isn't, the tool refuses and tells you. When a thread is ending, that
checkpoint is its final word. Anyone who later wonders what came of the work
will read it.

If the thread has unfinished subthreads, completing or dropping it will
refuse. Merge or drop them first. When dropping a subthread, you can pass
`--force` to move its own subthreads up to its parent.

## When the work is done

For a subthread, **merge** it into its parent (see merging.md). For a thread
with no parent:

```
thread complete <id>
```

The final checkpoint should say what was achieved and where the results
are. If the origin has completion criteria, say how they were met. If
something was left undone, say what and why.

`complete` refuses on a subthread, because merging is how a finished
subthread's result reaches the parent.

## When the work isn't worth pursuing

```
thread drop <id>
```

Use it when you've decided to stop, for any thread, subthreads included.
Maybe the approach didn't work, the question stopped mattering, or
something else made the work unnecessary. The final checkpoint should say
why, and what was tried, so nobody repeats it.

Dropping a subthread records an event on the parent, so the parent's view
shows that it was dropped. Its results aren't merged into the parent. If
the reason matters to the parent's work, say so in the parent's next
checkpoint.

A dropped thread was stopped before it achieved what it was for, even if some
of the work got done. If it achieved what it was for, it's completed or
merged. If it turned into different work, it hasn't ended: reanchor it (below).

## When the origin no longer fits

The origin is never edited. When it stops matching the work, reread its
Context & Motivation.

**The reason for the work still holds, and your understanding changed.**
Maybe the goal got clearer, the scope moved, a constraint turned out not to
be hard, or the completion criteria were wrong. **Revise:**

```
thread revise <id> revision.md
```

This appends your text to the origin under a dated heading, and the original
stays above it. Say what changed, why, and what it means for the work.
Don't use a revision to record progress. That's what checkpoints are for.

**The context for the work has shifted, and the work carries on.** It has
grown into something bigger, or turned into something else, but the tasks,
subthreads, and history still belong to it. **Reanchor:**

```
thread reanchor <id> --origin new-origin.md --body checkpoint.md [--title "new title"]
```

This replaces the origin in place and writes a checkpoint, in one step. The
old origin moves to `origin-1.md` (with its revisions), and everything else
stays: id, tasks, subthreads, checkpoints, history. The view marks where in
the history the origin changed, so earlier checkpoints aren't read against
the new one.

Write the new origin as if the thread were being created today. It has to
stand on its own: a reader who never sees the old one should understand the
work completely. Don't write it in reference to the old origin ("now",
"widened from", "unlike before"). If the original words are still the reason
for the work, quote them again. The only place the change is discussed is a
short `## Previous origin` section at the end (required, at most 500
characters): what the earlier framing was, what changed, and why. The tool
adds a pointer to the old file under it, and keeps that section last. Run
without `--origin` to print the template.

The checkpoint then says where the work stands against the new origin. Run
without `--body` to print its template. 

Use reanchor sparingly, as it risks drift due to the origin changing. 

**The original question was the wrong one, and the work doesn't carry on.**
Drop the thread (or complete it, if it achieved something), create a new
one, and link them so the next reader can follow the trail:

```
thread link <new-id> continues <old-id>
```

## Reopening

`thread reopen <id>` brings a completed or dropped thread back to active and
out of the archive.
