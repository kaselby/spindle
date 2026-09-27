# Artifacts, docs and reading guides

Artifacts, docs and the reading guide exist so a future session can use what
this one built or learned without redoing it. They're curated: register what's
worth finding, not everything you touched. Working files go in `scratch/`.

## Where things go

- **Checkpoint:** where the work stands right now. Replaced by the next one.
- **Note** (`thread note`): a finding worth keeping in the log. Not shown on the
  view page.
- **Doc:** durable knowledge a future session needs to do the work.
- **Artifact:** something the work produced.
- **Reading guide:** where to look, and in what order.

If it will be wrong after the next checkpoint, it belongs in the checkpoint, not
a doc.

## Artifacts

Artifacts are the outputs: reports, results, figures, datasets, scripts, an
experiment harness. Put them in `<thread>/artifacts/` and register them:

```
thread register <id> artifacts/results.csv --kind artifact --purpose "p95 by endpoint, before and after the fix"
```

- Register an artifact once it's worth keeping, not while it's a draft.
- `--purpose` is one line (at most 160 characters) saying what it is. The view
  page shows it next to the file.
- A directory can be one artifact. The limit is 5 MB; for anything bigger, keep
  it outside the thread and register a small file that says where it is.
- If you replace an artifact, register it again with an updated purpose.

## Docs

Docs are guides for future sessions: how to run the experiments, how the code is
laid out, a design that's been settled, what was tried and ruled out. Put them
in `<thread>/docs/` and register them with a note on when to read them:

```
thread register <id> docs/running-the-benchmark.md --kind doc \
  --purpose "how to run the latency benchmark locally" \
  --read-when "before running or changing the benchmark"
```

The view page lists every doc with its `--read-when`, so that line is how a
session decides whether to open it. Make it a moment ("before changing the
parser"), not a topic.

Writing a good doc:

- Write for a session that arrives with no memory and a specific job to do. Lead
  with what it needs first.
- One doc, one subject. Two short docs beat one long one.
- Keep it true. When something changes, update the doc rather than adding a new
  one next to it.
- Leave out status and next steps. Those go in the checkpoint.

Write a doc when you notice a new session would have to rediscover something:
you explained it to yourself, or it took real effort to work out.

## The reading guide

Once a thread has a few docs, or its important material lives outside the thread
(a repo, a branch, another thread), write a reading guide. It's
`<thread>/reading-guide.md`, and the view page shows it above the docs.

It's a short numbered list of what to read and why, in order:

```
1. `docs/design.md`: the settled design. Read first.
2. `~/Git/search` on branch `p95-fix`: the fix; start at `ranker/cache.py`.
3. `k7q2m9:docs/profiling.md`: how the profiling was done, from the parent.
```

- It can point anywhere: this thread's docs and artifacts, repo paths, branches,
  PRs, URLs, another thread's files as `<id>:docs/<file>`.
- It's for orientation only. No status, no next steps.
- Keep it under 1,500 characters. HTML comments don't count.
- `thread doctor` checks that every local path in it still exists.

After you write or change it, register it so the change is logged:

```
thread register <id> reading-guide.md --kind reading-guide --purpose "added the fix branch"
```

`--purpose` is optional here and says what changed.

## At merge

When a subthread merges, you choose which of its docs and artifacts (and its
reading guide) to copy into the parent with `--promote`. Anything not copied
stays with the archived subthread, and the parent's `index.md` points to it.
