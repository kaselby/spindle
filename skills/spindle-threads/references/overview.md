# Thread overview

## What a thread is

A session's memory ends with the session. A thread keeps one stream of work on
disk so the next session can pick it up: why the work exists, where it stands,
what has happened, and what it has produced. Everything in a thread is arranged
around one goal: a session that has never seen the work should be able to get
oriented quickly, without reading everything and without anyone explaining it.

## The parts of a thread

A thread is a folder, and each part answers one question a newcomer has.

**Why does this work exist?** `origin.md` holds the motivation, and the scope
and constraints if there are any. It's written when the thread is created and
never edited in place, because everything else is measured against it. If the
understanding shifts, `thread revise` appends a dated revision; if the work
becomes something else, `thread reanchor` replaces it and keeps the old one.

**Where does it stand?** `checkpoints/` holds one file per checkpoint, each a
snapshot a session wrote: a headline, an outline, and a status measured against
the origin. The latest is the thread's current state; the older ones read as its
history. `tasks.yml` is the list of open work.

**What has happened?** `log.jsonl` records every action as an **event**, with an
id, a time and the session that did it: claims, notes, task changes,
registrations, checkpoints, state changes. It's append-only. Notes live only
here. The events since the last checkpoint are the work nobody has written up
yet.

**What has it produced, and what should I read?** `artifacts/` holds outputs
worth keeping, and `docs/` holds guides for future sessions. Each is registered
with a one-line purpose, and docs also say when to read them. `index.md` is the
generated list of both. `reading-guide.md`, if there is one, says where to look
and in what order, including places outside the thread.

**What is this thread?** `thread.yml` holds the title, the parent if it's a
subthread, and any flags you add.

`scratch/` is the working session's own space: not tracked, not shown.

The tool writes the log, checkpoints, tasks and index; change those only with
`thread` commands. You edit docs, artifacts, the reading guide and `thread.yml`
directly, then register docs, artifacts and the reading guide so the change is
logged.

## Reading a thread

`thread view <id>` puts the parts together in the order a newcomer needs them:
the origin, one line per past checkpoint, the latest checkpoint in full, what
has happened since, subthreads, who's working, open tasks, the reading guide,
docs and artifacts, and links. It's the page to read before doing anything on a
thread. `thread replay` shows the log itself.

The session-start index is the level above: every thread in the store by id and
title, with subthreads nested under their parents.

## How threads relate

A **subthread** is a thread with a parent. It has everything a thread has, and
takes on a stream of work that serves the parent's goal but needs its own
history. When it's done it **merges**: the parent gets a checkpoint describing
what the subthread brought, and can take over its open tasks and copy its docs
and artifacts. Whatever isn't copied stays with the subthread, and the parent's
index points to it.

A **link** records that a thread is `related` to another, `blocked-by` it, or
`continues` it. Links are shown on the view page and don't restrict anything.

## A thread's life

A thread starts **active**. A session working on it **claims** it, with an
intent saying what it's doing, and releases it when it stops. Claims don't lock
anything; several sessions can hold one at once, and a claim expires after 4
hours without activity.

A thread with nothing written to it for 14 days becomes **inactive**. The
session-start index lists those separately, and anything written to the thread
makes it active again.

A thread ends in one of three ways: a subthread is **merged** into its parent, a
top-level thread is **completed**, or either is **dropped** when it's no longer
worth doing. An ended thread moves to the archive and drops out of the index,
but `thread view <id>` still opens it, and `thread reopen` brings it back.

## Where threads live

Threads live in a **store**, a folder that is its own git repo. By default it's
one global store at `~/.spindle/`; setting `scope: project` in
`~/.spindle/config.yml` gives each project its own `<project>/.spindle/`
instead.

```
~/.spindle/
  default/                 the default namespace
    threads/
      k7q2m9-latency-regression/
      archived/2026-09/    threads that ended, by the month they ended
  research/                another namespace, if you use them
```

A thread's id is the six characters before the first dash (`k7q2m9`), and
commands take the id. **Namespaces** are optional folders that group threads; a
subthread always lives in its parent's.

Checkpoints, merges, completions, drops, revisions and reanchors each commit to
git. Everything else is on disk at once and goes into the next commit.

Every command's flags: `thread <command> --help`.
