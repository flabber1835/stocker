#!/usr/bin/env bash
# The ONE place that decides which compose file this host runs.
#
# ## Why a resolver and not an override
#
# A Synology DS216+II (kernel 3.10.108, cgroup v1) has no CPU CFS quota, so
# `cpus:` makes the daemon REFUSE before the container is created:
#
#     Error response from daemon: NanoCPUs can not be set, as your kernel does
#     not support CPU CFS scheduler or the cgroup is not mounted
#
# Compose overrides MERGE; they cannot delete a key. `cpus: 0` in an override
# does avoid the daemon's check — it is gated on `NanoCPUs > 0` — but the field
# survives into `docker compose config`, so the deployment still ADVERTISES a
# ceiling it does not have. That is the defect, not the fix.
#
# So the CPU-free deployment is GENERATED from the canonical file, every
# invocation, by deleting exactly the `cpus:` keys and nothing else. It is
# derived rather than maintained, so it cannot drift, and no operator edits
# YAML. `mem_limit` and `shm_size` are untouched and stay enforced — this host
# supports both, and they are the half that protects the machine.
#
# ## Usage
#
#     eval "docker compose $(scripts/sentinel-compose.sh) up -d sentinel-postgres"
#     docker compose $(scripts/sentinel-compose.sh) run --rm -T sentinel status
#
# It prints `-f <path>` arguments and nothing else, so it composes into any
# command. Diagnostics go to stderr.
#
#     scripts/sentinel-compose.sh --explain    what it decided, and why
#
# `SENTINEL_FORCE_CPU_LIMITS=1` keeps the canonical file regardless of the
# probe — for proving on a capable host that the canonical path still works.
set -euo pipefail

cd "$(dirname "$0")/.."

CANONICAL="docker-compose.sentinel.yml"
GENERATED="artifacts/compose/docker-compose.sentinel.nocpu.yml"
EXPLAIN=0
[ "${1:-}" = "--explain" ] && EXPLAIN=1

note() { [ "$EXPLAIN" -eq 1 ] && printf '%s\n' "$*" >&2 || true; }

if [ "${SENTINEL_FORCE_CPU_LIMITS:-0}" = "1" ]; then
  note "SENTINEL_FORCE_CPU_LIMITS=1 — using the canonical file unprobed"
  printf -- '-f %s' "${CANONICAL}"
  exit 0
fi

CAPS="$(python3 scripts/sentinel_host_capabilities.py --json 2>/dev/null || echo '{}')"
USABLE="$(printf '%s' "${CAPS}" | python3 -c \
  'import json,sys
try: d = json.load(sys.stdin)
except ValueError: d = {}
# FAIL TOWARD THE CANONICAL FILE. An unprobed host keeps its declared ceilings:
# the failure mode is a loud daemon refusal, whereas guessing UNSUPPORTED would
# silently drop every CPU limit on a host that can hold them.
print("1" if d.get("cpu_limits_usable", True) else "0")' 2>/dev/null || echo 1)"

if [ "${USABLE}" = "1" ]; then
  note "CPU quota ENFORCED — canonical ${CANONICAL}"
  printf -- '-f %s' "${CANONICAL}"
  exit 0
fi

note "CPU quota UNSUPPORTED on this host — generating ${GENERATED}"
mkdir -p "$(dirname "${GENERATED}")"
python3 scripts/sentinel_strip_cpu_limits.py "${CANONICAL}" "${GENERATED}" \
  >&2 || { echo "could not generate the CPU-free compose file" >&2; exit 1; }
printf -- '-f %s' "${GENERATED}"
