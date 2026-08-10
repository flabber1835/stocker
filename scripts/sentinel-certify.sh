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
#   2b  REQUIRE the closure lock      and STOP if it is missing. Ahead of the
#                                     truncate on purpose: an unlocked image is
#                                     not reproducible, and letting one wipe and
#                                     re-seed spends hours producing evidence
#                                     nobody can rebuild the environment for
#   2c  the ENGINE carries the same   bt-engine runs the rehearsal; a stale
#       Wealth Core                   base would surface only after the seed
#                                     and three hours of simulation
#   2d  record the ARTEFACT identity  the image ids, from the HOST — a container
#                                     cannot discover its own image
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
  # STOCKER-BASE FIRST, UNCONDITIONALLY. `services/bt-engine/Dockerfile` begins
  # `FROM stocker-base:latest`, which is a MUTABLE tag holding the `shared/`
  # package — including Wealth Core. Building bt-engine without rebuilding it
  # layers a fresh engine on whatever base happens to be lying around: on one
  # machine yesterday's, on a clean machine nothing at all.
  #
  # The rehearsal WOULD eventually expose that as a Wealth Core source-hash
  # mismatch — after the corpus seed and three hours of simulation. This is the
  # stale-base trap the deploy scripts already carry a forced rebuild for, and
  # it belongs here for the same reason: the editable install caches the module
  # list, so a new shared file is invisible until the base is rebuilt.
  #
  # It is a `docker build`. It starts no service and revives nothing.
  docker build --network host -t stocker-base:latest -f Dockerfile.base .

  # BT-ENGINE IS BUILT HERE TOO, and deliberately NOT started. The manifest has
  # to name the engine that will run the rehearsal BEFORE it runs one —
  # comparing the run against whatever the tag points at during finalization
  # accepts any correctly self-identifying artefact that happens to run
  # afterwards, including one built from loader source that changed after the
  # freeze. Starting it is `scripts/bt-engine-up.sh`'s job; a recording step
  # does not get to bring a service up.
  docker compose -f docker-compose.backtest.yml build bt-engine
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

# ── 2b. THE CLOSURE LOCK, AHEAD OF ANYTHING DESTRUCTIVE ──────────────────────
# This used to sit at the END, as a yellow warning, after the truncate and the
# hours-long re-seed and immediately before "READY FOR THE REHEARSAL". That is
# exactly backwards: an unlocked build is not reproducible, so it would have
# destroyed a corpus and spent hours rebuilding one in order to produce evidence
# nobody could ever rebuild the environment for. A refusal is only a refusal if
# it comes before the irreversible step.
step "2b/9 the dependency closure must be LOCKED"
CLOSURE=$(python3 -c "import json; print(json.load(open('${ART}/identity-env.json'))['environment']['distributions_hash'])")
IMAGE_LOCK=$(python3 -c "import json; print(json.load(open('${ART}/identity-env.json'))['environment'].get('image_lock_sha256') or '')")
BOOT="${ART}/bootstrap_closure.txt"

if [ ! -f sentinel/requirements.lock ]; then
  # RECORD THE BOOTSTRAP CLOSURE BEFORE EXITING. Without this the first
  # unlocked build leaves nothing behind, and the locked rebuild has no earlier
  # value to be compared against — so the very comparison the bootstrap exists
  # to perform would be skipped on the one run that needed it.
  printf '%s' "${CLOSURE}" > "${BOOT}"
  printf '\n\033[31mSTOP — NO DEPENDENCY LOCK. NOTHING HAS BEEN DESTROYED.\033[0m\n' >&2
  cat >&2 <<EOF

  sentinel/requirements.txt pins the DIRECT dependencies; pip resolved the
  transitive closure freely for this build. identity_hash still separates two
  different closures — they can never be mistaken for one — but you cannot
  REBUILD this one, and a rehearsal whose environment cannot be rebuilt is not
  certification evidence.

  The bootstrap closure has been recorded:
    ${CLOSURE}
    -> ${BOOT}

  This is the EXPECTED state on the first 3.12.13 build. Finish the bootstrap:

    scripts/sentinel-lock.sh                       # read the closure OUT of it
    git add sentinel/requirements.lock && git commit
    scripts/sentinel-certify.sh --start ${START} --end ${END} --keep-corpus

  Note the REBUILD: --verify-only does NOT rebuild the image, so it would check
  a lock that exists in the checkout against an image that never consumed one.
  The rebuild is where the lock proves itself, and this script then compares the
  closure against the recorded bootstrap value automatically.

EOF
  exit 1
fi

# THE IMAGE MUST HAVE BEEN BUILT FROM THIS LOCK, not merely coexist with it.
# `image_lock_sha256` is the digest of the lock file baked into the image at
# /tmp/req. Without this check an OLD UNLOCKED image passes the moment a lock
# appears on the host — which proves the generator was run, not that anything
# consumed its output.
LOCK_SHA=$(sha256sum sentinel/requirements.lock | cut -d' ' -f1)
if [ -z "${IMAGE_LOCK}" ]; then
  fail "the image carries NO lock file, but sentinel/requirements.lock exists in
  the checkout. This image was built before the lock, or without it. REBUILD:
    ${COMPOSE} build sentinel sentinel-panel
  A lock in the working tree says nothing about the image that will run."
fi
if [ "${IMAGE_LOCK}" != "${LOCK_SHA}" ]; then
  fail "the image was built from a DIFFERENT lock than the checkout holds.
  image   : ${IMAGE_LOCK}
  checkout: ${LOCK_SHA}
  Rebuild, or work out which one is the intended closure. Do not proceed with an
  artefact whose declared dependencies are not the ones it contains."
fi
echo "  image built from the checkout lock: ${LOCK_SHA}"

# AND THE CLOSURE MUST NOT HAVE MOVED. Compared against the bootstrap value
# where one exists — that is the proof the lock DESCRIBES the image it came
# from — and against the previous certified run otherwise.
PREV="${ART}/distributions_hash.prev"
BASELINE=""
BASELINE_KIND=""
if [ -f "${BOOT}" ]; then
  BASELINE=$(cat "${BOOT}"); BASELINE_KIND="the unlocked bootstrap build"
elif [ -f "${PREV}" ]; then
  BASELINE=$(cat "${PREV}"); BASELINE_KIND="the previous certified run"
fi
if [ -n "${BASELINE}" ]; then
  if [ "${BASELINE}" != "${CLOSURE}" ]; then
    fail "the dependency closure MOVED against ${BASELINE_KIND}.
  before: ${BASELINE}
  after : ${CLOSURE}
  Something in the closure is not described by sentinel/requirements.lock. Do
  NOT edit the lock to agree — find what moved. Compare the 'distributions'
  list in ${ART}/identity-env.json against the lock."
  fi
  echo "  closure UNCHANGED against ${BASELINE_KIND}: ${CLOSURE}"
  # The bootstrap has served its purpose: the locked rebuild reproduced it.
  # Retired so a later legitimate dependency change is compared against the
  # last CERTIFIED run rather than against a build from before the lock existed.
  [ -f "${BOOT}" ] && mv "${BOOT}" "${BOOT}.proven"
else
  echo "  closure recorded for the first time: ${CLOSURE}"
  echo "  (a later run compares against it and refuses if it moved)"
fi
printf '%s' "${CLOSURE}" > "${PREV}"

# ── 2c. THE ENGINE CARRIES THE CERTIFIED WEALTH CORE ─────────────────────────
# Checked BEFORE anything is destroyed. The forced stocker-base rebuild above
# establishes the intended provenance; this proves the resulting artefact
# actually contains it. Defence in depth, because the two fail differently: a
# skipped rebuild is an operator mistake, a mismatched result is a build that
# did not do what it was told.
#
# The rehearsal would eventually expose a stale Wealth Core as a source-hash
# mismatch — after the corpus seed and three hours of simulation. Here it costs
# one container start.
step "2c/9 the engine carries the certified Wealth Core"
# ONE RESOLVER, shared with the launcher, so the two cannot form different
# opinions about which artefact they mean. It ASKS COMPOSE rather than guessing:
# the previous inference appended the service name to the DIRECTORY basename,
# while Compose uses the file's top-level `name:` — `stocker-bt-bt-engine`, not
# `stocker-bt-engine`. Close enough to read as a typo, different enough never
# to resolve.
BT_REF=$(python3 scripts/compose_image.py \
  --file docker-compose.backtest.yml --service bt-engine) \
  || fail "the bt-engine image could not be resolved from its compose file.
  NOT guessed: a wrong image name that resolves is worse than one that does
  not, because the record would then name an artefact nobody ran."
echo "  bt-engine image: ${BT_REF}"

BT_WC=$(docker run --rm --entrypoint python "${BT_REF}" -c \
  "from stock_strategy_shared import identity_hashes as i; print(i.wealth_core_source_hash())" \
  2>/dev/null || true)
SENTINEL_WC=$(python3 -c "import json; print(json.load(open('${ART}/identity-env.json'))['environment']['wealth_core_source']['hash'])")
if [ -z "${BT_WC}" ] || [ "${BT_WC}" = "None" ]; then
  fail "the bt-engine image ${BT_REF} could not report a Wealth Core source
  hash. It runs the three-hour rehearsal; an engine that cannot name the engine
  source it carries cannot produce certification evidence."
fi
if [ "${BT_WC}" != "${SENTINEL_WC}" ]; then
  fail "bt-engine carries Wealth Core ${BT_WC} and the certified Sentinel image
  carries ${SENTINEL_WC}. The rehearsal would run different economics than the
  image being certified. Rebuild both:
    docker build --network host -t stocker-base:latest -f Dockerfile.base .
    docker compose -f docker-compose.backtest.yml build bt-engine"
fi
echo "  both carry Wealth Core ${BT_WC}"

# ── 2d. THE ARTEFACT'S OWN IDENTITY, from the HOST ───────────────────────────
# `sentinel identity` describes the environment INSIDE the container: the
# interpreter, the packages, the source. It cannot describe the IMAGE — a
# container has no reliable way to discover the id of the image it is running —
# and the image is the thing actually being certified. So the manifest is
# assembled out here, where docker can answer.
#
# FAIL CLOSED on every image it names. PostgreSQL in particular PRODUCES the
# corpus being certified, and an unresolved or locally-tagged `postgres:16`
# would leave the record naming the wrong server, or nothing at all.
step "2d/9 recording the artefact identity"
PG_REF=$(python3 -c "
import re,sys
t=open('docker-compose.sentinel.yml').read()
m=re.search(r'image:\s*(postgres:[^\s]+)', t)
sys.stdout.write(m.group(1) if m else '')")
[ -n "${PG_REF}" ] || fail "no pinned postgres image found in docker-compose.sentinel.yml"
# Non-destructive: pull the pinned digest so it is resolvable locally BEFORE the
# manifest reads it. `up -d` would also do it, and starting a database is not
# something a recording step should decide to do.
docker image inspect "${PG_REF}" >/dev/null 2>&1 || docker pull "${PG_REF}" >/dev/null \
  || fail "the pinned Postgres image ${PG_REF} could not be resolved. It PRODUCES
  the corpus being certified; a record that cannot name it is not a record."

python3 scripts/sentinel_manifest.py "${ART}" "${RUNSTAMP}" "${LOCK_SHA}" \
  --postgres-ref "${PG_REF}" --bt-engine-ref "${BT_REF}" --require-images \
  || fail "the artefact manifest is incomplete — every image it names must
  resolve, and the source tree must be clean, BEFORE anything is destroyed."

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
# AFTER the rehearsal, re-run this with the book the RUN ITSELF emitted:
#   sentinel rejection-audit --start ... --end ... --book <book.json>
# `sentinel.core.book_artifact.write()` produces that file from the RunResult —
# no human retypes a ticker list into the evidentiary chain, where a typo would
# not error but would produce a CLEAN certification.
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
#
# THE DEFAULT DSN MIRRORS THE SENTINEL ONE ABOVE, and the `+psycopg` is not
# decoration. The canonical side goes through SQLAlchemy, and a bare
# `postgresql://` selects psycopg2 — which is NOT in the closure (the lock
# carries psycopg 3 only), so it fails as `No module named 'psycopg2'` wrapped
# in "the canonical corpus could not be read", one indirection away from the
# actual cause. 5434 is bt-postgres's PUBLISHED host port and `--network host`
# is what makes 127.0.0.1 reach it: no shared docker network, so Sentinel's
# isolation from the retired stack is unchanged — this reads a database, it
# does not depend on a Stocker service.
#
# Overridable, because a default is a convenience and not a claim about where
# the corpus is.
docker run --rm --network host --entrypoint python \
  -e SENTINEL_DATABASE_URL="${SENTINEL_DATABASE_URL:-postgresql://sentinel:${SENTINEL_POSTGRES_PASSWORD:-sentinel}@127.0.0.1:5435/sentinel}" \
  -e BT_DATABASE_URL="${BT_DATABASE_URL:-postgresql+psycopg://btuser:${BT_POSTGRES_PASSWORD:-btpass}@127.0.0.1:5434/backtest}" \
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

# The manifest is COMPLETED here, not written twice: the corpus hash cannot
# exist before there is a corpus, and a record that silently lacked it would be
# indistinguishable from one for an interval with no data.
python3 - "${ART}" "${RUNSTAMP}" <<'PYX' || fail "the manifest could not be completed"
import hashlib, json, sys
from pathlib import Path
art, stamp = Path(sys.argv[1]), sys.argv[2]
mp = art / f"manifest-{stamp}.json"
m = json.loads(mp.read_text())
rec = json.loads((art / f"identity-{stamp}.json").read_text())
m["corpus_hash"] = rec.get("corpus", {}).get("corpus_hash")
m["postgres_server_version"] = rec.get("corpus", {}).get("postgres_server_version")
ra = art / f"rejection-audit-{stamp}.json"
if ra.exists():
    m["rejection_audit_sha256"] = hashlib.sha256(ra.read_bytes()).hexdigest()
mp.write_text(json.dumps(m, indent=2, sort_keys=True))
print(f"  corpus_hash {m['corpus_hash']}")
print(f"  -> {mp}")
PYX

printf '\n\033[32mREADY FOR THE REHEARSAL\033[0m — %s..%s\n' "${START}" "${END}"
echo "  evidence retained in ${ART}/ :"
ls -1 "${ART}" | sed 's/^/    /'
echo
echo "The rehearsal itself is NOT run here. Start it deliberately, and read the"
echo "settlement counters and the per-episode terminal audit before any"
echo "performance number — a CAGR without them cannot say how much of the book"
echo "was valued rather than realised."
echo
echo "AFTER it completes, run the finalizer — it extracts the book the RUN"
echo "emitted, re-runs the audit against it and closes the manifest:"
echo "  scripts/sentinel-finalize-rehearsal.sh --start ${START} --end ${END} \\"
echo "      --run-id <bt_wealth_core_runs.run_id>"
echo "The pre-seed audit asserted an EMPTY book. That was true then and is not"
echo "true of the interval the rehearsal actually traded, so the finalizer"
echo "re-runs it against the realised one."
