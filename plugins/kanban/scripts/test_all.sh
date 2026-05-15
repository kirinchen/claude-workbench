#!/usr/bin/env bash
# Run all kanban v0.2 regression suites in order. Stops on first failure.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for n in 1 2 3 4 5 6 7 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30 31 32 33; do  # …32: paste-flow removal + initjira auto-detect (#54), 33: mutation primitives (#55)
  echo "----- phase $n -----"
  python3 "$DIR/test_phase$n.py"
done
echo "all phases passed"
