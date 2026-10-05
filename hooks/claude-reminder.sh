#!/bin/sh
# Claude Code PostToolUse hook: Spindle's mid-session reminder (prompts/reminder.md).
# Fires after every SPINDLE_REMINDER_TOKENS of context growth (default 50,000) or
# SPINDLE_REMINDER_CALLS tool calls (default 50), whichever comes first. Counting is
# done here, so Python only starts when the reminder is due.
root=${CLAUDE_PLUGIN_ROOT:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}
input=$(cat)
field() { printf '%s' "$input" | sed -n "s/.*\"$1\"[[:space:]]*:[[:space:]]*\"\([^\"]*\)\".*/\1/p"; }
sid=$(field session_id | tr -d '-')
[ -n "$sid" ] || exit 0
transcript=$(field transcript_path)

# Context size: input plus cache tokens of the model's latest response in the transcript.
tokens=0
if [ -n "$transcript" ] && [ -f "$transcript" ]; then
  # Only the model's own responses: a subagent's tool result carries its own usage.
  usage=$(tail -n 40 "$transcript" | grep '"type":"assistant"' | grep -o '"usage":{[^}]*}' | tail -n 1)
  for key in input_tokens cache_creation_input_tokens cache_read_input_tokens; do
    n=$(printf '%s' "$usage" | sed -n "s/.*\"$key\":\([0-9]*\).*/\1/p")
    tokens=$((tokens + ${n:-0}))
  done
fi

state="${TMPDIR:-/tmp}/spindle-reminder/$sid"
mkdir -p "$(dirname "$state")"
calls=0; last=$tokens
[ -f "$state" ] && read -r calls last < "$state"
calls=$((calls + 1))
# Compaction shrinks the context: measure growth from the new, smaller size.
[ "$tokens" -lt "$last" ] && last=$tokens
if [ "$calls" -lt "${SPINDLE_REMINDER_CALLS:-50}" ] && [ $((tokens - last)) -lt "${SPINDLE_REMINDER_TOKENS:-50000}" ]; then
  echo "$calls $last" > "$state"
  exit 0
fi
echo "0 $tokens" > "$state"

command -v uv >/dev/null 2>&1 || exit 0
[ -n "$CLAUDE_PROJECT_DIR" ] && export SPINDLE_PROJECT="$CLAUDE_PROJECT_DIR"
# The session is resolved as `thread` resolves it (src/spindle/identity.py).
if out=$(uv run --offline --quiet --frozen --no-dev --project "$root" python -m spindle.reminder \
    --claude-hook PostToolUse 2>/dev/null); then
  printf '%s\n' "$out"
fi
exit 0
