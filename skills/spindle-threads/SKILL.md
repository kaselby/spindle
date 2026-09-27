---
name: spindle-threads
description: >
  Tracks ongoing work across sessions with the `thread` CLI, so a session
  with no memory can pick up a piece of work and understand it. Use when
  picking up, creating, checkpointing, splitting, or finishing a thread,
  or when deciding whether new work needs one.
---

# Threads

Threads are a memory feature designed around tracking ongoing work and offloading it to disk. The system is designed around rapid, frictionless reorientation, so any new agent session can immediately reorient on where the work has been left and pick up right where it left off without expensive orientation or lossy summarization.

One thread corresponds to one ongoing stream of work. A single task that can be accomplished in a few simple steps is not a thread. Threads can nest and contain subthreads. They can merge into parent threads when complete, or flow into new threads when they undergo fundamental changes.

Threads live in a store, its own git repo: `~/.spindle/`, or
`<project>/.spindle/` if setup chose per-project stores (the session-start
snapshot names the store it shows). In a project with no store yet, the first
`thread create` starts one.

```
~/.spindle/
  default/                 the default namespace; other namespaces sit beside it
    threads/               one folder per active thread
      archived/YYYY-MM/    threads that have ended, by the month they ended
```

Concretely, a thread is a folder under `<store>/<namespace>/threads/`:

```
k7q2m9-latency-regression/
  origin.md      why the work exists. Written once, never edited.
  checkpoints/   one file per checkpoint; the latest says where the work stands
  log.jsonl      every event (claims, notes, tasks, registrations), written by the tool
  tasks.yml      the task list
  docs/          guides for future sessions, registered with a note on when to read them
  artifacts/     things the work produced and should keep: reports, results, scripts
  index.md       generated list of docs and artifacts
  scratch/       your working files; not tracked by git, not shown to anyone
  thread.yml     metadata: title, parent, flags.
  reading-guide.md  optional: where to look and in what order, for a newcomer
```

The `thread` cli is used to interact with threads, and contains automated
features for logging and event tracking. Thread files generally shouldn't be
edited directly - use the tool instead. The exceptions are docs/artifacts and
the reading-guide (if applicable), and if you need to add flags to `thread.yml`.

Every action on a thread (a claim, a note, a task, a checkpoint) is recorded
as an **event** with an id, in the thread's log.

## Picking up a thread

1. **Read it:** `thread view <id>`. The page shows the origin, one line per
   past checkpoint, the latest checkpoint, recent activity, subthreads, who's
   working, open tasks, the reading guide if there is one, and the docs worth
   reading. Read the origin first, because everything else is measured
   against it.
2. **Claim it:** `thread claim <id> --intent "what you're doing"`. This tells
   other sessions you're here. It doesn't lock anything, and it lasts until
   you release it or go 4 hours without activity. `thread create` claims
   the new thread for you.
3. **Work**, recording things as you go (see below).
4. **Checkpoint** when the state of the work changes in a way the next
   session would need to know, and before you stop. See below.
5. **Release:** `thread release <id>`. If you've recorded more than three
   events since your last checkpoint, it asks for a checkpoint first. You
   can pass `--skip "reason"` instead, and the reason is shown to the next
   session.

## Checkpoints

A checkpoint captures the current state of the thread. It acts like a commit, capturing the changes that have been made to the thread, as well as documenting where the work currently sits, what's next on the horizon, and anything a future session needs to know to continue from here.

Checkpoints should be rewritten whenever any major changes happen to the thread - changes in thread state, merging children, pivots or origin changes, major milestones completed. The `thread` tool will suggest creating a new checkpoint periodically if it has been awhile since the last checkpoint - this isn't mandatory, it's just a gentle reminder. Don't write one after every small task is completed.

`thread checkpoint <id>` with no body prints the template. Write the body
to a file and run `thread checkpoint <id> body.md`. **Read
[checkpointing](references/checkpointing.md) before your
first checkpoint in a session.**

Write the body in scratch, it's copied into checkpoints by the tool.


## Starting new work

Before creating anything, check `thread list`. The work may already have a
home.

- **You'll finish it now and nobody needs to pick it up later:** nothing, or
  a task on the thread it belongs to.
- **It's a single stateless step inside an existing thread:** a task.
- **It's part of an existing thread but needs its own reasoning, or might be
  handed off:** a subthread. Use `thread promote <parent> <task-id> "title"`
  if it started as a task, or `thread create "title" --parent <id>`.
- **It's new and stands on its own:** `thread create "title"`.

To decide between a task and a thread, ask whether someone picking this up
later would need to know why it exists and what's been tried. If they would,
it's a thread.

For details on thread creation or promotion, read `references/thread-creation.md`.

## Thread lifecycle

A thread is **active** while it's being worked on. After 14 days with no
activity it becomes **inactive**, and any new activity makes it active again.

Every thread ends in one of three ways, and each one moves the thread to the
archive:

- **Merged:** a finished subthread, folded into its parent with
  `thread merge`. This is how its result reaches the parent.
- **Completed:** a finished thread with no parent, ended with
  `thread complete`.
- **Dropped:** decided it isn't worth pursuing, ended with `thread drop`.
  This works for any thread, subthreads included.

If new information arises that causes a thread's origin to no longer be accurate, the thread should either be **revised** or **reanchored**. If the overall context and motivation for the work remains largely accurate, use `thread revise` to append a dated revision. If the whole context for the thread shifts but the work carries on, **reanchor** it: `thread reanchor` replaces the origin, writes a checkpoint against the new one, and keeps the tasks, subthreads, and history. If the original question was wrong and the work shouldn't carry on, drop the thread and start a new one.

Threads can be linked to each other with `thread link`: `related`, `blocked-by`, or `continues` (a new thread carrying on an ended one). Links show on the view page. They never block anything.

Read [lifecycle](references/lifecycle.md) before completing, dropping,
revising, reanchoring, or reopening a thread, and
[merging](references/merging.md) before merging one.

## Recording as you work

Apart from checkpoints, there are six places to put things while you work.
They differ in who will see them.

- **Notes:** `thread note <id> "..."`. Gotchas, small findings, dead ends,
  observations. Record anything you think might be useful, but doesn't
  belong in a checkpoint or doc. Notes are kept in the log and are not
  shown on the view page. Anyone who needs them can search with
  `thread replay <id> --type note`. 
- **Tasks:** `thread task add <id> "..."`, then `thread task close <id>
  <task-id>`. Small, concrete next steps. A task is one line with no history.
  If one grows its own reasoning, turn it into a subthread with
  `thread promote`.
- **Docs:** files in `docs/`, registered with `thread register <id>
  docs/x.md --kind doc --purpose "..." --read-when "..."`. Guides written for
  future sessions: how to run the experiments, where the code lives and how it's structured, a reading guide to the research reports, etc... Every doc is listed on the view page with when to read it, so
  this is how you make sure something gets seen.
- **Artifacts:** files in `artifacts/`, registered with `thread register <id>
  artifacts/x --kind artifact --purpose "..."`. Records of what the work
  produced: results, reports, scripts, diagrams. They're listed on the view
  page with their purpose. A directory of related files can be registered
  as one entry.
- **Reading guide:** `reading-guide.md` at the thread root. Optional
  orientation guide pointing to what files to read first or linking to
  resources outside the thread. Not a status document, shouldn't reference
  next steps or ongoing work. Just pointers on where to find information.
  Keep it under 1,500 characters; doctor flags a longer one and any local
  path in it that no longer exists.
- **Scratch:** `scratch/`. Anything in progress. It isn't tracked or shown to
  anyone.

The difference between docs and artifacts is that docs are specifically
written as guidelines or reference material for future sessions. Both are
registered with `thread register` - `index.md` has a list of all registered
docs and artifacts.

## Other sessions

Several sessions can claim and work on the same thread at once. Claims indicate presence and intent, they're not a lock. When working at the same time as other agents, be careful to avoid concurrent edits. 

For checkpoints, there's a safeguard in place to ensure that checkpoints don't happen without being aware of work other sessions have done, since checkpoints must capture the full state of the thread. When writing a checkpoint, pass the event id of the latest event you are aware of. If it is stale, the checkpoint will fail. Make sure to replay the log to understand what other sessions have contributed before writing your checkpoint.

## Namespaces

Threads can optionally be grouped into namespaces, for example one per
agent. Use `thread create --ns <name>`, or set `SPINDLE_NAMESPACE`.
Subthreads can only be created in their parent's namespace. `thread list`
shows all namespaces grouped. `--ns <name>` filters to one.

Default to not using namespaces unless the user requests it or there is an established convention in place.

## Commands

| Command | What it does |
|---|---|
| `thread list [--ns <name>]` | active and inactive threads |
| `thread view <id> [--deep]` | the orientation page. `--deep` includes subthreads' histories |
| `thread claim` / `release <id>` | start / stop working on a thread |
| `thread note <id> "text"` | record a finding (not shown on the view page) |
| `thread task add\|close\|remove\|list <id> ...` | the task list |
| `thread register <id> <path> --kind doc\|artifact --purpose "..."` | keep a doc (under docs/, needs `--read-when`) or artifact (under artifacts/), a file or a directory. Max 5 MB |
| `thread reading-guide <id>` | the reading guide's template, or its size against the cap |
| `thread checkpoint <id> [body.md] [--at <event-id>]` | write a checkpoint. No body prints the template |
| `thread create "title" --origin o.md [--parent <id>] [--ns <name>]` | new thread. No `--origin` prints the template |
| `thread promote <id> <task-id> "title" --origin o.md` | task to subthread |
| `thread revise` / `reanchor` / `merge` / `complete` / `drop` / `reopen` | see above |
| `thread link` / `unlink <id> <kind> <target>` | `related`, `blocked-by`, or `continues`. Display only |
| `thread replay <id>` | read the log. `--checkpoint cNNNN` or `--checkpoints` shows past checkpoints in full |
| `thread doctor [<id>]` | check for problems; each finding says what to do |

Flags: `thread <command> --help`. Background on how the system works and
why: [system/design](references/system/design.md) and
[system/mechanics](references/system/mechanics.md).

## Guidelines

1. **Write for a fresh session.** Threads exist so that a future session can
   continue your work exactly as if it were you continuing it, with none of
   your memory. Write origins, checkpoints, docs, and artifacts for that
   reader: someone who knows only what's on the page.

2. **Update as you go.** Keep the thread current while you work, not at the
   end. A session can end at any point, and whatever wasn't recorded ends
   with it.

3. **Grow docs as the thread grows.** When a workflow or a piece of setup
   keeps mattering, write it up as a doc: an orientation guide or a manual.
   Docs are shown on the view page with a note on when to read them
   (progressive disclosure), so they give the next session detail without
   making it read everything up front.

4. **The threads are yours to run.** Threads are an internal tool for you to
   track your work. A user should be able to read them, but shouldn't need
   to understand Spindle's structure or curate your threads. Decide the
   structure yourself: when to start a thread or a subthread, revise or
   reanchor an origin, merge, or drop. Don't ask the user to approve it.
