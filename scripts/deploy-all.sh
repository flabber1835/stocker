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

# `ps --format '{{.Name}}...'` (a Go template) is NOT accepted by every Compose
# build — on this NAS it errors, which printed "(could not read live stack
# state)" for BOTH stacks while up.sh's own plain `ps` above worked fine. Use
# the plain table, which every version supports.
echo "live stack:"
docker compose ps 2>/dev/null | sed 's/^/  /' || echo "  (could not read live stack state)"
echo
echo "backtest stack:"
docker compose -p stocker-bt -f docker-compose.backtest.yml ps 2>/dev/null \
    | sed 's/^/  /' || echo "  (could not read backtest stack state)"
echo

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
        # RETRY. A container that compose reports as Started can still be
        # `health: starting` — uvicorn needs a moment, and services with a DB
        # migration or a config load need several. The first version of this
        # probed once and reported api/scheduler/evaluator as NOT RESPONDING
        # seconds after they were created, which is a false alarm that trains
        # you to ignore the check.
        # 90s, not 30. A container recreated SECONDS before this runs is still
        # doing startup work — bt-engine's lifespan runs DDL and an orphan-run
        # reclaim against bt-postgres before it serves anything. 30s flagged a
        # 4-second-old bt-engine as down, which is the same false alarm the
        # single-shot version produced, just rarer. A service genuinely broken
        # will not come up in 90s either.
        ok=0
        for attempt in $(seq 1 30); do
            if curl -sf --max-time 4 "http://${host_port/0.0.0.0/localhost}/health" \
                 >/dev/null 2>&1; then ok=1; break; fi
            sleep 3
        done
        if [ "$ok" -eq 1 ]; then
            printf '  %-22s ok\n' "$svc"
        else
            printf '  %-22s NOT RESPONDING after 90s (%s)\n' "$svc" "$host_port"
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
# READ-ONLY. The first version POSTed a real /jobs/run and read the status code,
# which only worked while the active config was guaranteed to be REFUSED. Once
# SUE parity made it scorable, the same probe STARTED A BACKTEST — from
# `--verify`, whose entire contract is that it changes nothing. A gate you can
# only test by trying to trip it is not a gate you can safely monitor.
gate_json="$(curl -s --max-time 10 http://localhost:8031/gates/check 2>/dev/null || true)"
gate_get() { printf '%s' "$gate_json" \
    | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('$1',''))" 2>/dev/null; }
if [ -z "$gate_json" ]; then
    echo "  bt-engine gates            UNREACHABLE (/gates/check) — old image, or bt-engine down"
    rc=1
else
    cov_on="$(gate_get coverage_enforcing)"; par_on="$(gate_get parity_enforcing)"
    scorable="$(gate_get scorable)";         refuse="$(gate_get would_refuse)"
    if [ "$cov_on" = "True" ] && [ "$par_on" = "True" ]; then
        echo "  bt-engine gates            ENFORCING (coverage + parity)"
    else
        echo "  bt-engine gates            NOT fully enforcing — coverage=$cov_on parity=$par_on."
        echo "                             Check BT_COVERAGE_ENFORCE / BT_PARITY_ENFORCE."
        rc=1
    fi
    if [ "$scorable" = "True" ]; then
        echo "  active config              SCORABLE — the wind tunnel can run it"
    else
        echo "  active config              REFUSED by the gates (would_refuse=$refuse):"
        printf '%s' "$gate_json" | python3 -c "
import sys, json
d = json.load(sys.stdin)
for v in (d.get('coverage_violations') or []) + (d.get('parity_violations') or []):
    print('                             · ' + v[:150])
" 2>/dev/null
        # NOT an error. A refusal is the gate doing its job; it is a fact about
        # the config, not a fault in the deploy.
    fi
fi
echo

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
