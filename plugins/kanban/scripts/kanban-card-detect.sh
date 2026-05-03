#!/usr/bin/env bash
# kanban-card-detect.sh — UserPromptSubmit hook for Jira mode.
#
# Reads the prompt event JSON from stdin, scans the prompt text for Jira
# card keys filtered by backend.jira.projectKey, runs precheck-card per
# detected key (cached 30s), and emits an additionalContext block with one
# section per card. Silent on:
#   - no kanban.json
#   - backend.driver != "jira"
#   - no detected keys / no matches in this project
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

# Stash stdin so the python block can re-read it.
payload="$(cat)"
[ -z "$payload" ] && exit 0

if ! command -v python3 >/dev/null 2>&1; then
  exit 0
fi

KANBAN_PATH="$KANBAN" PLUGIN_LIB="$PLUGIN_LIB" PAYLOAD="$payload" \
  python3 - <<'PY' 2>/dev/null || true
import json, os, sys, subprocess
sys.path.insert(0, os.environ["PLUGIN_LIB"])

try:
    from lib import card_parser, kanban_io
except Exception:
    raise SystemExit(0)

kanban_path = os.environ["KANBAN_PATH"]
try:
    data = kanban_io.load(kanban_path)
except Exception:
    raise SystemExit(0)

backend = data.get("backend") or {}
if backend.get("driver") != "jira":
    raise SystemExit(0)

project_key = (backend.get("jira") or {}).get("projectKey") or ""
if not project_key:
    raise SystemExit(0)

# Extract prompt text from the hook payload.
try:
    payload = json.loads(os.environ["PAYLOAD"])
except Exception:
    raise SystemExit(0)
prompt = (payload.get("prompt") or payload.get("user_prompt") or "")
if not isinstance(prompt, str):
    raise SystemExit(0)

keys = card_parser.extract_for_project(prompt, project_key)
if not keys:
    raise SystemExit(0)

# Cap at 5 to keep context block bounded.
keys = keys[:5]

setup = os.path.join(os.environ["PLUGIN_LIB"], "scripts", "jira_setup.py")
blocks = []
for key in keys:
    # Surface the 3 most-recent comments verbatim in the context block
    # so agents see "stop / cancel / change direction" instructions
    # instead of confidently proceeding in the wrong direction (#42).
    # The 30s precheck cache absorbs the extra API call cost across
    # repeated key references in a session.
    res = subprocess.run(
        ["python3", setup, "precheck-card",
         "--kanban-path", kanban_path,
         "--key", key,
         "--comments-limit", "3"],
        capture_output=True, text=True,
    )
    if res.returncode != 0:
        continue
    try:
        j = json.loads(res.stdout)
    except Exception:
        continue
    block = j.get("context_block")
    if block:
        blocks.append(block)

if not blocks:
    raise SystemExit(0)

context = "\n\n".join(blocks)
out = {
    "hookSpecificOutput": {
        "hookEventName": "UserPromptSubmit",
        "additionalContext": context,
    }
}
print(json.dumps(out))
PY

exit 0
