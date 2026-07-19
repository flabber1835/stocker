#!/usr/bin/env bash
# run-tests.sh — run EVERY test suite, each in its OWN pytest process.
#
# Why not one big `pytest tests/`: every service ships a top-level package
# named `app`, and the per-suite conftests swap sys.path + purge sys.modules
# to point `app` at their service. Within one process that is inherently
# order-dependent (audit finding #7) — cross-suite runs intermittently import
# the WRONG service's `app`. Until packages are renamed (planned with the
# modular-monolith restructuring), process-per-suite is the reliable contract:
# each suite gets a clean interpreter, so `make test` green means every suite
# is green in isolation — the same way CI and this repo's docs run them.
#
# Usage: scripts/run-tests.sh [pytest-args...]
#   e.g. scripts/run-tests.sh -q       (default)
#        scripts/run-tests.sh -x -k sector
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
ARGS=("${@:--q}")

# tests/harness is the docker-compose black-box overlay (needs the stack up);
# everything else must pass on a bare runner (DB-needing suites skip cleanly).
# tests/integration runs PER FILE: its files bootstrap DIFFERENT services'
# `app` packages and are not in the root conftest's service map, so they
# collide with each other inside one process.
mapfile -t SUITES < <(find tests -mindepth 1 -maxdepth 1 -type d \
    ! -name harness ! -name __pycache__ ! -name integration | sort)
mapfile -t -O "${#SUITES[@]}" SUITES < <(find tests/integration -maxdepth 1 \
    -name 'test_*.py' | sort)
# Top-level test modules (tests/test_*.py) run as one extra suite.
SUITES+=("tests/test_compose.py")

pass=0; fail=0; failed_suites=()
for suite in "${SUITES[@]}"; do
    printf '── %s ' "$suite"
    out=$(python -m pytest "$suite" "${ARGS[@]}" 2>&1); rc=$?
    tail_line=$(printf '%s\n' "$out" | tail -1)
    if [ "$rc" -eq 0 ] || [ "$rc" -eq 5 ]; then          # 5 = nothing collected
        printf '✓ %s\n' "$tail_line"
        pass=$((pass + 1))
    else
        printf '✗ FAILED\n%s\n' "$out"
        fail=$((fail + 1)); failed_suites+=("$suite")
    fi
done

echo
echo "════ ${pass} suite(s) passed, ${fail} failed ════"
if [ "$fail" -gt 0 ]; then
    printf 'failed: %s\n' "${failed_suites[@]}"
    exit 1
fi
