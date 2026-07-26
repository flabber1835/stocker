#!/usr/bin/env bash
# up.sh — bring up BOTH stacks (live + backtest) with one command.
#
# The stacks are deliberately SEPARATE compose projects (own bt-postgres, own
# namespace): a live `up -d --build` must never recreate backtest containers
# mid-backfill/backtest, and merging projects would re-prefix the bt data
# volume (the 35M-row corpus would mount as empty). This wrapper gives the
# one-command experience without those risks.
#
# INDEPENDENCE IS THE POINT: a failure in one stack must NOT stop the other
# from coming up (an llm-gateway build error once aborted the script before the
# backtest stack was touched). Each stack is attempted, both results are
# reported, and the script exits non-zero only at the very end.
#
# IN-FLIGHT GUARD (the same one down.sh has): recreating bt-engine while a sweep
# runs does NOT just pause it — bt-engine marks every `running` bt_sweeps row
# 'RESTART_ABORTED: engine restarted mid-sweep' on ITS OWN STARTUP. So a deploy
# during an experiment silently destroys it. That is exactly what happened on
# 2026-07-23/24/25: three consecutive nightly baselines aborted, no candidate was
# ever validated, and the weekly review reported the lane as non-functional for a
# 4th week. up.sh had no guard while down.sh did — a deploy was the one path that
# could kill a job without warning. The LIVE stack still comes up either way.
#
# Usage: scripts/up.sh            (both stacks, no rebuild)
#        scripts/up.sh --build    (both stacks, rebuild changed images)
#        scripts/up.sh --force    (recreate the bt stack even mid-job)
set -uo pipefail          # deliberately NOT -e: see above
cd "$(dirname "${BASH_SOURCE[0]}")/.."

ARGS=()
FORCE=0
SERIAL=0
for a in "$@"; do
    case "$a" in
        --build)      ARGS+=(--build) ;;
        --force|-f)   FORCE=1 ;;
        --serial|-s)  SERIAL=1 ;;
        *) echo "unknown argument: $a"
           echo "usage: scripts/up.sh [--build] [--force] [--serial]"; exit 2 ;;
    esac
done

# SERIAL builds, one image at a time. Compose hands every service to BuildKit at
# once; on a NAS that means ~17 concurrent pip installs and layer exports
# competing for the same spindle, and the symptom is not a clear out-of-resources
# error but this:
#     => [scheduler internal] load .dockerignore    15.5s
#     failed to solve: DeadlineExceeded: context deadline exceeded
# A 400-byte .dockerignore taking 15 seconds is IO starvation, and BuildKit's
# internal deadline fires before anything useful happens. Serial is slower in
# wall-clock but finishes, which parallel does not.
build_serially() {   # build_serially [compose args...]
    local svc rc=0
    while read -r svc; do
        [ -n "$svc" ] || continue
        echo "── building $svc ─────────────────────────────────"
        docker compose "$@" build "$svc" || { echo "!! $svc build FAILED"; rc=1; }
    done < <(docker compose "$@" config --services 2>/dev/null)
    return "$rc"
}

bt_busy=""
if [ "$FORCE" -eq 0 ]; then
    if curl -sf --max-time 5 http://localhost:8030/runs/latest 2>/dev/null \
         | grep -q '"status":[[:space:]]*"running"'; then
        bt_busy="a bt-data fetch (backfill/topup)"
    fi
    if curl -sf --max-time 5 http://localhost:8031/sweeps/latest 2>/dev/null \
         | grep -q '"status":[[:space:]]*"running"'; then
        bt_busy="${bt_busy:+$bt_busy and }a bt-engine sweep/experiment"
    fi
fi

# 17 of the service images are `FROM stocker-base:latest` — a LOCALLY built
# image that compose never builds for you.
#
# MISSING is the obvious failure (fresh host, after a prune): every dependent
# build fails, which reads as a random service error.
#
# STALE is the subtle one, and it has bitten twice. The base carries the
# editable install of shared/, which CACHES THE MODULE FILE LIST — so a NEW file
# under shared/ (parity.py, wealth.py, …) is invisible to every service until
# the base is rebuilt. The backtest stack has no bind-mount override, so its
# services import the BAKED copy and crash-loop on the missing import. Rebuilding
# only when the image is absent never caught this, and "remember to rebuild the
# base" is not a control.
#
# Rule: rebuild when the image is older than the newest file under shared/. A
# git pull restamps mtimes, so this errs toward rebuilding after any sync —
# cheap, and the failure it prevents is a crash-looping service.
base_needs_build=0
if ! docker image inspect stocker-base:latest >/dev/null 2>&1; then
    base_needs_build=1
    echo "── stocker-base:latest missing — building it first ─────────"
else
    img_epoch="$(docker image inspect stocker-base:latest \
        --format '{{.Created}}' 2>/dev/null | cut -c1-19)"
    img_ts="$(date -d "${img_epoch/T/ }" +%s 2>/dev/null || echo 0)"
    newest_shared="$(find shared -type f -newermt "@${img_ts}" -print -quit 2>/dev/null || true)"
    if [ "$img_ts" = "0" ] || [ -n "$newest_shared" ]; then
        base_needs_build=1
        echo "── stocker-base:latest is STALE vs shared/ — rebuilding ────"
        [ -n "$newest_shared" ] && echo "   (newer than the image: $newest_shared)"
    fi
fi
if [ "$base_needs_build" -eq 1 ]; then
    if ! docker build --network host -t stocker-base:latest -f Dockerfile.base .; then
        echo "!! could not build stocker-base — every service build will fail"
        exit 1
    fi
fi

live_rc=0
bt_rc=0
bt_skipped=0

echo "── live stack ──────────────────────────────────────────────"
if [ "$SERIAL" -eq 1 ] && [ "${#ARGS[@]}" -gt 0 ]; then
    build_serially || live_rc=$?
    docker compose up -d || live_rc=$?
else
    docker compose up -d "${ARGS[@]}" || live_rc=$?
fi
[ "$live_rc" -ne 0 ] && echo "!! live stack FAILED (rc=$live_rc) — continuing to the backtest stack"

echo
echo "── backtest stack ──────────────────────────────────────────"
if [ -n "$bt_busy" ]; then
    # SKIPPED, not failed: the live stack is deployed and the running job keeps
    # its slot. Recreating bt-engine here would mark the sweep RESTART_ABORTED.
    echo "SKIPPED: $bt_busy is RUNNING."
    echo "  Recreating bt-engine now would abort it (bt-engine marks every"
    echo "  'running' sweep RESTART_ABORTED on its own startup) — three nightly"
    echo "  baselines were lost that way on 2026-07-23/24/25."
    echo "  The live stack above IS deployed. Re-run once the job finishes:"
    echo "      scripts/up.sh${ARGS[*]:+ ${ARGS[*]}}"
    echo "  or override deliberately:"
    echo "      scripts/up.sh${ARGS[*]:+ ${ARGS[*]}} --force"
    bt_skipped=1
else
    if [ "$SERIAL" -eq 1 ] && [ "${#ARGS[@]}" -gt 0 ]; then
        build_serially -f docker-compose.backtest.yml || bt_rc=$?
        docker compose -f docker-compose.backtest.yml up -d || bt_rc=$?
    else
        docker compose -f docker-compose.backtest.yml up -d "${ARGS[@]}" || bt_rc=$?
    fi
    [ "$bt_rc" -ne 0 ] && echo "!! backtest stack FAILED (rc=$bt_rc)"
fi

# Plain `ps` (default table): --format Go templates with \t are not parsed by
# every compose version on the NAS, and a cosmetic status print must never make
# the deploy look failed.
echo
echo "── status: live ──"
docker compose ps || true
echo "── status: backtest ──"
docker compose -f docker-compose.backtest.yml ps || true

echo
if [ "$live_rc" -eq 0 ] && [ "$bt_rc" -eq 0 ]; then
    if [ "$bt_skipped" -eq 1 ]; then
        echo "✓ live stack up · backtest stack SKIPPED (job in flight — see above)"
    else
        echo "✓ both stacks up"
    fi
    exit 0
fi
echo "✗ live=$( [ "$live_rc" -eq 0 ] && echo ok || echo FAILED ) " \
     "backtest=$( [ "$bt_rc" -eq 0 ] && echo ok || echo FAILED )"
echo "  If a build died with 'DeadlineExceeded: context deadline exceeded',"
echo "  that is IO starvation from ~17 parallel builds, not a code error —"
echo "  retry one image at a time:"
echo "      scripts/up.sh --build --serial"
echo "  Re-run a single stack to see the full build log, e.g.:"
echo "    docker compose up -d --build llm-gateway"
exit 1
