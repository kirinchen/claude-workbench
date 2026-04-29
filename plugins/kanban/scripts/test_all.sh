#!/usr/bin/env bash
# Run all kanban v0.2 regression suites in order. Stops on first failure.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for n in 1 2 3 4 5 6 7; do
  echo "----- phase $n -----"
  python3 "$DIR/test_phase$n.py"
done
echo "all phases passed"
