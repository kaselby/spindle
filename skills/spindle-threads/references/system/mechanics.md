# How threads work underneath

Reference material, for when you need to know what the tool actually does:
where things live, what gets committed, what gets checked. For what to do in
the moment, see SKILL.md and the other reference docs.

## Where things live

```
~/.spindle/                          the one store; its own git repo
  .gitignore                         ignores every thread's scratch/
  .gitattributes                     log.jsonl merges by union, so logs from two machines combine
  default/                           the default namespace (threads created without --ns)
    threads/<id>-<slug>/             active and inactive threads
    threads/archived/YYYY-MM/<id>-<slug>/   merged, completed, and dropped threads,
                                     by the month they ended
  <ns>/                              any other namespace, same shape as default/
```

The tool refuses a store that isn't its own git repository, because every
change is a commit; without its own `.git` nothing would be recorded.

Subthreads aren't nested on disk. A subthread sits beside its parent (in
its own namespace's threads/ folder), and the parent link is recorded in
the thread's own data. That's why reparenting or merging never moves folders
around. There is one level of namespace, and ids are unique across the whole
root, so any command finds a thread by id no matter which namespace it's in.
A thread's namespace is also recorded in its origin's frontmatter, and the
two must agree. Don't move thread folders by hand.

A thread id is six characters (e.g. `k7q2m9`). Commands accept the id; the
slug in the folder name is only there so people can read it.

The store is `--root` if given, else `SPINDLE_ROOT`, else `~/.spindle`. It
never depends on the directory you run the command from. Your identity comes
from `THREAD_SESSION` and `THREAD_AGENT` (optional), or from `--by
session/agent` on any command. Without `THREAD_SESSION` the tool falls back
to user@host, which can't tell two sessions apart, so set it.

## Files in a thread

| File | Written by | Notes |
|---|---|---|
| `origin.md` | you, at creation | Never rewritten. Revisions are appended under `## Revisions`. `reanchor` replaces it whole, moves the old one to `origin-N.md`, and writes a checkpoint in the same commit. Frontmatter holds the thread's metadata. |
| `log.jsonl` | the tool | Append-only. Every change to a thread is an event here first. |
| `checkpoints/cNNNN.md` | you, plus the tool | Your outline, Status, and Inherited, then an `## Event log` section the tool adds. |
| `thread.yml` | the tool | A summary computed from the log (state, claims, latest checkpoint, counts). It can always be rebuilt. |
| `tasks.yml` | the tool | Hand edits are noticed and recorded as events the next time the tool runs. |
| `index.md` | the tool | Generated from registrations. Never edit it. |
| `docs/`, `artifacts/` | you | Only files registered with `thread register` appear in the index. |
| `scratch/` | you | Not in git. Not shown anywhere. |

## Events

Every change is an event with an id, a timestamp, who did it, a type, and a
payload. Types include: `created`, `claim`, `release`, `note`, task
changes, `register`, `checkpoint`, `origin-revised`, `origin-replaced`, `linked`, `unlinked`, `state-changed`,
`merged-into`, `reopened`, and the parent-side `child-created`,
`child-merged`, `child-dropped`, `child-reopened`, and
`child-adopted`. Older logs may also contain the old names
`child-closed` and the states `open` and `closed`. The tool still reads
them (`open` as active, `closed` as completed, or merged if it came from a
merge, and `child-closed` as the child completing) but never writes them.
`thread replay` reads them.

"Events since the last checkpoint" counts every event after the latest
checkpoint, notes included. Events that only record a state change (like a
merge or reopen) don't count as work.

## Git

`.spindle/` is one repository for all threads, so a merge that touches two
threads is one commit. Commits happen at checkpoints and at lifecycle
commands (merge, complete, drop, reopen, revise, reanchor, archive), not on every
event. So each commit corresponds to a meaningful moment. A commit contains
only the threads its command touched; events on other threads stay
uncommitted until their own next commit. Work across machines syncs with ordinary push and pull.

## Checkpoints and conflicts

A checkpoint is refused if:

- the outline (text before the first heading) is empty or over 600
  characters, or its first line is over 120;
- `## Status` is missing, empty, or over 3,000 characters;
- `## Inherited` has more than 3 items, an item over 160 characters, or an
  item not ending in `(from cNNNN)`;
- the body includes `## Event log`, which the tool writes itself;
- another session has written since the last checkpoint and `--at` is
  missing, or `--at` isn't the latest event.

The last rule is the only concurrency control. When only your own session
has written since the last checkpoint, `--at` is optional, because a session
can't conflict with itself.

## States

- **active:** being worked on, or available to be.
- **inactive:** no activity for 14 days. The doctor sets this, and any
  new activity makes the thread active again automatically.
- **merged:** a finished subthread whose result went into its parent.
- **completed:** a finished thread with no parent.
- **dropped:** stopped because it wasn't worth pursuing. Dropping a
  subthread records `child-dropped` on the parent.
The last three are endings, and each moves the thread to the archive by the
month it ended. `reopen` brings a completed or dropped thread back to
active. lifecycle.md covers when to use which.

`complete`, `drop`, `merge` (on both sides), `revise`, and `reanchor`
require a thread with no events since its last checkpoint.

## Maintenance

Nothing runs in the background. Instead, some quick checks run every time
the tool touches a thread:

- **Claims expire** after 4 hours without activity from that session. The
  next command releases them on the dead session's behalf and records how
  many events it left without a checkpoint, so the next live session knows
  to write one from the log.
- **Hand-edited tasks** are noticed and recorded.
- **Many events since the last checkpoint** (more than 8) gets flagged.

`thread doctor` runs everything. It also moves threads with no activity
for 14 days to inactive, and flags:

- scratch files newer than the last checkpoint, and scratch files older
  than 30 days;
- files in docs/ or artifacts/ that were never registered;
- promoted tasks whose subthread is missing;
- pointers to files that no longer exist;
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
| artifacts shown on the view page | 8 most recent |
| largest registrable file | 5 MB |
| old scratch | 30 days |
