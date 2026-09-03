#!/usr/bin/env bash
# Fail-closed Sentinel fenced-installation entrypoint.
#
# A host-global lock is acquired before Git can move, so a second invocation
# cannot fast-forward the checkout underneath an active deployment. The lock FD
# is inherited across exec, including the re-exec after a successful ff-only
# update. The Python bootstrap recovers only facts already authoritative in the
# existing deployment; it never guesses account authority or an arbitrary key.
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON="${SENTINEL_HOST_PYTHON:-${SENTINEL_PYTHON:-python3}}"
"$PYTHON" scripts/sentinel_host_python.py >/dev/null || {
  echo "REFUSED: host Python is incompatible; minimum Python is 3.8.15" >&2
  exit 1
}

# Serialize the whole deployment, including the Git update. Python owns the
# flock because fcntl is already part of Sentinel's supported Linux host
# contract; the descriptor is deliberately inheritable across exec/re-exec.
if [ -z "${SENTINEL_DEPLOY_LOCK_FD:-}" ]; then
  exec "$PYTHON" - "$0" "$@" <<'PY'
import fcntl
import os
import sys
from datetime import datetime, timezone

path = "/tmp/sentinel-autonomous-deploy.lock"
handle = open(path, "a+", encoding="utf-8")
try:
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
except OSError:
    print("REFUSED: another autonomous Sentinel deployment is running", file=sys.stderr)
    raise SystemExit(2)
handle.seek(0)
handle.truncate()
handle.write("pid=%d started=%s\n" % (
    os.getpid(), datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
handle.flush()
os.set_inheritable(handle.fileno(), True)
env = dict(os.environ)
env["SENTINEL_DEPLOY_LOCK_FD"] = str(handle.fileno())
os.execvpe("bash", ["bash", sys.argv[1]] + sys.argv[2:], env)
PY
fi

# Refuse a forged/stale marker rather than treating an environment variable as
# proof that the lock is held.
"$PYTHON" - "$SENTINEL_DEPLOY_LOCK_FD" <<'PY'
import fcntl
import os
import sys
fd = int(sys.argv[1])
os.fstat(fd)
fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
PY

TARGET_BRANCH="${SENTINEL_DEPLOY_GIT_BRANCH:-main}"
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
  exec bash scripts/sentinel-autonomous-deploy.sh "$@"
fi

# The supported installer owns first-install secret provisioning. This is
# idempotent for an existing key and will generate a missing publication receipt
# authority only when PostgreSQL proves that no authenticated receipt ancestry
# exists. It never prints the secret.
"$PYTHON" scripts/sentinel_deployment_bootstrap.py

# The deployable image now runs as fixed uid/gid 10001. Upgrade an existing
# audit-only named volume before the bootstrap starts any new runtime. Fresh
# installations have no volume yet and this helper exits successfully.
bash scripts/sentinel-state-volume-permissions.sh

exec "$PYTHON" scripts/sentinel_autonomous_deploy_bootstrap.py "$@"
