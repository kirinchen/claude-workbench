#!/usr/bin/env bash
# tmux-input.sh <session> --get
# tmux-input.sh <session> --set  "<text>"   # replace the input box, do NOT submit
# tmux-input.sh <session> --send "<text>"   # replace, then press Enter
# tmux-input.sh <session> --append "<text>" # type at the cursor, no clearing
# tmux-input.sh <session> --clear
#
# Everything deterministic about touching another session's input box lives
# here; the slash commands only compose the text.
#
# Behaviour notes (all of these are hard-won — see README "Known traps"):
#   * Text goes in with `send-keys -l`, and Enter is ALWAYS a separate
#     send-keys after a short pause. Bundling them drops characters.
#   * Clearing is `End` + `C-u`, looped. In the Claude Code box C-u kills only
#     from the start of the *visual* line to the cursor, so one press does not
#     empty a wrapped draft.
#   * Refuses to type into a pane showing a dialog/selector, and into the
#     session this script is running in (use --allow-self to override).
#   * Embedded newlines are rejected: a literal newline would submit early.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
state_py="$here/tmux-state.py"

# Tuned on tmux 3.4 + Claude Code 2.x. Raise if a loaded box misses keys.
TYPE_SETTLE="${TMUX_PLUGIN_TYPE_SETTLE:-0.3}"   # after -l text, before Enter
KEY_SETTLE="${TMUX_PLUGIN_KEY_SETTLE:-0.25}"    # after a control key
CLEAR_MAX_ROUNDS="${TMUX_PLUGIN_CLEAR_ROUNDS:-40}"

die() { echo "tmux-input: $*" >&2; exit 1; }

usage() {
  sed -n '2,10p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2
  exit 64
}

state_field() { python3 "$state_py" "$session" --field "$1"; }

[ $# -ge 2 ] || usage
session="$1"; shift
mode=""
text=""
allow_self=0

while [ $# -gt 0 ]; do
  case "$1" in
    --get|--clear)            mode="${1#--}"; shift ;;
    --set|--send|--append)    mode="${1#--}"; [ $# -ge 2 ] || die "$1 needs <text>"
                              text="$2"; shift 2 ;;
    --allow-self)             allow_self=1; shift ;;
    -h|--help)                usage ;;
    *)                        die "unexpected argument: $1" ;;
  esac
done
[ -n "$mode" ] || usage

# Fail loud on an unknown session (tmux-state.py prints the live list).
python3 "$state_py" "$session" --field session >/dev/null

if [ "$mode" = "get" ]; then
  exec python3 "$state_py" "$session"
fi

# --- guards for anything that types ------------------------------------------

if [ "$allow_self" -eq 0 ] && [ -n "${TMUX:-}" ]; then
  self="$(tmux display-message -p '#S' 2>/dev/null || true)"
  [ "$self" != "$session" ] || die \
    "refusing to type into '$session' — that is this very session. Use --allow-self if you really mean it."
fi

ui="$(state_field ui)"
[ "$ui" != "dialog" ] || die \
  "'$session' is showing a dialog/selector, not an input box. Answer or dismiss it first (nothing was typed)."

case "$text" in
  *$'\n'*) die "text contains a newline — send one line at a time (a literal newline submits early)." ;;
esac

# --- clearing -----------------------------------------------------------------

clear_box() {
  if [ "$ui" != "claude-code" ]; then
    # Plain shell / unknown TUI: readline's C-u kills the whole logical line,
    # so one End+C-u is both necessary and sufficient. Best effort.
    tmux send-keys -t "$session" End;  sleep "$KEY_SETTLE"
    tmux send-keys -t "$session" C-u;  sleep "$KEY_SETTLE"
    return 0
  fi
  local i
  for i in $(seq 1 "$CLEAR_MAX_ROUNDS"); do
    [ "$(state_field has_draft)" = "false" ] && return 0
    tmux send-keys -t "$session" End;  sleep "$KEY_SETTLE"
    tmux send-keys -t "$session" C-u;  sleep "$KEY_SETTLE"
  done
  [ "$(state_field has_draft)" = "false" ] || die \
    "could not empty the input box of '$session' after $CLEAR_MAX_ROUNDS rounds — it may be taking keys elsewhere. Left as-is."
}

type_text() {
  [ -n "$text" ] || return 0
  tmux send-keys -t "$session" -l -- "$text"
  sleep "$TYPE_SETTLE"
}

case "$mode" in
  clear)  clear_box ;;
  append) type_text ;;
  set)    clear_box; type_text ;;
  send)
    clear_box
    type_text
    # Enter strictly on its own, after the text has settled.
    tmux send-keys -t "$session" Enter
    # Give the target a beat to either start work or show the queue placeholder.
    sleep 1.5
    ;;
esac

python3 "$state_py" "$session"
