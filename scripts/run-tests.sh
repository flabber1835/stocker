#!/usr/bin/env bash
# Local diagnostic execution in the same pinned dependency lens used by CI.
set -euo pipefail

if [ "${SENTINEL_IN_IMAGE:-}" = 1 ]; then
  cd /work
  exec python tools/local_test_runner.py "$@"
fi

cd "$(dirname "${BASH_SOURCE[0]}")/.."
image="${SENTINEL_TEST_IMAGE:-sentinel-test:local}"
evidence="${SENTINEL_TEST_EVIDENCE:-$(mktemp -d "${TMPDIR:-/tmp}/sentinel-local-tests.XXXXXX")}"
mkdir -p "$evidence"
evidence="$(cd "$evidence" && pwd)"
echo "Local test evidence: $evidence"
exec docker run --rm --network none \
  -v "$evidence:/local-evidence" \
  --entrypoint python "$image" /work/tools/local_test_runner.py \
  --evidence /local-evidence "$@"
