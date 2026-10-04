# Completion and merging

A thread ends when its goal is met, not when every task is closed. How it ends
depends on where it sits: a subthread **merges** into its parent, and a
top-level thread **completes**. Either way the thread moves to the archive, and
its last checkpoint becomes the record of how it ended, so that checkpoint has
to be written for someone who will only ever read that one.

If the work isn't finished but is no longer worth doing, drop it instead
(`references/changing-direction.md`).

## Before either

Both commands refuse until the latest checkpoint covers everything that has
happened on the thread. Write a final checkpoint first. It should say what the
thread achieved against its origin, what it produced and where that lives, and
anything left open that someone might want to pick up later.

Open subthreads also block both. Merge or drop them first. (`--force` moves them
up to the parent instead, which only makes sense if the parent still wants that
work.)

## Completing a top-level thread

After the final checkpoint, `thread complete <id>`. The thread is archived and
leaves the session-start index. `thread reopen <id>` brings it back if the work
turns out not to be done.

## Merging a subthread

A merge is how a subthread's result reaches its parent. The parent gets a new
checkpoint describing what the subthread brought, and chooses what to take from
it. Merge is also the only way a subthread finishes: `thread complete` refuses
on a subthread, because its result would never reach the parent.

Both threads need current checkpoints: the child's final one, and the parent's
latest.

1. **Decide what the parent takes.**
   - **Artifacts:** `--promote <path> ...` copies them into the parent, where
     they're listed as the parent's own. Promote what the parent's work will
     use. Everything else stays in the archived child; the parent's `index.md`
     still lists it, and the view page counts it.
   - **Open tasks:** `--tasks <id> ...` or `--all-tasks` copies them onto the
     parent's list. Take the ones that still need doing; the rest stay with the
     child.
2. **Print the template:** `thread merge <child-id>` with your flags and no
   `--body`. It's the parent's next checkpoint, with a suggested headline and
   the facts of the merge filled in.
3. **Write it.** Two sections matter:
   - **From <child>:** what the subthread did over its life and how it ended:
     what it found or produced, and what it left unfinished. The parent's
     readers may never open the child, so this is their account of it.
   - **Status:** the parent's state now. What does the parent know that it
     didn't, what changes about its next steps, and what's newly open or no
     longer needed? Write it against the parent's origin, like any checkpoint.
4. **Merge:** `thread merge <child-id> [flags] --body <file>`. The child is
   archived, the parent's task that became the subthread (if any) is closed, and
   both are committed together.

If the parent has an "Inherited" section in its current checkpoint, the template
lists its items. Carry one forward only while it's still true.
