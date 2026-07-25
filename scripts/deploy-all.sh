#!/usr/bin/env bash
# deploy-all.sh — ONE command that deploys everything, from any starting state.
#
# WHY THIS EXISTS. The per-service deploy (scripts/deploy.sh api pipeline …) is
# correct and fast when you know exactly what changed. After a long session
# spanning shared/ schema changes, two new shared modules, a compose edit and
# both stacks, "what do I need to rebuild?" stops being answerable from memory —
# and the failure mode of guessing wrong is silent: a service keeps running the
# old code and nothing says so.
#
# This rebuilds EVERYTHING in dependency order and then VERIFIES what is running.
# It is slower than a targeted deploy. That is the trade: certainty over minutes.
#
# What it does, in order:
#   1. git safety + sync        — delegated to scripts/deploy.sh (no services),
#                                 which refuses off-main, mirrors an applied
#                                 config, rebases and pushes.
#   2. stocker-base             — forced rebuild. 17 service images are FROM it,
#                                 and its editable install caches shared/'s
#                                 module list, so a NEW shared file is invisible
#                                 until it is rebuilt.
#   3. both stacks              — via scripts/up.sh --build, which keeps the
#                                 in-flight guard (never recreate bt-engine
#                                 mid-sweep) and the independent-failure rule.
#   4. verification             — HEAD, container state, health, and a check
#                                 that the parity/coverage gates are actually
#                                 live rather than merely built.
#
# Usage: scripts/deploy-all.sh            deploy + verify
#        scripts/deploy-all.sh --force    also recreate the bt stack mid-job
#        scripts/deploy-all.sh --verify   verify only, change nothing
set -uo pipefail          # NOT -e: a failure in one stage must still report
cd "$(dirname "${BASH_SOURCE[0]}")/.."

FORCE=0
VERIFY_ONLY=0
for a in "$@"; do
    case "$a" in
        --force|-f)  FORCE=1 ;;
        --verify)    VERIFY_ONLY=1 ;;
        *) echo "unknown argument: $a"
           echo "usage: scripts/deploy-all.sh [--force] [--verify]"; exit 2 ;;
    esac
done

rc=0
hr() { printf '── %s %s\n' "$1" "$(printf '─%.0s' $(seq 1 $((66 - ${#1}))))"; }

if [ "$VERIFY_ONLY" -eq 0 ]; then
    hr "1/4  git sync"
    # deploy.sh with NO service arguments does the git steps only and prints a
    # hint instead of building — exactly the half we want here.
    if ! scripts/deploy.sh; then
        echo "!! git sync failed — NOT deploying stale code on top of it"
        exit 1
    fi

    hr "2/4  stocker-base (forced)"
    # Unconditional, not the staleness heuristic up.sh uses: this command's
    # promise is "everything is current", and a base rebuild is a few minutes
    # against the cost of one service silently importing yesterday's shared/.
    if ! docker build --network host -t stocker-base:latest -f Dockerfile.base .; then
        echo "!! stocker-base build failed — every dependent build would fail too"
        exit 1
    fi

    hr "3/4  both stacks"
    if [ "$FORCE" -eq 1 ]; then
        scripts/up.sh --build --force || rc=$?
    else
        scripts/up.sh --build || rc=$?
    fi
fi

# ── 4. verification ──────────────────────────────────────────────────────────
# A deploy that "succeeded" and a system that is actually running the new code
# are different claims. Everything below checks the second one.
hr "4/4  verification"

echo "commit:  $(git log --oneline -1 2>/dev/null)"
echo

echo "live stack:"
docker compose ps --format '  {{.Name}}\t{{.State}}\t{{.Status}}' 2>/dev/null \
    || echo "  (could not read live stack state)"
echo
echo "backtest stack:"
docker compose -p stocker-bt -f docker-compose.backtest.yml ps \
    --format '  {{.Name}}\t{{.State}}\t{{.Status}}' 2>/dev/null \
    || echo "  (could not read backtest stack state)"
echo

# Any container not running/healthy is the thing you actually want to see.
bad="$( { docker compose ps --format '{{.Name}}\t{{.State}}';
          docker compose -p stocker-bt -f docker-compose.backtest.yml ps \
              --format '{{.Name}}\t{{.State}}'; } 2>/dev/null \
        | grep -vE '\t(running|exited)$' || true)"
if [ -n "$bad" ]; then
    echo "!! containers not in a good state:"
    printf '%s\n' "$bad" | sed 's/^/   /'
    rc=1
fi

echo "health:"
# Ports are asked of COMPOSE, never hardcoded. The first draft of this script
# hardcoded them and had five wrong (pipeline 8018 not 8003, evaluator 8014 not
# 8017, llm-vetter 8016 not 8005 …) — a health check that probes the wrong port
# reports a healthy service as down, or worse, a different service as healthy.
probe_stack() {   # probe_stack <label> [compose args...]
    local label="$1"; shift
    local svc host_port
    while read -r svc; do
        [ -n "$svc" ] || continue
        host_port="$(docker compose "$@" port "$svc" 8000 2>/dev/null | tail -1)"
        # No :8000 mapping = infrastructure (postgres, redis) or a run-once
        # container (db-migrator). Not a fault, nothing to probe.
        [ -n "$host_port" ] || continue
        if curl -sf --max-time 4 "http://${host_port/0.0.0.0/localhost}/health" >/dev/null 2>&1; then
            printf '  %-22s ok\n' "$svc"
        else
            printf '  %-22s NOT RESPONDING (%s)\n' "$svc" "$host_port"
            rc=1
        fi
    done < <(docker compose "$@" ps --services --filter status=running 2>/dev/null)
}
probe_stack live
probe_stack backtest -p stocker-bt -f docker-compose.backtest.yml
echo

# The gates are the whole point of this week's work, so verify they are LIVE
# rather than merely present in the image. A gate that built but is not enforcing
# looks identical to one that is, right up until it lets something through.
echo "gates:"
# NOT -f: --fail makes curl exit non-zero and print NOTHING on 4xx, so the 422
# this is looking for would be indistinguishable from the service being down.
gate_out="$(curl -s --max-time 10 -X POST http://localhost:8031/jobs/run \
    -H 'Content-Type: application/json' \
    -d '{"start_date":"2024-01-02","end_date":"2024-02-02"}' \
    -w '\n%{http_code}' 2>/dev/null || true)"
gate_code="$(printf '%s' "$gate_out" | tail -1)"
case "$gate_code" in
    422) echo "  bt-engine coverage/parity  ENFORCING (422 as expected — the active"
         echo "                             config weights earnings_surprise, which the"
         echo "                             corpus cannot compute)" ;;
    200|202) echo "  bt-engine coverage/parity  NOT enforcing — a run STARTED for a config"
             echo "                             it cannot faithfully score. Check"
             echo "                             BT_COVERAGE_ENFORCE / BT_PARITY_ENFORCE."
             rc=1 ;;
    409) echo "  bt-engine coverage/parity  (busy — a run is in flight, gate unverified)" ;;
    *)   echo "  bt-engine coverage/parity  unverified (HTTP '${gate_code:-none}')" ;;
esac

ver="$(docker compose -p stocker-bt -f docker-compose.backtest.yml exec -T bt-postgres \
        psql -U btuser -d backtest -tAq \
        -c "SELECT version::text FROM bt_data_version WHERE id=1" 2>/dev/null | tr -d '[:space:]')"
if [ -n "$ver" ]; then
    echo "  bt corpus version          ${ver}"
    echo "                             (the factor cache keys on this; a re-backfill"
    echo "                              must change it or the cache serves stale factors)"
else
    echo "  bt corpus version          ABSENT — bt-engine will DISABLE its factor cache"
    echo "                             (fail-closed). Run a bt-data job to stamp one."
fi

echo
if [ "$rc" -eq 0 ]; then
    hr "deploy verified"
else
    hr "deploy FINISHED WITH PROBLEMS (see above)"
fi
exit "$rc"
