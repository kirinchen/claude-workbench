#!/usr/bin/env bash
# cron-runner.sh — headless Claude Code runner for kanban automation.
#
# Invoked by cron on a schedule (default every 10 minutes). Pulls latest git,
# launches `claude -p` in headless mode to process any new TODO tasks, and
# logs output. Uses flock to prevent overlapping runs.
#
# Usage:
#   cron-runner.sh <project-dir>
#
# Authentication: uses the host user's existing `claude login` (Claude Pro/Max
# subscription). Does NOT consume API credits. See §9 of SPEC for the security
# considerations — notably `--allowedTools` is explicit (no wildcards).
set -euo pipefail

# Cron spawns with a minimal PATH (typically just /usr/bin:/bin). Ensure we
# can find `claude` itself AND the sibling workbench-* CLIs. User-level bin
# dirs get prepended; system PATH preserved.
_WB_BIN="$HOME/.claude-workbench/bin"
_USER_BIN="$HOME/.local/bin"
for d in "$_WB_BIN" "$_USER_BIN"; do
  case ":${PATH:-}:" in
    *":$d:"*) ;;
    *) [ -d "$d" ] && export PATH="$d:${PATH:-}" ;;
  esac
done

PROJECT_DIR="${1:?project dir required as first argument}"
PROJECT_DIR="$(realpath "$PROJECT_DIR")"
LOG_DIR="${KANBAN_LOG_DIR:-$HOME/.claude-workbench/logs}"
LOCK_FILE="/tmp/kanban-$(printf '%s' "$PROJECT_DIR" | md5sum | awk '{print $1}').lock"

mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/cron-runner.log"

# --- Mutex: only one concurrent run per project --------------------------------
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
  echo "[$(date -Iseconds)] skipped — previous run still executing" >>"$LOG_FILE"
  exit 0
fi

# --- Pre-flight ---------------------------------------------------------------
cd "$PROJECT_DIR"
[ -f kanban.json ] || { echo "[$(date -Iseconds)] no kanban.json, exiting" >>"$LOG_FILE"; exit 0; }
git rev-parse --git-dir >/dev/null 2>&1 || { echo "[$(date -Iseconds)] not a git repo" >>"$LOG_FILE"; exit 0; }

# Fast-forward if remote changed. Never merge — avoid silent conflict resolution.
git fetch --quiet 2>>"$LOG_FILE" || true
if ! git pull --quiet --ff-only 2>>"$LOG_FILE"; then
  echo "[$(date -Iseconds)] non-FF state, skipping (manual resolution required)" >>"$LOG_FILE"
  exit 0
fi

# --- Only run if there is work ------------------------------------------------
# Cheap local check: count TODO tasks whose deps are all DONE. Skip invoking
# Claude entirely when there's nothing to do.
READY=$(python3 - <<'PY' 2>/dev/null || echo 0
import json
try:
    d = json.load(open("kanban.json"))
except Exception:
    print(0); raise SystemExit
done_ids = {t["id"] for t in d.get("tasks", []) if t.get("column") == "DONE"}
ready = 0
for t in d.get("tasks", []):
    if t.get("column") != "TODO": continue
    deps = t.get("depends") or []
    if all(dep in done_ids for dep in deps):
        ready += 1
print(ready)
PY
)
if [ "${READY:-0}" = "0" ]; then
  echo "[$(date -Iseconds)] no ready TODO tasks, exiting" >>"$LOG_FILE"
  exit 0
fi

# --- Invoke headless Claude ---------------------------------------------------
echo "[$(date -Iseconds)] starting headless claude for $PROJECT_DIR (ready=$READY)" >>"$LOG_FILE"

# Note: --allowedTools is intentionally minimal. Expand only when you trust
# the tasks in kanban.json not to require risky tools.
claude -p "/kanban:next and execute the picked task. When finished, /kanban:done." \
  --allowedTools "Read,Write,Edit,Bash(git:*),Bash(date:*)" \
  --permission-mode acceptEdits \
  --output-format json \
  >>"$LOG_FILE" 2>&1 || echo "[$(date -Iseconds)] claude exited non-zero" >>"$LOG_FILE"

echo "[$(date -Iseconds)] run complete" >>"$LOG_FILE"
exit 0
