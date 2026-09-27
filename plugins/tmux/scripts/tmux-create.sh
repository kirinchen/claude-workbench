#!/usr/bin/env bash
# tmux-create.sh <name> [--cwd DIR] [--run CMD] [--no-run] [--json]
#
# Start a new detached tmux session and, by default, launch `claude` in it.
#
# Deliberately boring and idempotent-ish:
#   * Refuses to touch an existing session (exit 3) — this command creates,
#     it never reuses or restarts. Use /tmux:send on the existing one.
#   * Refuses a name tmux cannot address: `.` and `:` are separators in
#     tmux target syntax, whitespace makes the name untypable (exit 4).
#   * Refuses a working directory that does not exist (exit 5).
#   * The command is typed with `send-keys -l`, Enter a separate key after a
#     pause — same discipline as tmux-input.sh, for the same reason.
#
# Prints the new session's state (via tmux-state.py) on success.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
state_py="$here/tmux-state.py"

# Shell prompt needs to exist before we type into it; `claude` needs longer
# than that before its input box is worth reading.
SHELL_SETTLE="${TMUX_PLUGIN_SHELL_SETTLE:-1}"
TYPE_SETTLE="${TMUX_PLUGIN_TYPE_SETTLE:-0.3}"
BOOT_SETTLE="${TMUX_PLUGIN_BOOT_SETTLE:-6}"

die() { echo "tmux-create: $*" >&2; exit 1; }

usage() {
  sed -n '2,15p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2
  exit 64
}

[ $# -ge 1 ] || usage
name="$1"; shift

cwd="$PWD"
run="claude"
as_json=0

while [ $# -gt 0 ]; do
  case "$1" in
    --cwd)     [ $# -ge 2 ] || die "--cwd needs <dir>"; cwd="$2"; shift 2 ;;
    --run)     [ $# -ge 2 ] || die "--run needs <cmd>"; run="$2"; shift 2 ;;
    --no-run)  run=""; shift ;;
    --json)    as_json=1; shift ;;
    -h|--help) usage ;;
    *)         die "unexpected argument: $1" ;;
  esac
done

case "$name" in
  ""|*[.:]*|*[[:space:]]*)
    echo "tmux-create: bad session name '$name'." >&2
    echo "  '.' and ':' are tmux target separators and whitespace makes the" >&2
    echo "  name untypable. Use letters, digits, '-' and '_'." >&2
    exit 4 ;;
esac

if tmux has-session -t "=$name" 2>/dev/null; then
  echo "tmux-create: session '$name' already exists — not touching it." >&2
  echo "  Read it with tmux-capture.sh, or type into it with tmux-input.sh." >&2
  exit 3
fi

[ -d "$cwd" ] || { echo "tmux-create: no such directory: $cwd" >&2; exit 5; }
cwd="$(cd "$cwd" && pwd)"

case "$run" in
  *$'\n'*) die "--run must not contain a newline" ;;
esac

tmux new-session -d -s "$name" -c "$cwd"

if [ -n "$run" ]; then
  sleep "$SHELL_SETTLE"
  # Plain name, not "=name": the exact-match prefix is a session target and
  # send-keys resolves a *pane* target, where it finds nothing.
  tmux send-keys -t "$name" -l -- "$run"
  sleep "$TYPE_SETTLE"
  tmux send-keys -t "$name" Enter
  sleep "$BOOT_SETTLE"
fi

if [ "$as_json" = "1" ]; then
  python3 - "$state_py" "$name" "$cwd" "$run" <<'PY'
import json, subprocess, sys
state_py, name, cwd, run = sys.argv[1:]
raw = subprocess.run(["python3", state_py, name], capture_output=True, text=True)
st = json.loads(raw.stdout) if raw.returncode == 0 else {"session": name}
st.update({"created": True, "cwd": cwd, "ran": run})
print(json.dumps(st, ensure_ascii=False, indent=2))
PY
  exit 0
fi

echo "created: $name"
echo "cwd:     $cwd"
echo "ran:     ${run:-<none, plain shell>}"
echo
python3 "$state_py" "$name"
