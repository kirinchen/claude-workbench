#!/usr/bin/env bash
# kanban-session-check.sh — SessionStart / UserPromptSubmit hook.
#
# Skeleton implementation for v0.1.0. Responsibilities:
#   • SessionStart (no args):    surface DOING tasks so Claude picks up where
#                                 last session left off. Future: also `git fetch`
#                                 and detect remote kanban.json changes.
#   • --lightweight:              same, but lower noise (intended for
#                                 UserPromptSubmit — fires on every prompt).
#
# Output contract: if anything noteworthy, print JSON with a `systemMessage`
# to stdout (Claude Code SessionStart hook protocol). Silent on no-op.
# Always exit 0 — this is additive context, never a blocker.
set -euo pipefail

LIGHTWEIGHT=0
for arg in "$@"; do
  case "$arg" in
    --lightweight) LIGHTWEIGHT=1 ;;
  esac
done

# --- Capability detection (§6.5) ---------------------------------------------
# Siblings are still stubs today; these vars stay 0, integration blocks are
# no-op. When notify / memory ship real CLIs, flip without touching this file.
has_plugin() { command -v "workbench-$1" >/dev/null 2>&1; }
HAS_NOTIFY=0; has_plugin notify && HAS_NOTIFY=1
HAS_MEMORY=0; has_plugin memory && HAS_MEMORY=1
export HAS_NOTIFY HAS_MEMORY

# --- Locate kanban.json ------------------------------------------------------
proj="${CLAUDE_PROJECT_DIR:-}"
if [ -z "$proj" ]; then
  proj="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
fi
KANBAN="$proj/kanban.json"
[ -f "$KANBAN" ] || exit 0

# --- Extract DOING / BLOCKED summary -----------------------------------------
# Prefer python3 (always present on Linux/macOS). Falls back to jq.
summary=""
if command -v python3 >/dev/null 2>&1; then
  summary="$(KANBAN_PATH="$KANBAN" LIGHTWEIGHT="$LIGHTWEIGHT" python3 - <<'PY' 2>/dev/null || true
import json, os
path = os.environ["KANBAN_PATH"]
lightweight = os.environ["LIGHTWEIGHT"] == "1"
try:
    with open(path) as f:
        data = json.load(f)
except Exception:
    raise SystemExit(0)
tasks = data.get("tasks", [])
doing = [t for t in tasks if t.get("column") == "DOING"]
blocked = [] if lightweight else [t for t in tasks if t.get("column") == "BLOCKED"]

lines = []
if doing:
    lines.append("DOING tasks in this project's kanban.json:")
    for t in doing:
        lines.append(f"  • {t.get('id')} [{t.get('priority')}] {t.get('title')} (since {t.get('started') or '?'})")
if blocked:
    if lines: lines.append("")
    lines.append("BLOCKED tasks (may need your decision):")
    for t in blocked:
        reason = (t.get("custom") or {}).get("blocked_reason") or "no reason"
        lines.append(f"  • {t.get('id')} [{t.get('priority')}] {t.get('title')} — {reason}")
print("\n".join(lines), end="")
PY
)"
elif command -v jq >/dev/null 2>&1; then
  doing="$(jq -r '[.tasks[] | select(.column=="DOING") | "  • \(.id) [\(.priority)] \(.title) (since \(.started // "?"))"] | .[]' "$KANBAN" 2>/dev/null || true)"
  if [ "$LIGHTWEIGHT" -eq 0 ]; then
    blocked="$(jq -r '[.tasks[] | select(.column=="BLOCKED") | "  • \(.id) [\(.priority)] \(.title) — \(.custom.blocked_reason // "no reason")"] | .[]' "$KANBAN" 2>/dev/null || true)"
  else
    blocked=""
  fi
  [ -n "$doing" ] && summary="DOING tasks in this project's kanban.json:"$'\n'"$doing"
  [ -n "$blocked" ] && summary="${summary:+$summary$'\n\n'}BLOCKED tasks (may need your decision):"$'\n'"$blocked"
fi

[ -z "$summary" ] && exit 0

# Emit as SessionStart / UserPromptSubmit additional context.
if command -v python3 >/dev/null 2>&1; then
  MSG="$summary" python3 -c 'import json,os; print(json.dumps({"hookSpecificOutput":{"hookEventName":"SessionStart","additionalContext":os.environ["MSG"]}}))' 2>/dev/null || printf '%s\n' "$summary"
elif command -v jq >/dev/null 2>&1; then
  jq -n --arg msg "$summary" '{hookSpecificOutput:{hookEventName:"SessionStart",additionalContext:$msg}}'
else
  printf '%s\n' "$summary"
fi

exit 0
