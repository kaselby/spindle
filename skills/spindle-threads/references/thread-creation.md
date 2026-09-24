# Creating a thread

Read this before creating a thread or subthread, promoting a task, or writing
a revision or a new origin for `thread reanchor`.

## The origin

Every thread starts with an origin: why the work exists, and what it
needs to achieve. Every later session reads it first, and every checkpoint is measured
against it. It's never edited. If understanding changes, a revision is
appended below it and the original stays. If the work outgrows it,
`thread reanchor` replaces it and keeps the old one beside it.

Incorrect framing in the origin ripples to every future session - be careful with what you write. Avoid writing hard rules unless you're sure - this is a major source of future drift.

`thread create "title"` with no `--origin` prints the template. Fill it in
and save it in scratch, then run `thread create "title" --origin <file>`.
Add `--parent <id>` for a subthread.

## The sections

### Context & Motivation (required)

Why the work exists: what's going on around it, why it matters, who asked,
and what they were trying to achieve. This is the most important section.

If a user asked for the work, quote them directly, in their own words.
That's more reliable than any paraphrase. If it came from a bug report, a
conversation, or another thread, quote the part that matters. If there's
nothing to quote, say plainly what prompted it.

Include the reason, not just the task. "Fix the flaky auth test" is a task.
"The auth test fails about one run in five and blocks every merge; Dana
suspects last week's token cache" tells the next session what matters,
how urgent it is, and where to start.

### Scope (optional)

What's in and what's out, what's known and unknown, what looks hard. Leave
it out if the context already makes this clear.

This isn't a plan. Plans belong in checkpoints and tasks, because they
change. Don't write it as a checklist either, or later sessions will treat
the list as required.

### Constraints (optional, usually empty)

Only constraints that are genuinely hard, like a deadline, an interface that
can't change, or data that can't leave the machine. Write each one as "X,
because Y", so a later session can tell whether it still applies.

Most threads have none. Don't invent them. A preference written here gets
treated as a rule by every session after you. Ask whether breaking it would
make the result wrong, or just worse. If just worse, it's a preference, and
it can go in Context if it matters.

### Completion criteria (optional)

A hard target, if there is one. Usually there isn't - that's fine, just omit it. Usually used for automations rather than interactive work.

## Example

```markdown
## Context & Motivation

The nightly eval score on the reasoning suite dropped from 71.2 to 64.8
between the Sept 14 and Sept 15 runs, and has stayed there. The user, on
seeing it: "this is probably the tokenizer bump but I don't want to
assume that, the data pipeline also changed that night. I need to know
which before we cut the release candidate."

## Scope

Both suspects landed on the 14th: the tokenizer upgrade (v3.1 → v3.2)
and a change to how few-shot examples are sampled. The eval itself is
assumed correct unless something points at it. Fixing the regression is
in scope if the cause is small; if not, a clear diagnosis is enough.

## Constraints

- Don't revert either change on main to test it, because other teams
  are building on both. Test on a branch.
```

There are no completion criteria here. It's interactive work, and the
Context already says what the answer is for.

## Subthreads

To turn an existing task into a subthread, use `thread promote <parent>
<task-id> "title" --origin <file>`. Otherwise use `thread create "title"
--parent <id>`. Either way, write the subthread's origin in full, and don't
copy the parent's. Say why this piece was split off, what it contributes to
the parent, and what result the parent needs from it.

## Revisions

`thread revise <id> <file>` appends your text to the origin under a dated
heading. Say what changed in your understanding, why, and what it means for
the work. Don't use a revision to record progress. Progress goes in
checkpoints.

## Reanchored origins

`thread reanchor` replaces the origin in place, and the old one stays beside
it as `origin-1.md`. Write the new origin as if the thread were being created
today, self-contained and not in reference to the old one. The change goes
only in a short `## Previous origin` section at the end. lifecycle.md has the
details.
