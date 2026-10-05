---
name: spindle-threads
description: >
  Tracks ongoing work across sessions with the `thread` CLI, so a session
  with no memory can pick up a piece of work and understand it. Use when
  picking up, creating, checkpointing, splitting, or finishing a thread,
  or when deciding whether new work needs one.
---

# Threads

Threads are a memory feature for tracking ongoing work and offloading it to
disk. The system is designed around rapid, frictionless reorientation, so any
new agent session can immediately reorient on where the work has been left and
pick up right where it left off without expensive orientation or lossy
summarization.

One thread corresponds to one ongoing stream of work. A single task that can be
accomplished in a few simple steps is not a thread. Threads can nest and contain
subthreads. They can merge into parent threads when complete, or flow into new
threads when they undergo fundamental changes.

Concretely, a thread is a folder:

```
k7q2m9-latency-regression/
  origin.md      why the work exists. Written once, never edited.
  checkpoints/   one file per checkpoint; the latest says where the work stands
  log.jsonl      every event (claims, notes, tasks, registrations), written by the tool
  tasks.yml      the task list
  artifacts/     things the work produced and should keep: reports, results, scripts
  decisions/     one file per decision: what was chosen and why
  index.md       generated list of artifacts
  scratch/       your working files; not tracked by git, not shown to anyone
  thread.yml     metadata: title, parent, flags.
  orientation.md optional: where to look and what to read first, for a newcomer
```

The `thread` CLI is used to interact with threads, and contains automated
features for logging and event tracking. Thread files generally shouldn't be
edited directly - use the tool instead. The exceptions are artifacts,
`orientation.md`, and flags in `thread.yml`.

Every action on a thread (a claim, a note, a task, a checkpoint) is recorded as
an **event** with an id, in the thread's log.

For further details on general thread structure, lifecycle, storage, events, and
tools, read `references/overview.md`.

## How to use threads

### When starting work

Check if there is already a thread for what you want to do (from the index at
startup or using `thread list`). If so:

1. **Orient** via `thread view <id>`. This shows a summary of the thread
   structured for fast orientation. Follow whatever pointers you need to get up
   to speed.
2. **Claim** the thread via `thread claim <id> --intent "what you're doing"`.
   This is a nonexclusive claim that tells other agents what you are working on.

If there is no existing thread for what you're doing, and the task is large
enough to be worth tracking, **create a thread.** Read
`references/creating-a-thread.md`.

If you're starting new work that is a subset of an existing thread, create a new
subthread. Read `references/creating-a-thread.md`.

### While working on a thread

As you work, make sure to keep the thread updated.

1. Use `thread task` to record individual tasks that aren't large enough to need
   their own subthread.
2. Use `thread note` to record observations you want to persist that don't need
   to go in a full doc. Notes stay in the log (`thread replay`) but aren't shown
   on the view page.
3. If your work creates artifacts which should be persisted in the thread (such
   as experiment harnesses, research reports, figures, presentations, etc.), use
   `thread register` to register them as artifacts.
4. **Write a checkpoint when you reach a milestone.** Checkpoints are like
   commits. They act as a snapshot of the current state that can be read or
   replayed by future sessions. Read `references/checkpoints.md` for
   instructions on writing checkpoints.

For further details on how to use tasks, when to checkpoint, and what to do when
threads change direction or grow to encompass new work, read
`references/working-with-threads.md`.

### When wrapping up

If a thread is complete, then it either needs to be merged (for subthreads) or
completed (for top-level threads). Read `references/completion-and-merging.md`.

Note that completing a thread doesn't require every single task to be complete,
just that the overall goals and motivation for the thread have been met.

If you are wrapping up your session but the thread is not yet complete, then:

1. In most situations, you should write a checkpoint before you wrap up.
2. Release your claim with `thread release <id>`. If you haven't checkpointed,
   the tool will ask for a checkpoint; `--skip "<reason>"` releases without it,
   and the next session sees the reason.

## Artifacts & orientation

While working you may create artifacts: scripts, research reports, figures,
experiment harnesses, and so on. Throwaways go in `scratch/`. Anything another
session might need to use or consult goes in `<thread>/artifacts/` and is
registered with `thread register <id> artifacts/<file> --purpose "..."`. Add
`--read-when "..."` if it matters when to open it.

If a new session would need more than the view page to get oriented, such as
where the code lives, what to read first, or resources outside the thread,
write `<thread>/orientation.md`. The view page shows it in full. Keep it to
orientation and leave status and next steps to the checkpoint; it's capped
at 1,500 characters.

## Decisions

Use `thread decide` to record choices later work depends on, with the reason,
so a later session can judge whether they still hold.

- **Working** is the default: the current best judgement, open to revision.
- **Settled** (`--settled`) only if the user addressed it directly.
- **To change one**, record the new decision with `--supersedes DNNN`; the old
  one stays on file.
- **At merge**, a subthread's live decisions become its parent's.

`thread decisions <id>` lists them.

## Other sessions

Several sessions can claim and work on the same thread at once. Claims indicate
presence and intent; they're not a lock. When working at the same time as other
agents, be careful to avoid concurrent edits.

For checkpoints there are additional mechanisms, covered in
`references/checkpoints.md`.

## Thread storage and namespaces

Threads are stored either globally in `~/.spindle/` (the default) or per
project. This is configured in `~/.spindle/config.yml`.

Threads can optionally be grouped into namespaces for organization with
`thread create --ns <name>`. `thread list` shows all namespaces grouped;
`--ns <name>` filters to one.

Default to not using namespaces unless the user requests it or there is an
established convention in place.

## Commands

| Command | What it does |
|---|---|
| `thread list [--ns <name>] [--flag key[=value]]` | active and inactive threads |
| `thread view <id> [--deep]` | the view page. `--deep` includes subthreads' histories |
| `thread claim` / `release <id>` | start / stop working on a thread |
| `thread note <id> "text"` | record a finding (not shown on the view page) |
| `thread task add\|close\|remove\|list <id> ...` | the task list |
| `thread register <id> artifacts/<path> --purpose "..." [--read-when "..."]` | keep an artifact, a file or a directory. Max 5 MB |
| `thread decide <id> "title" <file> [--settled] [--supersedes DNNN]` | record a decision. No file prints the template |
| `thread decisions [<id>] [DNNN] [--all]` | list live decisions, or show one |
| `thread checkpoint <id> [body.md] [--at <event-id>]` | write a checkpoint. No body prints the template |
| `thread create "title" --origin o.md [--parent <id>] [--ns <name>]` | new thread. No `--origin` prints the template |
| `thread promote <id> <task-id> "title" --origin o.md` | task to subthread |
| `thread merge` / `complete` | finish a thread: `references/completion-and-merging.md` |
| `thread revise` / `drop` / `reopen` | change direction: `references/changing-direction.md` |
| `thread link` / `unlink <id> <kind> <target>` | `related`, `blocked-by`, or `continues`. Display only |
| `thread replay <id>` | read the log. `--checkpoint cNNNN` or `--checkpoints` shows past checkpoints in full |
| `thread doctor [<id>]` | check for problems; each finding says what to do |

Flags: `thread <command> --help`.

## Thread guidelines

1. **Write for a fresh session.** The goal of threads is rapid reorientation.
   Write accordingly.
2. **Update as you go.** Keep the thread up to date as you work, don't just wait
   for the end.
3. **Threads are internal, not user-facing.** The user should be able to read
   them if needed, but they are not responsible for curating your threads, and
   shouldn't be asked for approval about thread changes.

If the curated guides aren't enough and you want full documentation on the
thread system, `references/system/mechanics.md` covers the exact formats and
rules, and `references/system/design.md` explains why it's built this way.