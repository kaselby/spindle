# How threads work underneath

Reference material, for when you need to know what the tool actually does: where
things live, what gets committed, what gets checked. For what to do in the
moment, see SKILL.md and the other reference docs.

## Where things live

```
~/.spindle/                          the store (global scope; <project>/.spindle/ in project scope); its own git repo
  .gitignore                         ignores every thread's scratch/
  .gitattributes                     log.jsonl merges by union, so logs from two machines combine
  default/                           the default namespace (threads created without --ns)
    threads/<id>-<slug>/             active and inactive threads
    threads/archived/YYYY-MM/<id>-<slug>/   merged, completed, and dropped threads,
                                     by the month they ended
  <ns>/                              any other namespace, same shape as default/
```

The tool refuses a store that isn't its own git repository, because every change
is a commit; without its own `.git` nothing would be recorded.

Subthreads aren't nested on disk. A subthread sits beside its parent in the same
namespace's threads/ folder (a subthread always lives in its parent's
namespace), and the parent link is the `parent:` line in the subthread's
thread.yml. That's why reparenting or merging never moves folders around. A
parent's list of subthreads is found by scanning the store (archived threads
included) for threads that name it. There is one level of namespace, and ids are
unique across the whole root, so any command finds a thread by id no matter
which namespace it's in. The folder is the namespace; nothing else records it.
Don't move thread folders by hand.

A thread id is six characters (e.g. `k7q2m9`). Commands accept the id; the slug
in the folder name is only there so people can read it.

### Which store

`--root`, else `SPINDLE_ROOT`, else the scope in `~/.spindle/config.yml`
(`thread setup --scope` writes it; no file means global). Global: `~/.spindle`.
Project: `<project>/.spindle`. The project is the git repository the launch
folder is in (its main checkout, so worktrees share one store), or the launch
folder itself outside git. The launch folder is `SPINDLE_PROJECT` (the Claude
Code hook and the pi extension set it at session start) or else the current
directory. The first `thread create` in a project
starts its store and adds `**/.spindle/` to the user's global git ignore, never
the project's own `.gitignore`.

Your identity comes from `THREAD_SESSION` and `THREAD_AGENT` (optional), or from
`--by session/agent` on any command. Without `THREAD_SESSION` the tool falls
back to user@host, which can't tell two sessions apart, so set it.

## What lives where

| What | Where | Who writes it |
|---|---|---|
| Metadata: title, parent, `flags:` (and `supersedes`, old threads only) | `thread.yml` | people and agents, by hand; the tool on create, reanchor (title) and reparent (parent) |
| What happened: claims, notes, checkpoints, tasks, registrations, links, merges | `log.jsonl` | the tool, append-only |
| Current state: state, claims, counts, last checkpoint, subthreads, links | nowhere; computed on read | never stored |
| Why the work exists | `origin.md` | narrative only; its frontmatter says only whose it is and when it was written |
| Namespace | the folder | set at create (`--ns`) |

design.md says why the split is drawn here. Older stores kept thread.yml as a
cache the tool rebuilt from the log, with the title and parent in origin.md's
frontmatter. This version refuses a store written that way; convert it with
`thread migrate` from an older Spindle (commit 5de08e0 has it).

## Files in a thread

| File | Written by | Notes |
|---|---|---|
| `origin.md` | you, at creation | Never rewritten. Revisions are appended under `## Revisions`. `reanchor` replaces it whole, moves the old one to `origin-N.md`, and writes a checkpoint in the same commit. |
| `thread.yml` | you, and the tool | The metadata. Edit it directly; see below. |
| `log.jsonl` | the tool | Append-only. Everything that happens to a thread is an event here. Hand edits to thread.yml aren't. |
| `checkpoints/cNNNN.md` | you, plus the tool | Your outline, Status, and Inherited, then an `## Event log` section the tool adds. The frontmatter records thread.yml as it stood (`metadata:`). |
| `tasks.yml` | you, and the tool | Edit it directly if you like: the tool diffs the board against the task events on every command and records what changed. |
| `reading-guide.md` | you, optional | Where to look and in what order. See below. |
| `index.md` | the tool | Generated from registrations. Never edit it. |
| `docs/`, `artifacts/` | you | Only files registered with `thread register` appear in the index. |
| `scratch/` | you | Not in git. Not shown anywhere. |

### thread.yml

```yaml
title: One line, at most 80 characters        # required
parent: k7q2m9                                # subthreads only
from-task: t9k2a                              # set by `thread promote`
flags:                                        # optional: your own keys, one value each
  kiln.autonomous: true
```

It is checked every time it's read. A key the tool doesn't know is an error that
names it and guesses what you meant (`tittle` → `title`); your own keys go under
`flags:`. Flag values are single values (text, number, true/false), not lists or
mappings. Prefix flag names with your tool's name (`kiln.autonomous`); nothing
enforces it. `supersedes` is kept for old threads only; don't add it to new
ones.

A thread.yml that doesn't validate stops commands on that one thread, with how
to fix it: the `git -C … checkout -- …` command that restores the last committed
version, or the expected shape if nothing is committed yet. Commands that read
the whole store (`list`, the startup snapshot, the subthread and link scans)
skip the thread, count it, and point at doctor. The exception is the subthread
gate in `complete`, `drop` and `merge`: if a thread that could be a subthread
can't be read, they refuse and name it, `--force` included, because not knowing
isn't the same as having none. "Could be" means it's in the same namespace and
its thread.yml or log mentions the id (or its thread.yml can't be read at all).
`merge` also reads the parent's thread.yml and tasks before its first write, so
a bad file refuses the merge instead of half-applying it.

`parent:` can't be the thread's own id; that fails validation like any other bad
value. A `parent:` that names no thread, a thread in another namespace, or a
chain of parents that loops back isn't a read error: the thread reads as
top-level, doctor flags it (dangling-parent, cross-namespace-parent,
parent-cycle), and merge, drop, complete and reopen refuse until it's fixed.
`thread create --parent` puts the subthread in the parent's namespace (over
`SPINDLE_NAMESPACE`), and it and `promote` refuse an `--ns` that differs.
`thread list` and the startup snapshot show a cross-namespace thread at the top
of its own namespace, marked "subthread of X", which is display only.

The tool changes one line when it writes (the title on reanchor, the parent when
merge or drop `--force` moves a subthread up), so comments and flag order
survive. Hand edits aren't events. The view page shows them as a line under the
banner, "thread.yml since the last checkpoint: title, parent changed; 2 flags
changed", diffed against the `metadata:` block of the latest checkpoint (before
the first checkpoint, the `created` event; for a migrated thread, the `migrated`
event). Built-in fields are named and flags are counted. The line is not
activity: it doesn't add to the event count and doesn't wake an inactive thread.
The view lists the flags on one line under the title.

### reading-guide.md

Optional, hand-written, at the thread root: where to look and in what order, for
someone new to the thread. It points at anything, inside or outside the thread:
this thread's docs/ and artifacts/, repo paths, branches, PRs, URLs, another
thread's `<id>:docs/<file>`. It never holds status, next steps or handoff notes;
those go in the checkpoint.

`thread view` shows it in full, in its own section before the docs list; with
none, the view says nothing. After writing or changing it, register it with
`thread register <id> reading-guide.md --kind reading-guide [--purpose "what changed"]`:
that logs a `register` event (replay shows "reading guide updated") and reports
its size against the cap. It is not in index.md, and doctor flags a guide that
was never registered. At merge it is carried like a doc: promoted if the parent
has none, otherwise left with the child. The cap is 1,500 characters, not
counting HTML comments; the view still shows a guide over it, and doctor flags
it loudly, since a guide that keeps growing is usually status creeping in.
Doctor also checks that every local path in it exists: tokens starting with `/`,
`~/`, `./`, `../`, `docs/`, `artifacts/`, or `<id>:docs/`, `<id>:artifacts/`.
URLs and branch names aren't checked.

### Registering

`thread register <id> <path> --kind doc|artifact --purpose "..."` (docs also
need `--read-when`). The kind must match the folder: `doc` for a path under
docs/, `artifact` under artifacts/. Older registrations carry one of twelve
older kinds (guide, report, dataset, ...); they still read, filed by their
folder, and the kind is no longer shown. The third kind, `reading-guide`, is
described above. Registering a path again replaces its entry: the view and
index.md show only the newest registration.

At merge, whatever isn't promoted becomes a pointer on the parent
(`<child>:<path>@<checkpoint>`). index.md lists pointers in full; the view page
shows only a count of them, with a line pointing to index.md.

## Events

Every event has an id, a timestamp, who did it, a type, and a payload. Types
include: `created`, `claim`, `release`, `note`, task changes, `register`,
`checkpoint`, `origin-revised`, `origin-replaced`, `linked`, `unlinked`,
`state-changed`, `merged-into`, `reopened`, `reparented`, `migrated`, and the
parent-side `child-created`, `child-merged`, `child-dropped`, `child-reopened`,
and `child-adopted`. The `child-*` events and `reparented` are history (the
view's arc and counts use them); the subthreads list comes from the children's
thread.yml. `migrated` was written once per thread by the old `thread migrate`,
with the metadata it wrote; the tool still reads it but no longer writes it. Older logs may also contain the old names `child-closed` and
the states `open` and `closed`. The tool still reads them (`open` as active,
`closed` as completed, or merged if it came from a merge, and `child-closed` as
the child completing) but never writes them. `thread replay` reads them.

"Events since the last checkpoint" counts every event after the latest
checkpoint, notes included. Events that only record a state change (like a merge
or reopen) and the `migrated` event don't count as work.

## Git

A store is one repository for all its threads, so a merge that touches two
threads is one commit. Commits happen at checkpoints and at lifecycle commands
(merge, complete, drop, reopen, revise, reanchor, archive), not on every event.
So each commit corresponds to a meaningful moment. A commit contains only the
threads its command touched; events on other threads stay uncommitted until
their own next commit. Work across machines syncs with ordinary push and pull.

## Checkpoints and conflicts

A checkpoint is refused if:

- the outline (text before the first heading) is empty or over 600 characters,
  or its first line is over 120;
- `## Status` is missing, empty, or over 3,000 characters;
- `## Inherited` has more than 3 items, an item over 160 characters, or an item
  not ending in `(from cNNNN)`;
- the body includes `## Event log`, which the tool writes itself;
- another session has written since the last checkpoint and `--at` is missing,
  or `--at` isn't the latest event.

The last rule is the only concurrency control. When only your own session has
written since the last checkpoint, `--at` is optional, because a session can't
conflict with itself.

## States

- **active:** being worked on, or available to be.
- **inactive:** no activity for 14 days. The doctor sets this, and any new
  activity makes the thread active again automatically.
- **merged:** a finished subthread whose result went into its parent.
- **completed:** a finished thread with no parent.
- **dropped:** stopped because it wasn't worth pursuing. Dropping a subthread
  records `child-dropped` on the parent. The last three are endings, and each
  moves the thread to the archive by the month it ended. `reopen` brings a
  completed, dropped or merged thread back to active. completion-and-merging.md
  and changing-direction.md cover when to use which.

`complete`, `drop`, `merge` (on both sides), `revise`, and `reanchor` require a
thread with no events since its last checkpoint.

## Maintenance

Nothing runs in the background. Instead, some quick checks run every time the
tool touches a thread:

- **Claims expire** after 4 hours without activity from that session. The next
  command releases them on the dead session's behalf and records how many events
  it left without a checkpoint, so the next live session knows to write one from
  the log.
- **Hand-edited tasks** are noticed and recorded (the board is diffed against
  the task events every time).
- **Many events since the last checkpoint** (more than 8) gets flagged.

`thread doctor` runs everything. It also moves threads with no activity for 14
days to inactive, and flags:

- scratch files newer than the last checkpoint, and scratch files older than 30
  days;
- files in docs/ or artifacts/ that were never registered;
- promoted tasks whose subthread is missing;
- pointers to files that no longer exist, and links to threads that no longer
  exist;
- a thread.yml that doesn't validate, and a `parent:` that names no thread;
- a reading guide over the cap, and local paths in it that don't exist;
- ended threads not yet in `threads/archived/`. `thread archive` moves them.

## Limits

All in `src/spindle/limits.py`:

| Limit | Value |
|---|---|
| headline | 120 characters |
| outline | 600 characters |
| Status | 3,000 characters |
| Inherited | 3 items, 160 characters each |
| recent events shown on the view page | 5 |
| checkpoint suggested after | 8 events |
| release requires a checkpoint after | 3 of your own events |
| claim expires after | 4 hours |
| inactive after | 14 days |
| inactive threads listed in the startup snapshot | 10 most recently active (every active thread is always listed) |
| artifacts shown on the view page | 25 most recent |
| largest registrable file | 5 MB |
| reading guide | 1,500 characters (doctor flags it; the view still shows it) |
| old scratch | 30 days |
