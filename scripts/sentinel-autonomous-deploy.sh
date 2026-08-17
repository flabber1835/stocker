#!/usr/bin/env bash
# Fully autonomous, fail-closed Alpaca PAPER deployment entrypoint.
#
# It updates only by fast-forward, then re-execs the freshly pulled launcher so
# old orchestration code never continues after changing the checkout beneath
# itself. All authority/trading work lives in sentinel_autonomous_deploy.py.
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON="${SENTINEL_HOST_PYTHON:-${SENTINEL_PYTHON:-python3}}"
"$PYTHON" scripts/sentinel_host_python.py >/dev/null || {
  echo "REFUSED: host Python is incompatible; minimum Python is 3.8.15" >&2
  exit 1
}

TARGET_BRANCH="${SENTINEL_DEPLOY_GIT_BRANCH:-main}"
AFTER_PULL=0
ARGS=()
for arg in "$@"; do
  if [ "$arg" = "--after-fast-forward" ]; then
    AFTER_PULL=1
  else
    ARGS+=("$arg")
  fi
done

if [ "$AFTER_PULL" -eq 0 ]; then
  current_branch="$(git symbolic-ref --quiet --short HEAD 2>/dev/null || true)"
  [ "$current_branch" = "$TARGET_BRANCH" ] || {
    echo "REFUSED: autonomous deployment requires checked-out branch '$TARGET_BRANCH'; current branch is '${current_branch:-DETACHED}'" >&2
    exit 2
  }
  [ -z "$(git status --porcelain --untracked-files=all)" ] || {
    echo "REFUSED: working tree is dirty; autonomous deployment will never reset or discard local work" >&2
    git status --short >&2 || true
    exit 2
  }
  before="$(git rev-parse HEAD)"
  git pull --ff-only origin "$TARGET_BRANCH"
  after="$(git rev-parse HEAD)"
  if [ "$before" != "$after" ]; then
    exec bash scripts/sentinel-autonomous-deploy.sh --after-fast-forward "${ARGS[@]}"
  fi
fi

exec "$PYTHON" scripts/sentinel_autonomous_deploy.py "${ARGS[@]}"
