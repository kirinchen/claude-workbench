#!/usr/bin/env bash
# Run all kanban v0.2 regression suites in order. Stops on first failure.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

for n in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25; do  # 8-25: code-AP / screens (#6) / blocked-by (#8) / conventions (#10) / mentions+reply / sync stale+Q / resolve-doc-link / import (#16+#18) / locale (#17) / self-approve+guardrail (#19+#20) / reconcile (#21) / locale+JQL+ADF (#17 reopen +#26 +#27) / health-oracle (#31) / create_task fixup (#35) / set-conventions append (#36) / list-doing (#33) / secret-safe token capture (session-reported) / precheck recent-comments (#42)
  echo "----- phase $n -----"
  python3 "$DIR/test_phase$n.py"
done
echo "all phases passed"
