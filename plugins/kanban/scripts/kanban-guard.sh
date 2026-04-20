#!/usr/bin/env bash
# kanban-guard.sh — PreToolUse hook that blocks direct edits to kanban.json.
#
# Reads the Claude Code PreToolUse event JSON from stdin and exits 2 (blocking
# the tool call) when a Edit/Write/MultiEdit tries to touch kanban.json. The
# AI must go through /kanban:* slash commands instead.
#
# Exit codes:
#   0 — allow tool call
#   2 — block tool call; stderr is surfaced to Claude as an error message
set -euo pipefail

payload="$(cat)"

# Extract fields with jq; fall back to grep if jq is missing.
extract_field() {
  # $1 = field name, $2 = json payload. Emits value or empty string.
  local field="$1" json="$2" out=""
  if command -v jq >/dev/null 2>&1; then
    case "$field" in
      tool_name)   out="$(printf '%s' "$json" | jq -r '.tool_name // empty' 2>/dev/null || true)" ;;
      file_path)   out="$(printf '%s' "$json" | jq -r '.tool_input.file_path // empty' 2>/dev/null || true)" ;;
    esac
  else
    out="$(printf '%s' "$json" | grep -oE "\"${field}\"[[:space:]]*:[[:space:]]*\"[^\"]*\"" 2>/dev/null | head -1 | sed -E 's/.*"([^"]*)"$/\1/' || true)"
  fi
  printf '%s' "$out"
}

tool_name="$(extract_field tool_name "$payload")"
file_path="$(extract_field file_path "$payload")"

# Only guard Edit-family tools.
case "$tool_name" in
  Edit|Write|MultiEdit) ;;
  *) exit 0 ;;
esac

# No file path → nothing to guard.
[ -z "$file_path" ] && exit 0

# Match only exact `kanban.json` filename (any directory).
basename_file="$(basename "$file_path")"
if [ "$basename_file" = "kanban.json" ]; then
  cat >&2 <<'MSG'
kanban-guard: Direct edits to kanban.json are blocked.

Use a /kanban:* slash command instead:
  /kanban:init    — create kanban.json
  /kanban:next    — pick a task and move it to DOING
  /kanban:done    — close a task (DOING → DONE)
  /kanban:block   — move a task to BLOCKED
  /kanban:status  — read-only summary

If you genuinely need to edit kanban.json by hand (migration, recovery),
do it outside of Claude Code.
MSG
  exit 2
fi

exit 0
