#!/usr/bin/env bash
# Run each suite in its own pytest process. Service suites all expose a top-level
# `app` package, so a single interpreter makes import resolution order-dependent.
set -uo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
ARGS=("${@:--q}")

# Harness tests require a running Compose stack. Everything here must pass or
# skip cleanly on a bare test image. Integration modules are separate processes
# because each bootstraps a different service's `app` package.
mapfile -t CANDIDATE_DIRS < <(find tests -mindepth 1 -maxdepth 1 -type d \
  ! -name harness ! -name __pycache__ ! -name integration | sort)
SUITES=()
for candidate in "${CANDIDATE_DIRS[@]}"; do
  # Helper/fixture packages such as tests/support are not suites. Feeding one
  # to pytest returns exit 5, which the refusal below correctly treats as a
  # failure; discovery therefore admits a directory only when it contains at
  # least one test module somewhere beneath it.
  if find "$candidate" -type f -name 'test_*.py' -print -quit | grep -q .; then
    SUITES+=("$candidate")
  fi
done
mapfile -t -O "${#SUITES[@]}" SUITES < <(find tests/integration -maxdepth 1 \
  -name 'test_*.py' 2>/dev/null | sort)
mapfile -t -O "${#SUITES[@]}" SUITES < <(find tests -maxdepth 1 \
  -name 'test_*.py' | sort)

if [ "${#SUITES[@]}" -eq 0 ]; then
  echo "REFUSED: test discovery found no suites; nothing was validated" >&2
  exit 1
fi

# Expected failures belong on exact test nodes with strict xfail. A whole-suite
# allowlist can hide an unrelated regression; strict xfail also makes a stale
# XPASS fail until the marker is intentionally removed.
pass=0
fail=0
failed_suites=()
for suite in "${SUITES[@]}"; do
  printf -- '-- %s ' "$suite"
  out=$(python -m pytest "$suite" "${ARGS[@]}" 2>&1)
  rc=$?
  tail_line=$(printf '%s\n' "$out" | tail -1)
  if [ "$rc" -eq 0 ]; then
    printf 'PASS %s\n' "$tail_line"
    pass=$((pass + 1))
  else
    if [ "$rc" -eq 5 ]; then
      out="REFUSED: pytest collected no tests for ${suite}
${out}"
    fi
    printf 'FAILED\n%s\n' "$out"
    fail=$((fail + 1))
    failed_suites+=("$suite")
  fi
done

echo
echo "==== ${pass} passed, ${fail} FAILED ===="
if [ "$fail" -gt 0 ]; then
  printf 'failed: %s\n' "${failed_suites[@]}"
  exit 1
fi
