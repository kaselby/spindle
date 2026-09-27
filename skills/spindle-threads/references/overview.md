# Thread overview

## The store

All threads live in a **store**, a folder that is its own git repo. By default
there is one global store at `~/.spindle/`. If `~/.spindle/config.yml` sets
`scope: project`, each project gets its own `<project>/.spindle/` instead; the
first `thread create` in a project starts it.

```
~/.spindle/
  default/                 the default namespace
    threads/               one folder per thread that hasn't ended
      k7q2m9-latency-regression/
      archived/2026-09/    threads that ended, by the month they ended
  research/                another namespace, if you use them
```

A thread's id is the six characters before the first dash (`k7q2m9`). Commands
take the id; the rest of the folder name is the title.

## What you edit and what the tool owns

- **The tool writes:** `log.jsonl`, `checkpoints/`, `tasks.yml`, `index.md`.
  Change these only through `thread` commands.
- **Written once:** `origin.md`. Only `thread revise` (append a dated revision)
  and `thread reanchor` (replace it) change it.
- **You edit directly:** `docs/`, `artifacts/`, `reading-guide.md`, and
  `thread.yml` (title, parent, and any flags you add). Register docs, artifacts
  and the reading guide after you change them, so the change is logged.
- **Yours alone:** `scratch/`. Not tracked by git and not shown anywhere.

## Events and the log

Every action on a thread (a claim, a note, a task change, a registration, a
checkpoint, a state change) is appended to `log.jsonl` as an **event** with an
id, a time, and the session that did it. The log is append-only.

The view page summarizes what happened **since the last checkpoint**, so a new
session sees work that hasn't been written up yet. `thread replay <id>` prints
those events in full, or the whole history with `--all`.

## Checkpoints and git

A checkpoint is a snapshot of where the work stands, written by a session. It is
the main thing a new session reads. Writing one also commits the thread to the
store's git repo. Merges, completions, drops, revisions and reanchors commit
too. Everything else (notes, tasks, claims) is on disk right away and goes into
git with the next commit.

## States

- **active:** being worked on, or could be.
- **inactive:** nothing written for 14 days. Anything written to it (a claim, a
  note) makes it active again. The session-start index lists inactive threads
  separately.
- **merged**, **completed**, **dropped:** the thread has ended. It moves to
  `threads/archived/<month>/` and drops out of the index, but `thread view <id>`
  still opens it. `thread reopen` brings it back.

## Subthreads

A subthread is a thread with a `parent` in its `thread.yml`. It has everything a
thread has. The parent's view lists its subthreads, and the index nests them
under it. When a subthread is done it **merges** into its parent: the parent
gets a merge checkpoint, can take over the child's open tasks, and can copy its
docs and artifacts. Whatever isn't copied stays in the archived child, and the
parent's `index.md` points to it. Top-level threads **complete** instead.

## Claims

A claim says "this session is working here", with an optional intent. It doesn't
lock anything; several sessions can claim the same thread. A claim expires after
4 hours without activity. Release it when you stop.

## Links

`thread link` records that a thread is `related` to another, `blocked-by` it, or
`continues` it. Links show on the view page and gate nothing.

## Where you see all this

- **The session-start index** lists the threads in the store by id and title.
- **`thread view <id>`** is the orientation page: the origin, one line per past
  checkpoint, the latest checkpoint in full, what happened since, subthreads,
  who's working, open tasks, the reading guide, docs and artifacts, and links.
- **`thread doctor`** checks for problems (a stale claim, an unregistered file,
  a dead path in a reading guide), and each finding says what to do.

## The CLI tool

Every command's flags: `thread <command> --help`.