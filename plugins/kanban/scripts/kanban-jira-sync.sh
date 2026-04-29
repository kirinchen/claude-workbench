#!/usr/bin/env bash
# kanban-jira-sync.sh — SessionStart hook for Jira mode.
#
# When the project's kanban.json has backend.driver == "jira" AND a current
# AP is set in .claude/kanban-agent.json, fetches the open-card summary and
# emits it as additionalContext so the agent picks up where it left off.
# Silent for local mode (kanban-session-check.sh covers that).
#
# Exits 0 always (additive context, never blocks).
set -euo pipefail

PLUGIN_LIB="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

proj="${CLAUDE_PROJECT_DIR:-}"
if [ -z "$proj" ]; then
  proj="$(git rev-parse --show-toplevel 2>/dev/null || pwd)"
fi
KANBAN="$proj/kanban.json"
[ -f "$KANBAN" ] || exit 0

if ! command -v python3 >/dev/null 2>&1; then
  exit 0
fi

KANBAN_PATH="$KANBAN" PLUGIN_LIB="$PLUGIN_LIB" python3 - <<'PY' 2>/dev/null || true
import json, os, subprocess, sys
sys.path.insert(0, os.environ["PLUGIN_LIB"])

try:
    from lib import kanban_io
except Exception:
    raise SystemExit(0)

kanban_path = os.environ["KANBAN_PATH"]
try:
    data = kanban_io.load(kanban_path)
except Exception:
    raise SystemExit(0)

if (data.get("backend") or {}).get("driver") != "jira":
    raise SystemExit(0)

setup = os.path.join(os.environ["PLUGIN_LIB"], "scripts", "jira_setup.py")
res = subprocess.run(
    ["python3", setup, "sync-summary", "--kanban-path", kanban_path],
    capture_output=True, text=True,
)
if res.returncode != 0:
    raise SystemExit(0)

try:
    j = json.loads(res.stdout)
except Exception:
    raise SystemExit(0)

summary = j.get("summary") or ""
if not summary.strip():
    raise SystemExit(0)

out = {
    "hookSpecificOutput": {
        "hookEventName": "SessionStart",
        "additionalContext": summary,
    }
}
print(json.dumps(out))
PY

exit 0
