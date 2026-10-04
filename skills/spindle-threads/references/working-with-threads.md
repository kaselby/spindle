# Working with threads

The judgment calls that come up while you work: where to record something, when
to checkpoint, and what to do when the work grows or the goal moves.

## Where something goes

Everything you learn or decide has one right home, chosen by how long it stays
true and who needs to see it:

- **A task** (`thread task add`): something that needs doing and that you aren't
  doing now. Close it when it's done; remove it when it no longer needs doing.
- **A note** (`thread note`): a finding worth keeping, like a measurement or a
  dead end. Notes stay in the log but aren't on the view page. They're the raw
  record you write checkpoints from.
- **The checkpoint:** anything the next session must see to pick up the work. If
  a note matters that much, it goes here too.
- **A decision:** a choice that later work depends on, and why
  (`thread decide`).
- **An artifact:** something the work produced that a later session will use.

When in doubt: if it will be wrong after the next checkpoint, it belongs in the
checkpoint, not an artifact.

## When to checkpoint

Checkpoints are the main way that progress is tracked. Each checkpoint captures
a snapshot of the thread at its current point: what was finished, where things
stand, what comes next. It's critical to write good checkpoints in order to keep
the thread up to date.

In general, checkpoints should be written whenever something significant has
been accomplished or changed. Small tasks don't require a checkpoint, but any
time something significant has been finished a checkpoint should be written.
Similarly any time the work changes direction, the problem expands, a critical
decision is made, and so on. These are also good points to checkpoint.

A typical session might write one or two checkpoints. Shorter ones write fewer,
longer ones write more.

The `thread` CLI will flag when there have been many events since the last
checkpoint. This is just a reminder; it isn't mandatory.

Read `references/checkpoints.md` for full details on how to write a checkpoint.

## When the work grows

New work that turns up inside a thread is one of three things:

- **A task** if it's a single step with no history of its own.
- **A subthread** if it serves this thread's goal but is a stream of work of its
  own: it will need its own checkpoints, another session could take it on in
  parallel, or its detail would crowd the parent's checkpoints. Use
  `thread promote` if it's already a task (`references/creating-a-thread.md`).
- **A separate thread** if it serves a different goal, even though it came up
  here. Link the two with `thread link <id> related <other-id>`.

## When the goal moves

Sometimes a thread may change direction or framing. Assumptions were wrong, the
initial approach doesn't work, the scope changes. These may require changes to
`origin.md`, which defines the initial scope, problem definition and context. Do
not edit this file directly; it is immutable. Instead, use the thread tools:

- **Your understanding shifted** but it's the same work: `thread revise` appends
  a dated revision to the origin.
- **It has become different work:** finish this thread and start a new one
  that `continues` it.
- **It's no longer worth doing:** `thread drop` ends it.

See `references/changing-direction.md` for each. If the work is just on hold, do
nothing: a thread with no activity for 14 days goes inactive by itself, and any
write makes it active again.
