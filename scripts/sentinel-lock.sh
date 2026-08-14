#!/usr/bin/env bash
# Generate Sentinel's complete, artifact-hashed Python 3.12 lock.
set -euo pipefail

cd "$(dirname "$0")/.."
PYTHON_IMAGE="python:3.12-slim@sha256:229a2c5bfa27522db7815ea81f9bed70af17ccb9de9fc7ad142b1877b5830d36"
PIP_TOOLS_VERSION="7.5.1"

# pip-compile records every accepted release artifact hash. Index/trusted-host
# settings are deliberately not emitted into the committed lock; builds use
# normal TLS verification and fail if a downloaded artifact is not named there.
docker run --rm -v "$PWD:/work" -w /work "$PYTHON_IMAGE" sh -ceu '
  python -m pip install --disable-pip-version-check --no-cache-dir \
    "pip-tools=='"$PIP_TOOLS_VERSION"'" >/dev/null
  python -m piptools compile \
    --generate-hashes \
    --allow-unsafe \
    --strip-extras \
    --no-emit-index-url \
    --no-emit-trusted-host \
    --output-file sentinel/requirements.lock \
    sentinel/requirements.txt
'

grep -q -- '--hash=sha256:' sentinel/requirements.lock || {
  echo "REFUSED: generated lock contains no artifact hashes" >&2
  exit 1
}
echo "wrote hash-checked sentinel/requirements.lock"
echo "review it, commit it, then rebuild and certify from a clean tree:"
echo "  scripts/sentinel-certify.sh --start YYYY-MM-DD --end YYYY-MM-DD --keep-corpus"
