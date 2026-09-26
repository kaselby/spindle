#!/bin/sh
# Claude Code hooks for Spindle (wired in hooks/hooks.json).
#   claude-code.sh SessionStart   (startup|clear) sets up the Bash tool's environment, injects the index
#   claude-code.sh SubagentStart  injects the index once per subagent
# Hook input arrives on stdin and is passed through to spindle.context.
event=$1
root=${CLAUDE_PLUGIN_ROOT:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}
input=$(cat)
if [ "$event" = SessionStart ] && [ -n "$CLAUDE_ENV_FILE" ]; then
  # CLAUDE_ENV_FILE is sourced before each Bash tool command, including after
  # resume and in subagents.
  printf 'export PATH="%s/bin:$PATH"\n' "$root" >> "$CLAUDE_ENV_FILE"
  # The harness session for `thread` (see src/spindle/identity.py). Claude Code
  # exports CLAUDE_CODE_SESSION_ID itself; setting ours too makes the innermost
  # harness win when one harness runs inside another.
  sid=$(printf '%s' "$input" | sed -n 's/.*"session_id"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | tr -d '-')
  if [ -n "$sid" ]; then
    printf 'export SPINDLE_HARNESS_SESSION=claude-%s\n' "$(printf '%s' "$sid" | tail -c 8)" >> "$CLAUDE_ENV_FILE"
  fi
  # The launch folder, for project-scoped stores (src/spindle/scope.py).
  if [ -n "$CLAUDE_PROJECT_DIR" ]; then
    printf "export SPINDLE_PROJECT='%s'\n" "$(printf '%s' "$CLAUDE_PROJECT_DIR" | sed "s/'/'\\\\''/g")" >> "$CLAUDE_ENV_FILE"
  fi
fi
if ! command -v uv >/dev/null 2>&1; then
  msg="Spindle is installed but can't run: it needs uv (https://docs.astral.sh/uv/). Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh"
  printf '{"hookSpecificOutput":{"hookEventName":"%s","additionalContext":"%s"}}\n' "$event" "$msg"
  exit 0
fi
NOT_READY="Spindle's thread snapshot couldn't be built at session start, so no thread list is shown here. If Spindle was just installed, it is finishing its install in the background (this needs network access) and the next session will have the list; if it hasn't been set up yet, suggest the spindle-setup skill to the user. \`thread list\` works now and shows the active threads."
[ -n "$CLAUDE_PROJECT_DIR" ] && export SPINDLE_PROJECT="$CLAUDE_PROJECT_DIR"
set -- --claude-hook "$event"
# Only main sessions hear about missing setup; subagents just get the index.
[ "$event" = SessionStart ] && set -- "$@" --harness claude-code
# Claude Code waits for this hook, so never wait on the network: --offline uses only
# what uv already has installed or cached (the first `thread` command, online,
# finishes setup). hooks.json caps the run time.
# Emit only on success, so a run that prints and then fails can't send two JSON objects.
if out=$(printf '%s' "$input" | uv run --offline --quiet --frozen --no-dev --project "$root" python -m spindle.context "$@"); then
  printf '%s\n' "$out"
else
  # Usually a fresh install: the environment isn't built and uv's cache is empty.
  # Build it in the background, online, so the next session has it; session start
  # still never waits. Harmless when the environment is already complete.
  nohup uv sync --quiet --frozen --no-dev --project "$root" </dev/null >/dev/null 2>&1 &
  msg="$NOT_READY"
  printf '{"hookSpecificOutput":{"hookEventName":"%s","additionalContext":"%s"}}\n' "$event" "$msg"
fi
