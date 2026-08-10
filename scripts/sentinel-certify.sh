#!/usr/bin/env bash
#
# Everything that must be true BEFORE a rehearsal is allowed to produce
# evidence, in the order it must be true in.
#
# The order is not arbitrary. Each step's premise is the previous step's
# conclusion:
#
#   1  build the pinned image        the environment must exist before it can
#                                    be named
#   2  name it                       `identity --require-certified` refuses if
#                                    the interpreter or any pin drifted
#   3  DISCARD the corpus            review #4 changed economically meaningful
#                                    data: every dividend in the old seed is
#                                    0.0 and every split ratio was inferred.
#                                    Re-seeding is not hygiene, it is the fix
#   4  re-seed                       hours
#   5  the suite, INSIDE the image   a green suite on the host says nothing
#                                    about the image that produces the evidence
#   6  readiness                     is the corpus usable at all
#   7  rejection audit               is THIS interval complete — fail closed
#   8  loader parity                 do Sentinel's bars equal the canonical
#                                    Wealth Core path's, bar for bar
#   9  record the identity           the corpus hash only exists once there is
#                                    a corpus
#
# It does NOT run the rehearsal. That is a three-hour job with its own
# supervision, and a script that ran it at the end of nine preconditions would
# be a script nobody reads the output of.
#
# Usage:
#   scripts/sentinel-certify.sh --start 2021-01-04 --end 2023-12-29
#   scripts/sentinel-certify.sh --start ... --end ... --keep-corpus
#   scripts/sentinel-certify.sh --verify-only --start ... --end ...
set -euo pipefail

COMPOSE="docker compose -f docker-compose.sentinel.yml"
RUN="${COMPOSE} run --rm -T sentinel"
START=""; END=""; KEEP=0; VERIFY_ONLY=0; SEED_FROM="1998-01-01"

while [ $# -gt 0 ]; do
  case "$1" in
    --start) START="$2"; shift 2 ;;
    --end) END="$2"; shift 2 ;;
    --seed-from) SEED_FROM="$2"; shift 2 ;;
    --keep-corpus) KEEP=1; shift ;;
    --verify-only) VERIFY_ONLY=1; KEEP=1; shift ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[ -n "$START" ] && [ -n "$END" ] || { echo "--start and --end are required" >&2; exit 2; }

step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
fail() { printf '\n\033[31mCERTIFICATION BLOCKED: %s\033[0m\n' "$*" >&2; exit 1; }

# ── 1. the pinned image ──────────────────────────────────────────────────────
if [ "$VERIFY_ONLY" -eq 0 ]; then
  step "1/9  building the pinned image"
  # --pull is DELIBERATELY ABSENT. The base is pinned by digest, so there is
  # nothing to pull that would not already be that exact image; passing it
  # would only make a network hiccup look like a build failure.
  ${COMPOSE} build sentinel sentinel-panel
  docker build --network host -t sentinel-test:latest -f Dockerfile.sentinel-test .
fi

# ── 2. name the environment ──────────────────────────────────────────────────
step "2/9  naming the environment"
${RUN} identity --require-certified > /tmp/sentinel-identity-env.json \
  || fail "the image is not the certified environment — see the pin drift above"
echo "  identity_hash: $(python3 -c "import json;print(json.load(open('/tmp/sentinel-identity-env.json'))['identity_hash'])" 2>/dev/null || echo '?')"

# ── 3-4. the corpus ──────────────────────────────────────────────────────────
if [ "$KEEP" -eq 0 ]; then
  step "3/9  DISCARDING the corpus tables"
  echo "  Review #4 made ACTIONS authoritative for splits and dividends. Any"
  echo "  corpus seeded before it carries dividend_per_share = 0.0 everywhere"
  echo "  and split ratios inferred from prices. It is not repairable in place."
  # TRUNCATE, never `down --volumes`. The volume also holds the ownership log,
  # whose loss makes the next start liquidate a Sentinel-owned book.
  ${COMPOSE} up -d sentinel-postgres
  for _ in $(seq 1 60); do
    ${COMPOSE} exec -T sentinel-postgres pg_isready -U sentinel -h 127.0.0.1 \
      >/dev/null 2>&1 && break
    sleep 2
  done
  ${COMPOSE} exec -T sentinel-postgres psql -U sentinel -d sentinel -v ON_ERROR_STOP=1 -c \
    "TRUNCATE sentinel_bars, sentinel_actions, sentinel_universe,
              sentinel_ingest_rejections, feed_ingest_runs;" \
    || echo "  (tables absent — nothing to discard)"

  step "4/9  re-seeding from ${SEED_FROM} (hours — watch with \`feed-status\`)"
  ${RUN} feed-seed --date-from "${SEED_FROM}"
else
  step "3-4/9  keeping the existing corpus (--keep-corpus)"
fi

# ── 5. the suite, inside the image ───────────────────────────────────────────
step "5/9  the Sentinel suite, INSIDE the certified image"
set +e
SUITE=$(docker run --rm sentinel-test:latest tests/sentinel -q -rs 2>&1)
SUITE_RC=$?
set -e
echo "${SUITE}" | tail -25
[ "${SUITE_RC}" -eq 0 ] \
  || fail "the suite does not pass in the image that would produce the evidence"

# A SKIP is a failure HERE, and only here. Every Postgres-backed test in this
# suite skips itself when initdb/pg_ctl are missing, and the two pin tests skip
# outside the certified interpreter — so a test image without the Postgres
# binaries runs a green suite that exercised no database at all, and a suite
# that skipped its own certification assertions reports success for not having
# checked. On a developer's host those skips are correct; in the certified
# image there is nothing left for them to be waiting on.
if echo "${SUITE}" | grep -qE '[0-9]+ skipped'; then
  fail "tests SKIPPED inside the certified image (see the -rs reasons above).
  In this image nothing should be unavailable: a skip here means the suite did
  not exercise what it claims to. Do NOT accept it as a pass."
fi

# ── 6. readiness ─────────────────────────────────────────────────────────────
step "6/9  data-contract readiness"
${RUN} check-data || fail "the corpus cannot support a Wealth Core bootstrap"

# ── 7. is THIS interval complete ─────────────────────────────────────────────
step "7/9  refused rows over ${START}..${END} — fail closed"
${RUN} rejection-audit --start "${START}" --end "${END}" \
  > /tmp/sentinel-rejection-audit.json \
  || fail "refused price rows in the interval are unexplained. Read
  /tmp/sentinel-rejection-audit.json: every ticker under 'material' and
  'undetermined' needs an answer before this replay is evidence. Do NOT
  relax the audit to clear it."

# ── 8. loader parity ─────────────────────────────────────────────────────────
step "8/9  Sentinel loader vs the canonical Wealth Core data path"
docker run --rm sentinel-test:latest tests/sentinel/test_loader_parity.py -q \
  || fail "Sentinel's bars differ from the canonical path's — the engine is
  certified, what is handed to it is not"

# ── 9. the record ────────────────────────────────────────────────────────────
step "9/9  recording the rehearsal identity"
${RUN} identity --require-certified --start "${START}" --end "${END}" \
  > "artifacts/sentinel/identity-${START}_${END}.json" \
  || fail "the identity record could not be produced"

printf '\n\033[32mREADY FOR THE REHEARSAL\033[0m — %s..%s\n' "${START}" "${END}"
echo "  identity : artifacts/sentinel/identity-${START}_${END}.json"
echo "  refusals : /tmp/sentinel-rejection-audit.json"
echo
echo "The rehearsal itself is NOT run here. Start it deliberately, and read the"
echo "settlement counters and the per-episode terminal audit before any"
echo "performance number — a CAGR without them cannot say how much of the book"
echo "was valued rather than realised."
