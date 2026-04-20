#!/usr/bin/env bash
# kanban-autocommit.sh — PostToolUse hook that auto-commits kanban.json
# changes, then fans out to sibling workbench plugins (notify, memory) if
# they're installed.
#
# Responsibilities:
#   1. Detect kanban.json changes vs HEAD.
#   2. If kanban.json is the ONLY dirty file, stage + commit standalone.
#   3. Compute which tasks transitioned (prev → new column).
#   4. Dispatch sibling integrations (§6.1, §6.2) when available.
#
# Silent on no-op. Exit 0 always — this is a convenience, never a blocker.
set -euo pipefail

# --- Capability detection (§6.5) ---------------------------------------------
# Siblings expose a `workbench-<name>` CLI when installed. Today only kanban
# ships (§7 meta bundle), so HAS_NOTIFY / HAS_MEMORY stay 0 and the dispatch
# blocks no-op. When notify / memory v0.1.0 ship, these flip automatically.
has_plugin() { command -v "workbench-$1" >/dev/null 2>&1; }
HAS_NOTIFY=0; has_plugin notify && HAS_NOTIFY=1
HAS_MEMORY=0; has_plugin memory && HAS_MEMORY=1

# --- Locate project + kanban.json --------------------------------------------
proj="${CLAUDE_PROJECT_DIR:-}"
if [ -z "$proj" ]; then
  proj="$(git rev-parse --show-toplevel 2>/dev/null || true)"
fi
[ -z "$proj" ] && exit 0
[ -f "$proj/kanban.json" ] || exit 0

cd "$proj"
git rev-parse --git-dir >/dev/null 2>&1 || exit 0

# Is kanban.json actually modified?
if git diff --quiet -- kanban.json 2>/dev/null && \
   git diff --cached --quiet -- kanban.json 2>/dev/null; then
  exit 0
fi

# Refuse if other files are dirty — keep kanban commits standalone.
other_changes="$(git status --porcelain -- . | awk '{print $2}' | grep -v '^kanban\.json$' || true)"
[ -n "$other_changes" ] && exit 0

# --- Compute transitions (prev column → new column) --------------------------
# Output format: one line per changed task: `<id>\t<prev|NEW>\t<new>\t<title>`.
transitions=""
before="$(git show HEAD:kanban.json 2>/dev/null || echo '{}')"
after="$(cat kanban.json)"

if command -v python3 >/dev/null 2>&1; then
  transitions="$(BEFORE="$before" AFTER="$after" python3 - <<'PY' 2>/dev/null || true
import json, os
try:
    a = json.loads(os.environ["BEFORE"])
    b = json.loads(os.environ["AFTER"])
except Exception:
    raise SystemExit(0)
prev_by_id = {t.get("id"): t.get("column") for t in a.get("tasks", []) if t.get("id")}
for t in b.get("tasks", []):
    tid = t.get("id"); col = t.get("column"); title = t.get("title", "")
    if not tid: continue
    prev = prev_by_id.get(tid)
    if prev != col:
        print(f"{tid}\t{prev or 'NEW'}\t{col}\t{title}")
PY
)"
elif command -v jq >/dev/null 2>&1; then
  transitions="$(jq -rn --argjson a "$before" --argjson b "$after" '
    ($a.tasks // []) as $A | ($b.tasks // []) as $B |
    [ $B[] as $t | ($A[] | select(.id == $t.id) | .column) as $prev |
      select($prev != $t.column) |
      "\($t.id)\t\($prev // "NEW")\t\($t.column)\t\($t.title)" ] | .[]
  ' 2>/dev/null || true)"
fi

# --- Commit --------------------------------------------------------------------
summary="kanban: update"
if [ -n "$transitions" ]; then
  short="$(printf '%s\n' "$transitions" | awk -F'\t' '{printf "%s %s→%s, ", $1, $2, $3}' | sed 's/, $//')"
  [ -n "$short" ] && summary="kanban: $short"
fi

git add -- kanban.json
git commit -m "$summary" -- kanban.json >/dev/null 2>&1 || true

# --- Sibling integration: notify (§6.1) --------------------------------------
# No-op today. Wired in so Phase 2 can activate without touching this script.
if [ "$HAS_NOTIFY" -eq 1 ] && [ -n "$transitions" ]; then
  printf '%s\n' "$transitions" | while IFS=$'\t' read -r tid prev new title; do
    case "${prev}->${new}" in
      "TODO->DOING")
        workbench-notify --priority low  --title "Kanban" --message "Started: $title" || true ;;
      "DOING->DONE")
        workbench-notify --priority normal --title "Kanban" --message "Completed: $title" || true ;;
      "DOING->BLOCKED"|"TODO->BLOCKED")
        workbench-notify --priority high --title "Kanban: action needed" --message "$tid blocked: $title" || true ;;
    esac
  done
fi

# --- Sibling integration: memory (§6.2 scenario B) ---------------------------
# No-op today. On DOING→DONE, snapshot into memory for future recall.
if [ "$HAS_MEMORY" -eq 1 ] && [ -n "$transitions" ]; then
  printf '%s\n' "$transitions" | while IFS=$'\t' read -r tid prev new title; do
    if [ "$prev" = "DOING" ] && [ "$new" = "DONE" ]; then
      workbench-memory save \
        --topic "Task $tid: $title" \
        --content "Completed via kanban autocommit." \
        --tags "kanban,done" \
        --source "kanban:$tid" >/dev/null 2>&1 || true
    fi
  done
fi

exit 0
