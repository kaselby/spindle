# Changing direction

The origin is the fixed point a thread is measured against, so it's never edited
in place. When the goal moves, you record the change instead, and the thread
keeps an honest history of what the work was for at each point.
`references/working-with-threads.md` covers which of these fits; this doc covers
how to do each.

## Revise: the understanding shifted

Use `thread revise` when it's still the same work but you understand it
differently: the problem is narrower or broader than it looked, a constraint
turned up, you learned the real reason behind the request.

Write a checkpoint first if there's work since the last one; revise refuses
until the latest checkpoint is current. Then write a short file saying what
changed in the understanding and why, and run `thread revise <id> <file>`. It's
appended to the origin under a dated "Revisions" heading, and the original text
stays as it was. Later checkpoints are read against the origin with its
revisions.

Keep a revision about the goal. New findings and changes of plan belong in a
checkpoint.

## New work: it has become something else

If the question you're answering now isn't the one the thread started with,
start a new thread for it. Write a final checkpoint on the old one saying where
it stood, then complete or drop it. Create the new thread with an origin that
stands on its own and names the old thread's id, and link the two with
`thread link <new> continues <old>`. Move over any open tasks that still apply.

## Drop: no longer worth doing

Use `thread drop` when the work isn't finished and won't be: the question was
answered another way, the need went away, or the approach is a dead end with
nothing behind it.

Write a final checkpoint first, saying why it's being dropped and what, if
anything, is worth keeping. That's what anyone who finds the thread later will
read. Then `thread drop <id>`. The thread is archived as dropped, so it's clear
it was abandoned rather than finished. If it's a subthread, the parent's log
records the drop.

Open subthreads block a drop. Merge or drop them first, or pass `--force` to
move them to the dropped thread's parent.

## Reopen

`thread reopen <id>` brings back a completed, dropped or merged thread when the
work turns out not to be over. Write a checkpoint soon after, saying why it's
open again. A subthread whose parent has also finished can't come back alone:
reopen the parent first.

A thread that went inactive doesn't need reopening. Anything written to it makes
it active again.
