# Spindle

Harness-agnostic memory for agents: threads track ongoing work so a fresh session can pick it up.

Requires git and [uv](https://docs.astral.sh/uv/).

The repository is the plugin: each harness installs a copy of the whole tree.

- `src/spindle/`: the `thread` CLI, and the startup snapshot (`python -m spindle.context`) the hooks inject
- `bin/thread`: runs the CLI through uv; each harness plugin puts `bin/` on PATH
- `skills/`: the agent-facing skills: `spindle-setup` (run once per harness) and `spindle-threads`
- `prompts/system-blurb.md`: the standing instructions `thread setup` installs (Claude Code and omp: a rules file; pi: a block in AGENTS.md)
- `.claude-plugin/`, `hooks/`: the Claude Code plugin
- `package.json`, `extensions/pi.ts`: the pi (and omp) extension
- `schemas/`: JSON schemas for the on-disk format
- `tests/`

## Where threads are stored

Setup asks for a scope, saved in `~/.spindle/config.yml`: `global` (the
default, one store at `~/.spindle`) or `project` (`<project>/.spindle`, started
by the first `thread create` there and kept out of git by a line in your global
git ignore). `--root` or `SPINDLE_ROOT` overrides both.

## Session identity

Every event in a thread's log records who made it, and claims show which sessions are working on
what. Spindle reads identifiers hosts already provide, so no host needs to know about Spindle.
The first of these that is set wins (src/spindle/identity.py):

1. `THREAD_SESSION` (and optionally `THREAD_AGENT`), set by hand.
2. An agent runtime around the harness. Kiln: `KILN_AGENT_ID` (`scout-deep-reach` is session
   `scout-deep-reach`, agent `scout`). kiln-lite: `AGENT_ID` for the session, and the name of the
   `AGENT_HOME` folder for the agent; both must be set, and the id must start with that name.
3. The harness session: `claude-…`, `pi-…` or `omp-…`, the last 8 hex digits of the session id,
   which also find the transcript. Claude Code exports its id; for pi and omp the extension does.
4. `user@host`.

Supporting another runtime is one entry in `HOSTS` in identity.py.
