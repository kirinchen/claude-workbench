#!/usr/bin/env bash
# tmux-capture.sh <session> [-S <lines>]
#
# Dump what a tmux session's active pane shows, scrollback included, with
# blank lines dropped so an LLM reads content instead of whitespace.
#
# -S defaults to 200 lines of history. Accepts either form: `-S 200` or
# `-S -200`. Use `-S 0` for the visible screen only.
#
# Fails loud (exit 2) and lists the live sessions if <session> is unknown.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

usage() { echo "usage: tmux-capture.sh <session> [-S <lines>]" >&2; exit 64; }

[ $# -ge 1 ] || usage
session="$1"; shift
history_lines=200

while [ $# -gt 0 ]; do
  case "$1" in
    -S|--start) [ $# -ge 2 ] || usage; history_lines="${2#-}"; shift 2 ;;
    -h|--help)  usage ;;
    *)          echo "tmux-capture: unexpected argument: $1" >&2; usage ;;
  esac
done

case "$history_lines" in
  ''|*[!0-9]*) echo "tmux-capture: -S needs a number, got: $history_lines" >&2; exit 64 ;;
esac

# Reuse the state script's fail-loud session check so both agree on the message.
python3 "$here/tmux-state.py" "$session" --field session >/dev/null

echo "### session: $session  (last $history_lines lines of scrollback + screen)"
tmux capture-pane -p -S "-$history_lines" -t "$session" | grep -v '^[[:space:]]*$' || true
