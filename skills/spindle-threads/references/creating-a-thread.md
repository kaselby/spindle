# Creating a thread

## Before you create one

Check `thread list` (or the session-start index) for a thread that already
covers the work. If one does, claim it instead. If the work is part of an
existing thread, it may belong as a subthread (see below).

A thread is worth it when the work will outlast this session, or when someone
else might pick it up. A task you'll finish in a few steps doesn't need one.

## Steps

1. **Print the origin template:** `thread create "<title>" --template`.
2. **Write the origin** into a file anywhere (a temp file is fine). See below.
3. **Create the thread:**
   `thread create "<title>" --origin <file> [--parent <id>] [--ns <name>]`. The
   title is one line, at most 80 characters. The rest goes in the origin.
4. **Add the tasks you already know about** with `thread task add <id> "..."`.
5. **Write a first checkpoint** once you have something to say about where the
   work stands, and before you stop (`references/checkpoints.md`).

## What the tool sets up

`thread create` makes the thread folder and fills in what it can:

- `origin.md`: your origin, with who created it and when.
- `thread.yml`: the title, and the parent if you gave one.
- `log.jsonl`: a `created` event, and a claim for your session. You don't need
  to claim a thread you just created.
- `tasks.yml`: an empty task list.
- `index.md`: the (empty) list of docs and artifacts.
- `checkpoints/`, `docs/`, `artifacts/`, `scratch/`: empty.

There are no checkpoints yet, so the view page says so. Nothing is committed to
git until the first checkpoint.

## Writing the origin

The origin says **why the work exists**. It's written once and not edited, and
every later checkpoint is read against it. A session that finds the thread in
three weeks should be able to tell from the origin alone what the work is for
and whether it's done.

The template has four sections:

- **Context & Motivation** (required): the reason for the work. If someone asked
  for it, quote them in their own words; a paraphrase loses the part you didn't
  understand yet. Say what prompted it now.
- **Scope** (optional): what's in and what's out, when that isn't obvious. Not a
  plan.
- **Constraints** (optional, usually empty): only real, hard constraints, each
  written "X, because Y". Don't invent any.
- **Completion criteria** (optional, usually left out): a hard target, if there
  is one. Common for automated work, rare otherwise.

Keep out of it anything that will change as the work goes: plans, approaches,
first findings, status, next steps. Those go in tasks and checkpoints. An origin
that describes the plan goes stale the day the plan changes.

Scope the length to the brief. If given a large task with detailed context
behind the goals and motivation, then be exhaustive. Add as much structure
within the context and motivation section as you need. For a smaller task or a
short brief, the origin can be short.

Example:
```
## Context & Motivation
Kira: "the p95 on /search doubled after Tuesday's deploy, can you find out
why?" Users on the team dashboard are timing out. Nothing obvious changed
in the search code itself.

## Scope
Finding the cause and fixing it. Not a general latency audit.
```

If the goal itself changes later, don't edit the origin. See
`references/changing-direction.md`.

## Subthreads

There are two ways to start a subthread:

- `thread promote <parent-id> <task-id> "<title>" --origin <file>` when it's
  already a task on the parent. The task stays on the parent's list, marked as
  now a subthread, and closes when the subthread merges.
- `thread create "<title>" --origin <file> --parent <parent-id>` otherwise.

The subthread goes in its parent's namespace. Its origin says why this piece
exists: what the parent needs from it. Don't restate the parent's origin; a
reader can open the parent. When the subthread is done, it merges back into the
parent (`references/completion-and-merging.md`).