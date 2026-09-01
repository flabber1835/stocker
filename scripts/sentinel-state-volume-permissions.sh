#!/usr/bin/env bash
# Migrate the audit-only Sentinel state volume to the fixed runtime uid/gid.
# No broker/database credentials are passed to the helper container.
set -euo pipefail

cd "$(dirname "$0")/.."

VOLUME="sentinel_sentinel_state"
RUNTIME_UID="10001"
RUNTIME_GID="10001"
HELPER_IMAGE="postgres:16@sha256:95206741a5b214807675e14165369d05b93a9cf692223b616d07cca227e74b0b"

# First installation has no volume yet. Docker will initialize the new named
# volume from /var/lib/sentinel in the hardened image, preserving uid/gid 10001.
if ! docker volume inspect "$VOLUME" >/dev/null 2>&1; then
  exit 0
fi

# An older Sentinel image created this named volume while running as root.
# Repair numeric ownership before the first non-root runtime starts. The helper
# has no network and receives only this audit volume; the canonical behavioral
# database is a separate volume and is never mounted here.
docker run --rm --network none --user 0:0 \
  -v "$VOLUME:/sentinel-state" \
  --entrypoint sh "$HELPER_IMAGE" -ceu '
    chown -R 10001:10001 /sentinel-state
    test "$(stat -c %u /sentinel-state)" = 10001
    test "$(stat -c %g /sentinel-state)" = 10001
  '
