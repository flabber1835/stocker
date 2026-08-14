#!/usr/bin/env bash
# Resolve the Stage-4 automation overlay only with immutable deployment facts.
# This script does not activate automation and grants no broker authority.
set -euo pipefail

cd "$(dirname "$0")/.."

: "${SENTINEL_RUNTIME_IMAGE_DIGEST:?set sha256 runtime image digest}"
: "${SENTINEL_TEST_IMAGE_DIGEST:?set sha256 test image digest}"
: "${SENTINEL_GIT_COMMIT:?set exact built Git commit}"

[[ "${SENTINEL_RUNTIME_IMAGE_DIGEST}" =~ ^sha256:[0-9a-f]{64}$ ]] || {
  echo "REFUSED: SENTINEL_RUNTIME_IMAGE_DIGEST is not an immutable sha256 digest" >&2
  exit 2
}
[[ "${SENTINEL_TEST_IMAGE_DIGEST}" =~ ^sha256:[0-9a-f]{64}$ ]] || {
  echo "REFUSED: SENTINEL_TEST_IMAGE_DIGEST is not an immutable sha256 digest" >&2
  exit 2
}
[[ "${SENTINEL_GIT_COMMIT}" =~ ^[0-9a-f]{40}([0-9a-f]{24})?$ ]] || {
  echo "REFUSED: SENTINEL_GIT_COMMIT is not an exact Git object id" >&2
  exit 2
}

exec docker compose \
  -f docker-compose.sentinel.yml \
  -f docker-compose.sentinel-backup.yml \
  -f docker-compose.sentinel-automation.yml \
  --profile automation "$@"
