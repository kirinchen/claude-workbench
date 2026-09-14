#!/usr/bin/env bash
# tmux-sessions.sh [--json]
#
# List every tmux session with what it is doing right now: attached flag,
# foreground command, derived status (idle / busy / queued / dialog), whether
# its input box already holds a draft, and its last non-empty content line.
#
# Default output is an aligned table for humans; --json emits an array for
# programmatic use. Session names are NOT tab-completable anywhere in this
# plugin — run this first, then type the name you want.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
as_json=0
[ "${1:-}" = "--json" ] && as_json=1

if ! tmux has-session 2>/dev/null; then
  echo "tmux-sessions: no tmux server running (no sessions)." >&2
  exit 2
fi

names=()
while IFS= read -r line; do
  [ -n "$line" ] && names+=("$line")
done < <(tmux list-sessions -F '#{session_name}')

python3 - "$here" "$as_json" "${names[@]}" <<'PY'
import json
import subprocess
import sys
import unicodedata

here, as_json, *names = sys.argv[1:]
as_json = as_json == "1"


def tmux(*args):
    return subprocess.run(["tmux", *args], capture_output=True, text=True).stdout


rows = []
for name in names:
    raw = subprocess.run(
        ["python3", f"{here}/tmux-state.py", name],
        capture_output=True, text=True,
    )
    st = json.loads(raw.stdout) if raw.returncode == 0 else {
        "session": name, "status": "unknown", "summary": "",
        "ui": "unknown", "has_draft": False, "ghost": "", "pane_command": "",
    }
    st["attached"] = tmux(
        "display-message", "-p", "-t", name, "#{session_attached}"
    ).strip() == "1"
    rows.append(st)

if as_json:
    print(json.dumps(rows, ensure_ascii=False, indent=2))
    raise SystemExit(0)


def width(s):
    """Terminal columns, counting CJK/emoji as 2."""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def pad(s, n):
    return s + " " * max(0, n - width(s))


def clip(s, n):
    out = ""
    for c in s:
        if width(out + c) > n:
            return out + "…"
        out += c
    return out


name_w = max([width(r["session"]) for r in rows] + [7])
stat_w = max([width(r["status"]) for r in rows] + [6])

print(f"{pad('session', name_w)}  {pad('status', stat_w)}  draft  last line")
for r in rows:
    mark = "●" if r["attached"] else " "
    # "~" = a dim placeholder of abandoned input, not text anyone can send.
    draft = "yes" if r.get("has_draft") else (" ~ " if r.get("ghost") else " - ")
    print(
        f"{pad(r['session'], name_w)}{mark} {pad(r['status'], stat_w)}  "
        f"{draft}    {clip(r.get('summary', ''), 60)}"
    )
print()
print("● = attached.  draft: yes = real unsent text, ~ = dim placeholder only.")
print("Names are not auto-completed — copy one from this list.")
PY
