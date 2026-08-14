#!/usr/bin/env bash
# Retained as a fail-closed tombstone for old operator notes.
set -euo pipefail

for arg in "$@"; do
  case "$arg" in
    -h|--help) ;;
    -v|--volumes)
      echo "REFUSED: no repository script may remove durable volumes." >&2
      exit 2 ;;
    *) ;;
  esac
done

cat >&2 <<'EOF'
REFUSED: the Stocker runtime compose graph is no longer present. This script
will not guess at an external project name or issue any Compose stop against
the current directory. It performed no container or volume operation.

If a legacy deployment still exists on another host, fence its writers using
that deployment's archived runbook. Then use the explicit, account-confirmed
Sentinel handover sequence in docs/sentinel-paper-activation.md.
EOF
exit 64
