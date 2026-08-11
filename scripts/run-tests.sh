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
    -name 'test_*.py' 2>/dev/null | sort)
# Top-level test modules, DISCOVERED rather than named.
#
# This line used to be the literal `SUITES+=("tests/test_compose.py")`, and that
# file was deleted with the Stocker runtime. pytest then exited 4 — "file not
# found", which is neither 0 nor the 5 this loop forgives — so every run ended
# `1 suite failed` pointing at a file nobody could open. Two runs of that and the
# summary line stops being read at all, which is the real cost: a runner that is
# permanently red cannot answer "did I break anything", and every subsequent
# change is made without that answer. Same defect as the Makefile naming retired
# services, one layer further in.
mapfile -t -O "${#SUITES[@]}" SUITES < <(find tests -maxdepth 1 \
    -name 'test_*.py' | sort)

# ── suites that are red ON PURPOSE, each with a reason and an exit condition ──
#
# This list is a liability and is written to behave like one. It exists because
# the alternative is worse: a runner whose summary is permanently red cannot
# answer "did I break anything", and once nobody reads the summary a genuine
# regression arrives unnoticed. Distinguishing EXPECTED red from NEW red keeps
# that answer available.
#
# Two rules keep it from becoming a place where failures go to be forgotten:
#   1. every entry states WHAT is failing and WHAT ENDS IT, not just that it is
#      known — an entry nobody can close is an entry nobody will;
#   2. a suite listed here that PASSES is itself reported, so a stale entry is
#      surfaced by the next green run rather than surviving indefinitely.
declare -A KNOWN_RED=(
  [tests/wealth_core]="3 golden-fixture tests. The fixture is INTENTIONALLY UNPINNED while the terminal-audit re-pin is pending — see CLAUDE.md 'The \$283.04'. ENDS WHEN: the single authorised re-pin lands. Do NOT re-pin to make these green."
)

pass=0; fail=0; expected=0; failed_suites=(); stale=()
for suite in "${SUITES[@]}"; do
    printf '── %s ' "$suite"
    out=$(python -m pytest "$suite" "${ARGS[@]}" 2>&1); rc=$?
    tail_line=$(printf '%s\n' "$out" | tail -1)
    if [ "$rc" -eq 0 ] || [ "$rc" -eq 5 ]; then          # 5 = nothing collected
        printf '✓ %s\n' "$tail_line"
        pass=$((pass + 1))
        [ -n "${KNOWN_RED[$suite]:-}" ] && stale+=("$suite")
    elif [ -n "${KNOWN_RED[$suite]:-}" ]; then
        printf '✗ expected — %s\n' "$tail_line"
        expected=$((expected + 1))
    else
        printf '✗ FAILED\n%s\n' "$out"
        fail=$((fail + 1)); failed_suites+=("$suite")
    fi
done

echo
echo "════ ${pass} passed, ${expected} expected-red, ${fail} FAILED ════"
if [ "$expected" -gt 0 ]; then
    for s in "${!KNOWN_RED[@]}"; do
        printf 'expected-red  %s\n              %s\n' "$s" "${KNOWN_RED[$s]}"
    done
fi
if [ "${#stale[@]}" -gt 0 ]; then
    # A suite that was supposed to be red and is not. Reported LOUDLY: the entry
    # above is now a lie, and lies in a list like this are how the list stops
    # meaning anything.
    printf 'STALE known-red entry (this suite PASSED — delete its entry): %s\n' \
        "${stale[@]}"
    exit 1
fi
if [ "$fail" -gt 0 ]; then
    printf 'failed: %s\n' "${failed_suites[@]}"
    exit 1
fi
