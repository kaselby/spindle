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

## Session identity

Every change to a thread records who made it, and claims show which sessions are working on
what. Spindle reads identifiers hosts already provide, so no host needs to know about Spindle.
The first of these that is set wins (src/spindle/identity.py):

1. `THREAD_SESSION` (and optionally `THREAD_AGENT`), set by hand.
2. An agent runtime around the harness. Kiln: `KILN_AGENT_ID` (`ayin-deep-reach` is session
   `ayin-deep-reach`, agent `ayin`).
3. The harness session: `claude-…`, `pi-…` or `omp-…`, the last 8 hex digits of the session id,
   which also find the transcript. Claude Code exports its id; for pi and omp the extension does.
4. `user@host`.

Supporting another runtime is one entry in `HOSTS` in identity.py.
