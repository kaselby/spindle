---
name: spindle-setup
description: >
  Sets Spindle up for the harness you're running in: installs its standing
  instructions and creates the thread store if there isn't one. Use when the
  user asks to set up (or update, or remove) Spindle, or when a session-start
  note says Spindle isn't set up or its instructions are out of date.
---

# Setting up Spindle

The Spindle plugin gives you the `thread` command and a snapshot of the active
threads at the start of each session. One step is left, and it's done once per
harness: installing Spindle's standing instructions, which tell every future
session that threads exist and when to use them. Setup does that, and records
where threads are stored.

## 1. Know which harness you're in

Setup needs the harness name, because each one keeps instructions in a
different place:

- `claude-code`: Claude Code. Writes its own file, `~/.claude/rules/spindle.md`.
- `pi`: pi. Adds a marked block to the end of `~/.pi/agent/AGENTS.md`.
- `omp`: oh-my-pi. Writes its own file, `~/.omp/agent/rules/spindle.md`.

Your system prompt normally says which harness you're in. If you can't tell,
ask the user rather than guessing: the wrong name writes to a file this
harness never reads.

## 2. Ask where threads should live

Ask the user, unless they've said: `global` (the default, one store at
`~/.spindle`) or `project` (each project's threads in `<project>/.spindle`,
started by the first `thread create` there). The choice is saved in
`~/.spindle/config.yml`.

## 3. Tell the user what will change, then run it

Setup writes into the user's harness configuration, so say which file (from
the list above) before running it. Then:

```
thread setup --harness <name> --scope <global|project>
```

It prints what it did. Running it again is safe: it replaces only its own file
or block, so it's also how to update the instructions after upgrading Spindle.
`thread setup --harness <name> --check` reports the state without changing
anything.

The instructions take effect in the next session, not this one. Tell the user
that.

## If something goes wrong

- **`thread: command not found`**: the Spindle plugin isn't loaded in this
  session. Ask the user to check it's installed and enabled, then start a new
  session.
- **It says Spindle needs uv**: Spindle runs through
  [uv](https://docs.astral.sh/uv/). Give the user the install command it
  printed; installing software is their call.
- **It says a folder isn't a git repository**: something other than Spindle
  already lives at `~/.spindle`. Show the user the message; don't move or
  delete their files. `SPINDLE_ROOT` can point Spindle somewhere else.

## Removing it

`thread setup --harness <name> --remove` takes the instructions out again. The
thread store stays; deleting it is the user's decision.
