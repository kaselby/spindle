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

## Reanchor: it has become different work

Use `thread reanchor` when the question you're answering now isn't the one the
thread started with, but the history, tasks and artifacts still belong here. If
the new work would make as much sense as a fresh thread, create one and link it
with `continues` instead. Reanchor sparingly: a thread that keeps changing what
it's for becomes hard to read.

1. **Close out the old origin.** Write a checkpoint that says where the work
   stood against the old goal. Reanchor refuses until the latest checkpoint is
   current.
2. **Write the new origin:** `thread reanchor <id>` prints the template. Write
   it as if the thread were being created today, so it stands on its own, and
   end with a short **Previous origin** section (at most 500 characters): what
   the earlier framing was, what changed, and why.
3. **Write the checkpoint that opens it:** where things stand, measured against
   the new origin. `thread reanchor <id> --origin <file>` prints its template.
4. **Reanchor:** `thread reanchor <id> --origin <file> --body <checkpoint>`,
   with `--title "<new title>"` if the title no longer fits.

The old origin is kept as `origin-1.md` (then `origin-2.md`, and so on), and the
new one points back to it.

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
