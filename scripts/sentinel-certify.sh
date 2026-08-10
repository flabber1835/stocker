#!/usr/bin/env bash
#
# Everything that must be true BEFORE a rehearsal is allowed to produce
# evidence, in the order it must be true in.
#
# The order is not arbitrary. Each step's premise is the previous step's
# conclusion:
#
#    1  build the pinned image        the environment must exist before it can
#                                     be named
#    2  name it                       `identity --require-certified` refuses if
#                                     the interpreter, any pin, or either source
#                                     tree cannot be pinned down
#    3  DISCARD the corpus            review #4 changed economically meaningful
#                                     data: every dividend in the old seed is
#                                     0.0 and every split ratio was inferred.
#                                     Re-seeding is not hygiene, it is the fix
#    4  re-seed                       hours
#    5  the suite, INSIDE the image   a green suite on the host says nothing
#                                     about the image that produces the evidence
#    6  readiness                     is the corpus usable at all
#    7  rejection audit               is THIS interval complete — fail closed
#    8  synthetic loader parity       do the two MAPPINGS agree
#    8b REAL-WINDOW corpus parity     do the SEEDED bars agree, on real splits,
#                                     delistings and restatements
#    9  record the identity           the corpus hash only exists once there is
#                                     a corpus
#
# It does NOT run the rehearsal. That is a three-hour job with its own
# supervision, and a script that ran it at the end of nine preconditions would
# be a script nobody reads the output of.
#
# Usage:
#   scripts/sentinel-certify.sh --start 2021-01-04 --end 2023-12-29
#   scripts/sentinel-certify.sh --start ... --end ... --keep-corpus
#   scripts/sentinel-certify.sh --start ... --end ... --verify-only
set -euo pipefail

COMPOSE="docker compose -f docker-compose.sentinel.yml"
RUN="${COMPOSE} run --rm -T sentinel"
START=""; END=""; KEEP=0; VERIFY_ONLY=0; SEED_FROM="1998-01-01"
ART="artifacts/sentinel"

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

# EVIDENCE GOES IN THE ARTIFACT DIRECTORY, not /tmp. A certification input that
# lives where the operating system may delete it is not retained evidence, and
# the whole batch is about being able to reproduce a verdict later.
mkdir -p "${ART}"
RUNSTAMP="${START}_${END}"

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
${RUN} identity --require-certified > "${ART}/identity-env.json" \
  || fail "the image is not the certified environment — pin drift, the wrong
  interpreter, or a source tree that could not be located. See
  ${ART}/identity-env.json"
python3 - "${ART}/identity-env.json" <<'PY' || fail "the identity record is incomplete"
import json, sys
env = json.load(open(sys.argv[1]))["environment"]
for k in ("sentinel_source", "wealth_core_source"):
    if not env[k]["hash"]:
        sys.exit(f"{k} has no hash — the record cannot name the code it ran")
print(f"  python {env['python']}  calendar {env['calendar_version']}")
print(f"  sentinel   {env['sentinel_source']['hash'][:16]} "
      f"({env['sentinel_source']['files']} files)")
print(f"  wealthcore {env['wealth_core_source']['hash'][:16]} "
      f"({env['wealth_core_source']['files']} files)")
PY

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
  # FAIL CLOSED. The previous version ended in `|| echo "(tables absent)"`,
  # which read a permission error, a connection failure or a typo as "there was
  # nothing to delete" — and the seed then UPSERTS, so obsolete rows survive
  # into a corpus everyone believes is fresh. Table existence is handled by
  # `to_regclass` INSIDE the statement; every other error terminates the run.
  ${COMPOSE} exec -T sentinel-postgres \
    psql -U sentinel -d sentinel -v ON_ERROR_STOP=1 <<'SQL' || fail "the corpus could not be discarded — NOT proceeding, because the seed upserts and stale rows would survive into a corpus believed to be fresh"
DO $$
DECLARE t text;
BEGIN
  FOREACH t IN ARRAY ARRAY['sentinel_bars','sentinel_actions',
                           'sentinel_universe','sentinel_ingest_rejections',
                           'sentinel_rejection_truncation',
                           'sentinel_corpus_anomalies','feed_ingest_runs']
  LOOP
    IF to_regclass(t) IS NOT NULL THEN
      EXECUTE format('TRUNCATE TABLE %I', t);
      RAISE NOTICE 'truncated %', t;
    ELSE
      RAISE NOTICE 'absent (nothing to truncate): %', t;
    END IF;
  END LOOP;
END $$;
SQL

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
echo "${SUITE}" > "${ART}/suite-${RUNSTAMP}.txt"
[ "${SUITE_RC}" -eq 0 ] \
  || fail "the suite does not pass in the image that would produce the evidence"

# A SKIP is a failure HERE, and only here. Every Postgres-backed test in this
# suite skips itself when initdb/pg_ctl are missing, the pin tests skip outside
# the certified interpreter, and the runtime-artefact tests skip outside the
# image — so a test image without the Postgres binaries runs a green suite that
# exercised no database at all, and a suite that skipped its own certification
# assertions reports success for not having checked. On a developer's host those
# skips are correct; in the certified image there is nothing left to wait on.
if echo "${SUITE}" | grep -qE '[0-9]+ skipped'; then
  fail "tests SKIPPED inside the certified image (see the -rs reasons above).
  In this image nothing should be unavailable: a skip here means the suite did
  not exercise what it claims to. Do NOT accept it as a pass."
fi

# ── 6. readiness ─────────────────────────────────────────────────────────────
step "6/9  data-contract readiness"
${RUN} check-data | tee "${ART}/readiness-${RUNSTAMP}.txt" \
  || fail "the corpus cannot support a Wealth Core bootstrap"

# ── 7. is THIS interval complete ─────────────────────────────────────────────
step "7/9  refused rows over ${START}..${END} — fail closed"
# --assert-no-holdings is EXPLICIT, and it is a real claim: this runs BEFORE the
# first bootstrap, so the book genuinely is empty. Supplying nothing would mean
# UNKNOWN, and the audit would return UNDETERMINED for every ticker rather than
# quietly assuming an empty intersection — which is precisely the defect this
# flag exists to make impossible to reintroduce.
#
# AFTER the rehearsal, re-run this with the realised book:
#   sentinel rejection-audit --start ... --end ... --book artifacts/.../book.json
${RUN} rejection-audit --start "${START}" --end "${END}" --assert-no-holdings \
  > "${ART}/rejection-audit-${RUNSTAMP}.json" \
  || fail "refused price rows in the interval are unexplained. Read
  ${ART}/rejection-audit-${RUNSTAMP}.json: every ticker under 'material' and
  'undetermined', every entry under 'truncated_evidence' and every
  'gating_anomalies' row needs an answer before this replay is evidence. Do NOT
  relax the audit to clear it."

# ── 8. loader parity, both kinds ─────────────────────────────────────────────
step "8/9  Sentinel loader vs the canonical Wealth Core data path (synthetic)"
docker run --rm sentinel-test:latest tests/sentinel/test_loader_parity.py -q \
  || fail "Sentinel's bars differ from the canonical path's — the engine is
  certified, what is handed to it is not"

step "8b/9 the SEEDED corpus vs the canonical corpus, over the real window"
# The synthetic test proves the two MAPPINGS agree on rows both were handed.
# This proves the bars actually seeded for the interval agree — real splits,
# ticker reuse, delistings mid-window, restatements. ACTIONS authority and
# `tradeable` both changed in this batch, so this is where that shows up.
#
# An unreadable canonical corpus is NOT a pass; the tool says so and exits 2.
docker run --rm --network host --entrypoint python \
  -e SENTINEL_DATABASE_URL="${SENTINEL_DATABASE_URL:-postgresql://sentinel:${SENTINEL_POSTGRES_PASSWORD:-sentinel}@127.0.0.1:5435/sentinel}" \
  -e BT_DATABASE_URL="${BT_DATABASE_URL:-}" \
  sentinel-test:latest -m tools.corpus_parity \
  --start "${START}" --end "${END}" \
  > "${ART}/corpus-parity-${RUNSTAMP}.json" \
  || fail "the seeded corpus does not match the canonical Wealth Core corpus,
  or the comparison could not be run at all. Read
  ${ART}/corpus-parity-${RUNSTAMP}.json — membership differences FIRST, then
  split_ratio, then dividends. If BT_DATABASE_URL is unset, set it: not having
  run this check is not the same as passing it."

# ── 9. the record ────────────────────────────────────────────────────────────
step "9/9  recording the rehearsal identity"
${RUN} identity --require-certified --start "${START}" --end "${END}" \
  > "${ART}/identity-${RUNSTAMP}.json" \
  || fail "the identity record could not be produced"
python3 - "${ART}/identity-${RUNSTAMP}.json" <<'PY'
import json, sys
rec = json.load(open(sys.argv[1]))
c = rec.get("corpus", {})
print(f"  identity_hash : {rec['identity_hash']}")
print(f"  corpus_hash   : {c.get('corpus_hash')}")
print(f"  postgres      : {c.get('postgres_server_version')} "
      f"(certified={c.get('postgres_certified')})")
print(f"  sessions      : {c.get('sessions')}  securities: {c.get('securities')}")
if c.get("postgres_certified") is False:
    print("  WARNING: the database server is not the pinned one; the corpus "
          "digests were produced by a different Postgres than the record "
          "claims")
PY

printf '\n\033[32mREADY FOR THE REHEARSAL\033[0m — %s..%s\n' "${START}" "${END}"
echo "  evidence retained in ${ART}/ :"
ls -1 "${ART}" | sed 's/^/    /'
echo
echo "The rehearsal itself is NOT run here. Start it deliberately, and read the"
echo "settlement counters and the per-episode terminal audit before any"
echo "performance number — a CAGR without them cannot say how much of the book"
echo "was valued rather than realised."
echo
echo "AFTER it completes, re-run the rejection audit with the REALISED book:"
echo "  sentinel rejection-audit --start ${START} --end ${END} --book <book.json>"
echo "The pre-seed run asserted an empty book, which was true then and is not"
echo "true of the interval the rehearsal actually traded."
