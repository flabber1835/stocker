#!/usr/bin/env bash
# Run a signed-authority or broker-capable command in the reviewed immutable
# Sentinel image. This wrapper neither installs authority nor contacts a broker
# unless the explicitly supplied Sentinel subcommand does so.
set -euo pipefail

cd "$(dirname "$0")/.."

: "${SENTINEL_RUNTIME_IMAGE_DIGEST:?set sha256 runtime image digest}"
: "${SENTINEL_TEST_IMAGE_DIGEST:?set sha256 test image digest}"
: "${SENTINEL_GIT_COMMIT:?set exact built Git commit}"
: "${SENTINEL_AUTHORITY_ARTIFACTS_DIR:?set the dedicated reviewed artifact directory}"

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
[[ $# -gt 0 ]] || {
  echo "REFUSED: name one explicit Sentinel command" >&2
  exit 2
}
[[ -d "${SENTINEL_AUTHORITY_ARTIFACTS_DIR}" ]] || {
  echo "REFUSED: SENTINEL_AUTHORITY_ARTIFACTS_DIR is not an existing directory" >&2
  exit 2
}
SENTINEL_AUTHORITY_ARTIFACTS_DIR="$(
  cd "${SENTINEL_AUTHORITY_ARTIFACTS_DIR}" && pwd -P
)"
export SENTINEL_AUTHORITY_ARTIFACTS_DIR

# Use the same host-capability resolver as every ordinary Sentinel invocation.
# On Synology this strips CPU CFS limits from BOTH the base graph and the
# signed-authority overlay before Compose ever sees them.
exec bash scripts/sentinel-compose.sh --automation-overlay --run \
  --profile authorized-cli run --rm sentinel-authorized-cli "$@"
