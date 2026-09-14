#!/usr/bin/env bash
# Sourced by maintenance checkpoints after COMPOSE and PYTHON are resolved.
sentinel_backup_archive_identity() {
  local expected observed
  expected="$("$PYTHON" -c 'import hashlib; from pathlib import Path; print(hashlib.sha256(Path("scripts/sentinel-archive-wal.sh").read_bytes()).hexdigest())')" || return 1
  observed="$("${COMPOSE[@]}" exec -T -u postgres sentinel-postgres \
    sha256sum /usr/local/libexec/sentinel-archive-wal.sh)" || return 1
  [[ "$expected" =~ ^[0-9a-f]{64}$ ]] && [ "${observed%% *}" = "$expected" ]
}
