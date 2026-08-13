#!/usr/bin/env bash
# Retained as a fail-closed tombstone for old operator notes.
set -euo pipefail

cat >&2 <<'EOF'
REFUSED: deploy-wealth-core.sh belonged to the retired Stocker service graph.
It cannot deploy the current repository and intentionally performs no action.

Current, non-trading certification entry point:
  scripts/sentinel-certify.sh --start YYYY-MM-DD --end YYYY-MM-DD

Current deployment and paper-account procedures:
  docs/sentinel-deployment.md
  docs/sentinel-paper-activation.md
EOF
exit 64
