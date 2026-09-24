# Merging a subthread

Read this before merging a subthread into its parent.

```
thread merge <child> --body <file> [--promote <path> ...] [--tasks <id> ...]
```

Merging is how a finished subthread's result reaches its parent. It closes
the subthread, archives it, and writes a checkpoint on the parent. It only
goes child into parent.

## Before you merge

Both threads need to be checkpointed, with no events since their last
checkpoints. The subthread's final checkpoint is its last word, so say what
it found or produced and anything left unfinished.

If the subthread has unfinished subthreads of its own, the merge refuses. Merge or drop
those first, or pass `--force` to move them up to the parent.

## The merge checkpoint

Merging writes a checkpoint on the parent, and it has its own structure.
`thread merge <child>` without `--body` prints the template, with the
facts about what's moving already filled in. Write it in scratch, then run
`thread merge <child> --body <file>`.

```
Merged <child>: <headline>

## From <child>
<what the subthread did over its life and how it ended>

## Status
<how merging this subthread changes the parent's state>

## Inherited
<optional, as in any checkpoint>
```

**The headline** says what the subthread achieved, in terms that mean
something to the parent. It's the only line before the first heading.

**From <child>** (1,500 characters) tells the subthread's story for the
parent: what it set out to do, what it did, and how it ended. That covers
the whole arc, not just its last step. Read the subthread's view before you
write it. Below your text, the tool adds the facts: the subthread's final
checkpoint, what was promoted, which tasks moved, and what was left behind.

**Status** (3,000 characters) answers one question: how does merging this
subthread change the parent's state? What does the parent now know, what
changes about its next steps, what's newly open, and what's no longer
needed? Reread the parent's origin first, as for any checkpoint.

## What moves to the parent

- **Docs and artifacts** stay in the subthread by default, and the parent's
  index lists them as pointers. `--promote <path>` copies one into the
  parent. Use it for anything the parent will keep using or updating, like a
  script or harness the rest of the work depends on. From then on the
  parent's copy is the live one.
- **Tasks** stay in the subthread by default. `--tasks <id> ...` moves open
  tasks the parent still needs onto its list. `--all-tasks` moves all of
  them.
- **History** stays in the subthread. The parent's log gets one event
  recording the merge. `thread view <parent> --deep` shows the subthreads'
  checkpoint histories alongside the parent's.

If a subthread turned out not to be worth pursuing, you don't have to merge
it. Drop it instead (see lifecycle.md).
