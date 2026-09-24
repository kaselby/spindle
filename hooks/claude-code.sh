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
fi
if ! command -v uv >/dev/null 2>&1; then
  msg="Spindle is installed but can't run: it needs uv (https://docs.astral.sh/uv/). Install it with: curl -LsSf https://astral.sh/uv/install.sh | sh"
  printf '{"hookSpecificOutput":{"hookEventName":"%s","additionalContext":"%s"}}\n' "$event" "$msg"
  exit 0
fi
set -- --claude-hook "$event"
# Only main sessions hear about missing setup; subagents just get the index.
[ "$event" = SessionStart ] && set -- "$@" --harness claude-code
printf '%s' "$input" | uv run --quiet --frozen --no-dev --project "$root" python -m spindle.context "$@"
