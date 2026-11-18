#!/usr/bin/env bash
# Start a new herdr-core terminal in a directory, launch a program in it, and
# add it to the Herdr App sidebar. Deterministic half of /hc:create.
#
#   hc-create.sh <name> --cwd <dir> [--run <cmd> | --no-run] [--task <first message>]
#
# Defaults to launching `claude`. The terminal is started with --keep (a core
# restart / reboot leaves a shell in its place) and --no-parent (it does not die
# with whoever created it).
#
# Exit: 3 name already live · 4 name not valid for hc · 5 directory missing
#       6 hc missing / core unreachable · 0 created (prints `hc get` JSON)
set -euo pipefail

name="${1:-}"; shift || true
cwd=""; run="claude"; task=""
while [ $# -gt 0 ]; do
  case "$1" in
    --cwd) cwd="${2:-}"; shift 2 ;;
    --run) run="${2:-}"; shift 2 ;;
    --no-run) run=""; shift ;;
    --task) task="${2:-}"; shift 2 ;;
    *) echo "hc-create: unknown argument: $1" >&2; exit 64 ;;
  esac
done

command -v hc >/dev/null || { echo "hc-create: \`hc\` (herdr-core) is not on PATH." >&2; exit 6; }
if ! printf '%s' "$name" | grep -Eq '^[a-z0-9_-]{1,32}$'; then
  echo "hc-create: invalid name '$name' — hc names are 1-32 of a-z 0-9 - _ (lower case, no dots or spaces)." >&2
  exit 4
fi
[ -n "$cwd" ] && [ -d "$cwd" ] || { echo "hc-create: directory does not exist: ${cwd:-<none given>}" >&2; exit 5; }
cwd="$(cd "$cwd" && pwd)"

if state="$(hc get "$name" --json 2>/dev/null)" && printf '%s' "$state" | grep -q '"state":"live"'; then
  echo "hc-create: a live terminal named '$name' already exists — not touching it." >&2
  exit 3
fi

# hc's own flags must come BEFORE `--`; anything after it is the program's argv.
args=(run --bg --keep --no-parent --name "$name" --cwd "$cwd" --json)
if [ -n "$run" ]; then
  # shellcheck disable=SC2206  # --run is a command line; split it into argv on purpose
  prog=($run)
  [ -n "$task" ] && prog+=("$task")
  args+=(-- "${prog[@]}")
fi
hc "${args[@]}" >/dev/null || { echo "hc-create: hc run failed." >&2; exit 6; }

# Without this the terminal exists in the core but the Herdr App never shows it.
python3 "$(dirname "$0")/hc-app-place.py" "$name" >&2 || echo "hc-create: warning — not added to the Herdr App layout; reach it with: hc attach $name" >&2

hc wait "$name" --timeout 20 --json >/dev/null 2>&1 || true
hc get "$name" --json
