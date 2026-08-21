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
#   scripts/sentinel-certify.sh --start ... --end ... --build-only
#   scripts/sentinel-certify.sh --start ... --end ... --push-only \
#     --runtime-repository REGISTRY/REPO --test-repository REGISTRY/REPO
#   scripts/sentinel-certify.sh --start ... --end ... --verify-only
set -euo pipefail

# THE RESOLVER decides the compose file. On a host with no CPU CFS quota the
# canonical one cannot start a container at all, and a certification that never
# got past `up` is not a certification. The capability verdict is recorded in
# the manifest, so the record says which limits were actually in force.
COMPOSE="bash $(dirname "$0")/sentinel-compose.sh --run"
RUN="${COMPOSE} run --rm -T sentinel"
HOST_PYTHON="${SENTINEL_HOST_PYTHON:-python3}"
START=""; END=""; KEEP=0; PHASE=""; SEED_FROM="1998-01-01"
RUNTIME_REPOSITORY=""; TEST_REPOSITORY=""
CERTIFIED_BASELINE=""; CLOSURE_TRANSITION=""
ART="artifacts/sentinel"

select_phase() {
  [ -z "${PHASE}" ] || {
    echo "choose exactly one of --build-only, --push-only, --verify-only" >&2
    exit 2
  }
  PHASE="$1"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --start) START="$2"; shift 2 ;;
    --end) END="$2"; shift 2 ;;
    --seed-from) SEED_FROM="$2"; shift 2 ;;
    --keep-corpus) KEEP=1; shift ;;
    --build-only) select_phase build; shift ;;
    --push-only) select_phase push; shift ;;
    --verify-only) select_phase verify; shift ;;
    --runtime-repository) RUNTIME_REPOSITORY="$2"; shift 2 ;;
    --test-repository) TEST_REPOSITORY="$2"; shift 2 ;;
    --certified-baseline) CERTIFIED_BASELINE="$2"; shift 2 ;;
    --closure-transition) CLOSURE_TRANSITION="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[ -n "$START" ] && [ -n "$END" ] || { echo "--start and --end are required" >&2; exit 2; }
[ -n "${PHASE}" ] || {
  echo "choose one phase: --build-only, --push-only, or --verify-only" >&2
  exit 2
}
if [ "${PHASE}" != "verify" ] && { [ "${KEEP}" -ne 0 ] || \
    [ -n "${CERTIFIED_BASELINE}" ] || [ -n "${CLOSURE_TRANSITION}" ]; }; then
  echo "corpus and closure options apply only to --verify-only" >&2
  exit 2
fi
if [ "${PHASE}" = "push" ]; then
  [ -n "${RUNTIME_REPOSITORY}" ] && [ -n "${TEST_REPOSITORY}" ] || {
    echo "--push-only requires both explicit image repositories" >&2
    exit 2
  }
elif [ -n "${RUNTIME_REPOSITORY}" ] || [ -n "${TEST_REPOSITORY}" ]; then
  echo "image repository options apply only to --push-only" >&2
  exit 2
fi

# EVIDENCE GOES IN THE ARTIFACT DIRECTORY, not /tmp. A certification input that
# lives where the operating system may delete it is not retained evidence, and
# the whole batch is about being able to reproduce a verdict later.
RUNSTAMP="${START}_${END}"

step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
fail() { printf '\n\033[31mCERTIFICATION BLOCKED: %s\033[0m\n' "$*" >&2; exit 1; }

# The Synology failure occurred in a host evidence producer after the image
# build. Exercise that exact semantic surface before any build, push, corpus
# mutation, or evidence publication.
"${HOST_PYTHON}" scripts/sentinel_host_python.py || \
  fail "host Python is not compatible with the certification utilities; the minimum supported host interpreter is Python 3.8.15"

mkdir -p "${ART}"
SOURCE_GIT_SHA="$(git rev-parse HEAD)"
BUILD_RECORD="${ART}/image-build-${RUNSTAMP}-${SOURCE_GIT_SHA}.json"
PROMOTION_RECORD="${ART}/image-promotion-${RUNSTAMP}-${SOURCE_GIT_SHA}.json"

# A production image without authenticated dependency bytes is not buildable,
# and a certification attempt must explain that before spending build time.
[ -f sentinel/requirements.lock ] || \
  fail "sentinel/requirements.lock is missing; run scripts/sentinel-lock.sh"
grep -q -- '--hash=sha256:' sentinel/requirements.lock || \
  fail "sentinel/requirements.lock is version-only; regenerate its hashes"

# ── 1. the pinned image ──────────────────────────────────────────────────────
if [ "${PHASE}" = "build" ]; then
  step "1/9  building the pinned image"
  # --pull is DELIBERATELY ABSENT. The base is pinned by digest, so there is
  # nothing to pull that would not already be that exact image; passing it
  # would only make a network hiccup look like a build failure.
  ${COMPOSE} build --build-arg SOURCE_GIT_SHA="${SOURCE_GIT_SHA}" \
    sentinel sentinel-panel
  docker build --network host \
    --build-arg SENTINEL_RUNTIME_BASE_IMAGE=sentinel:latest \
    --build-arg SOURCE_GIT_SHA="${SOURCE_GIT_SHA}" \
    -t sentinel-authorized:latest -f Dockerfile.sentinel-authorized .
  docker build --network host \
    --build-arg SENTINEL_IMAGE=sentinel-authorized:latest \
    --build-arg SOURCE_GIT_SHA="${SOURCE_GIT_SHA}" \
    -t sentinel-test:latest -f Dockerfile.sentinel-test .
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
  docker build --network host --build-arg SOURCE_GIT_SHA="${SOURCE_GIT_SHA}" \
    -t stocker-base:latest -f Dockerfile.base .

  # BT-ENGINE IS BUILT HERE TOO, and deliberately NOT started. The manifest has
  # to name the engine that will run the rehearsal BEFORE it runs one —
  # comparing the run against whatever the tag points at during finalization
  # accepts any correctly self-identifying artefact that happens to run
  # afterwards, including one built from loader source that changed after the
  # freeze. Starting it is `scripts/bt-engine-up.sh`'s job; a recording step
  # does not get to bring a service up.
  BT_POSTGRES_PASSWORD="${BT_POSTGRES_PASSWORD:-build-only}" \
    docker compose -f docker-compose.backtest.yml build \
      --build-arg SOURCE_GIT_SHA="${SOURCE_GIT_SHA}" bt-data bt-engine

  "${HOST_PYTHON}" scripts/sentinel_certification_state.py capture-build \
    --git-commit "${SOURCE_GIT_SHA}" \
    --runtime-ref sentinel-authorized:latest \
    --test-ref sentinel-test:latest --output "${BUILD_RECORD}" || \
    fail "the exact local runtime/test image ids could not be retained"
  echo "BUILD PHASE COMPLETE: ${BUILD_RECORD}"
  echo "Next: rerun with --push-only and explicit runtime/test repositories."
  exit 0
fi

if [ "${PHASE}" = "push" ]; then
  [ -f "${BUILD_RECORD}" ] || fail \
    "${BUILD_RECORD} is missing; complete --build-only first"
  [ -z "$(git status --porcelain)" ] || fail \
    "the working tree is dirty; promotion must name the exact reviewed commit"
  "${HOST_PYTHON}" scripts/sentinel_certification_state.py verify-build \
    --record "${BUILD_RECORD}" || fail \
    "the local runtime/test image ids moved after --build-only"
  RUNTIME_TAG="${RUNTIME_REPOSITORY}:${SOURCE_GIT_SHA}"
  TEST_TAG="${TEST_REPOSITORY}:${SOURCE_GIT_SHA}"
  docker tag sentinel-authorized:latest "${RUNTIME_TAG}"
  docker tag sentinel-test:latest "${TEST_TAG}"
  docker push "${RUNTIME_TAG}"
  docker push "${TEST_TAG}"
  "${HOST_PYTHON}" scripts/sentinel_certification_state.py capture-promotion \
    --build-record "${BUILD_RECORD}" --runtime-tag "${RUNTIME_TAG}" \
    --test-tag "${TEST_TAG}" --output "${PROMOTION_RECORD}" || \
    fail "the pushed images could not be bound to immutable RepoDigests"
  echo "PUSH PHASE COMPLETE: ${PROMOTION_RECORD}"
  echo "Next: rerun with --verify-only to certify by immutable digest."
  exit 0
fi

[ -f "${PROMOTION_RECORD}" ] || fail \
  "${PROMOTION_RECORD} is missing; complete --build-only and --push-only first"
RUNTIME_IMAGE_REF=$("${HOST_PYTHON}" \
  scripts/sentinel_certification_state.py resolve-promotion \
  --record "${PROMOTION_RECORD}" --git-commit "${SOURCE_GIT_SHA}" \
  --kind runtime) || fail "the promoted runtime image is not immutable"
TEST_IMAGE_REF=$("${HOST_PYTHON}" \
  scripts/sentinel_certification_state.py resolve-promotion \
  --record "${PROMOTION_RECORD}" --git-commit "${SOURCE_GIT_SHA}" \
  --kind test) || fail "the promoted test image is not immutable"
export SENTINEL_RUNTIME_IMAGE_REF="${RUNTIME_IMAGE_REF}"

# `wealth_core_baseline_run` verifies the engine dependency lock and complete
# installed distribution closure against the manifest.  The canonical expected
# hash producer is part of the test image, so both files must be rebuilt after
# either source changes; the manifest's source-image checks below enforce that.

# ── 2. name the environment ──────────────────────────────────────────────────
step "2/9  naming the environment"
${RUN} identity --require-certified > "${ART}/identity-env.json" \
  || fail "the image is not the certified environment — pin drift, the wrong
  interpreter, or a source tree that could not be located. See
  ${ART}/identity-env.json"
"${HOST_PYTHON}" - "${ART}/identity-env.json" <<'PY' || fail "the identity record is incomplete"
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

step "2a/9 canonical database backup readiness"
[ -n "${SENTINEL_BACKUP_DIR:-}" ] || fail \
  "SENTINEL_BACKUP_DIR is unset. Certification requires second-target WAL and a verified base backup."
scripts/sentinel-backup-status.sh || fail \
  "WAL archiving/base-backup readiness failed; see docs/sentinel-deployment.md section 10g"

# ── 2b. THE CLOSURE LOCK, AHEAD OF ANYTHING DESTRUCTIVE ──────────────────────
# This used to sit at the END, as a yellow warning, after the truncate and the
# hours-long re-seed and immediately before "READY FOR THE REHEARSAL". That is
# exactly backwards: an unlocked build is not reproducible, so it would have
# destroyed a corpus and spent hours rebuilding one in order to produce evidence
# nobody could ever rebuild the environment for. A refusal is only a refusal if
# it comes before the irreversible step.
step "2b/9 the dependency closure must be LOCKED"
CLOSURE=$("${HOST_PYTHON}" -c "import json; print(json.load(open('${ART}/identity-env.json'))['environment']['distributions_hash'])")
IMAGE_LOCK=$("${HOST_PYTHON}" -c "import json; print(json.load(open('${ART}/identity-env.json'))['environment'].get('image_lock_sha256') or '')")
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
    scripts/sentinel-certify.sh --start ${START} --end ${END} --build-only

  Then follow the documented push and verify phases, adding --keep-corpus to
  the verify phase. Note the REBUILD: --verify-only does NOT rebuild the image,
  so it would check a lock in the checkout against an image that never consumed
  one. The rebuild is where the lock proves itself, and this script then compares
  the closure against the recorded bootstrap value automatically.

EOF
  exit 1
fi

if ! grep -q -- '--hash=sha256:' sentinel/requirements.lock; then
  fail "sentinel/requirements.lock is version-only. Regenerate it with
  scripts/sentinel-lock.sh; certification accepts only an artifact-hashed lock."
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

# AND THE CLOSURE MUST NOT HAVE MOVED. The bootstrap value proves the first
# locked rebuild. Later history comes only from explicitly named successful
# FINALIZED/PASS evidence; an abandoned attempt is never a baseline.
BASELINE=""
BASELINE_KIND=""
if [ -z "${CERTIFIED_BASELINE}" ] && [ -f "${BOOT}" ]; then
  BASELINE=$(cat "${BOOT}"); BASELINE_KIND="the unlocked bootstrap build"
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
else
  echo "  no bootstrap closure remains: ${CLOSURE}"
fi

CLOSURE_ARGS=(--art "${ART}" --identity "${ART}/identity-env.json" \
  --lock sentinel/requirements.lock --git-commit "${SOURCE_GIT_SHA}")
[ -z "${CERTIFIED_BASELINE}" ] || \
  CLOSURE_ARGS+=(--baseline "${CERTIFIED_BASELINE}")
[ -z "${CLOSURE_TRANSITION}" ] || \
  CLOSURE_ARGS+=(--transition "${CLOSURE_TRANSITION}")
"${HOST_PYTHON}" scripts/sentinel_certification_state.py check-closure \
  "${CLOSURE_ARGS[@]}" || fail \
  "the current dependency closure is not bound to successful certified evidence"

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
BT_REF=$("${HOST_PYTHON}" scripts/compose_image.py \
  --file docker-compose.backtest.yml --service bt-engine) \
  || fail "the bt-engine image could not be resolved from its compose file.
  NOT guessed: a wrong image name that resolves is worse than one that does
  not, because the record would then name an artefact nobody ran."
echo "  bt-engine image: ${BT_REF}"

BT_WC=$(docker run --rm --entrypoint python "${BT_REF}" -c \
  "from stock_strategy_shared import identity_hashes as i; print(i.wealth_core_source_hash())" \
  2>/dev/null || true)
SENTINEL_WC=$("${HOST_PYTHON}" -c "import json; print(json.load(open('${ART}/identity-env.json'))['environment']['wealth_core_source']['hash'])")
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
BT_DATA_REF=$("${HOST_PYTHON}" scripts/compose_image.py \
  --file docker-compose.backtest.yml --service bt-data) || \
  fail "the bt-data image could not be resolved from Compose"
PG_REF=$("${HOST_PYTHON}" -c "
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

MANIFEST_ARGS=("${ART}" "${RUNSTAMP}" "${LOCK_SHA}" \
  --postgres-ref "${PG_REF}" --bt-data-ref "${BT_DATA_REF}" \
  --bt-engine-ref "${BT_REF}" --runtime-ref "${RUNTIME_IMAGE_REF}" \
  --test-ref "${TEST_IMAGE_REF}" --require-images \
  --enforce-closure-context)
[ -z "${CERTIFIED_BASELINE}" ] || \
  MANIFEST_ARGS+=(--certified-baseline "${CERTIFIED_BASELINE}")
[ -z "${CLOSURE_TRANSITION}" ] || \
  MANIFEST_ARGS+=(--closure-transition "${CLOSURE_TRANSITION}")
"${HOST_PYTHON}" scripts/sentinel_manifest.py "${MANIFEST_ARGS[@]}" \
  || fail "the artefact manifest is incomplete — every image it names must
  resolve, and the source tree must be clean, BEFORE anything is destroyed."

# The lifecycle manifest at the path above is intentionally updated after
# corpus parity and again after rehearsal. Preserve the exact FROZEN bytes in a
# separate inode by atomic no-clobber publication while they still exist; the
# test-run record and evidence bundler consume this retained object rather than
# trusting its asserted hash.
PRE_SUITE_MANIFEST="${ART}/manifest-frozen-${RUNSTAMP}.json"
"${HOST_PYTHON}" scripts/sentinel_test_run.py retain-manifest \
  --manifest "${ART}/manifest-${RUNSTAMP}.json" \
  --output "${PRE_SUITE_MANIFEST}" \
  || fail "the exact FROZEN manifest bytes could not be retained by atomic
  no-clobber publication"

# Signed execution authority is deployable on another host, so its test record
# cannot name only local Docker image ids. Require exactly one immutable content
# digest for both images before the destructive corpus reset, not after it.
TEST_IMAGE_REF=$("${HOST_PYTHON}" scripts/sentinel_test_run.py validate-manifest \
  --manifest "${PRE_SUITE_MANIFEST}" --print-test-ref) \
  || fail "the runtime and test images do not each have one immutable registry
  digest. Push the exact built images and repeat identity recording; local tags
  and self-asserted environment values are not certification provenance."

# ── 3-4. the corpus ──────────────────────────────────────────────────────────
if [ "$KEEP" -eq 0 ]; then
  step "3/9  DISCARDING the corpus tables"
  echo "  Review #4 made ACTIONS authoritative for splits and dividends. Any"
  echo "  corpus seeded before it carries dividend_per_share = 0.0 everywhere"
  echo "  and split ratios inferred from prices. It is not repairable in place."
  # TRUNCATE, never `down --volumes`. The volume holds the canonical state,
  # account binding, journal, and corpus. Losing it is a recovery incident;
  # ordinary startup has no liquidation path.
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
DECLARE
  t text;
  present_tables text;
  reset_tables CONSTANT text[] := ARRAY[
    'sentinel_bar_split_repairs',
    'sentinel_bars',
    'sentinel_spy_total_return',
    'sentinel_defensive_bars',
    'sentinel_action_generation_events',
    'sentinel_action_observations',
    'sentinel_action_generations',
    'sentinel_actions',
    'sentinel_universe',
    'sentinel_ingest_rejections',
    'sentinel_rejection_truncation',
    'sentinel_anomaly_observation_events',
    'sentinel_corpus_anomalies',
    'sentinel_corpus_publications',
    'sentinel_readiness_snapshots',
    'sentinel_sep_staging',
    'feed_ingest_runs'
  ];
BEGIN
  -- PostgreSQL requires a referenced parent and every FK child being reset to
  -- appear in the SAME TRUNCATE statement. Sequential TRUNCATEs remain invalid
  -- even inside this transaction and even when the child is empty. Assemble
  -- one explicit statement rather than using CASCADE: a new, unreviewed child
  -- must stop certification instead of being erased implicitly.
  SELECT string_agg(format('%I.%I', 'public', candidate.table_name), ', '
                    ORDER BY candidate.ordinality)
    INTO present_tables
    FROM unnest(reset_tables) WITH ORDINALITY
         AS candidate(table_name, ordinality)
   WHERE to_regclass(format('%I.%I', 'public', candidate.table_name)) IS NOT NULL;

  IF present_tables IS NOT NULL THEN
    EXECUTE 'TRUNCATE TABLE ' || present_tables;
  END IF;

  FOREACH t IN ARRAY reset_tables LOOP
    IF to_regclass(format('%I.%I', 'public', t)) IS NULL THEN
      RAISE NOTICE 'absent (nothing to truncate): %', t;
    ELSE
      RAISE NOTICE 'truncated %', t;
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
INVENTORY_LOG="${ART}/suite-inventory-${RUNSTAMP}.txt"
INVENTORY_CMD=(docker run --rm --network none "${TEST_IMAGE_REF}" --collect-only -q tests/sentinel)
set +e
"${INVENTORY_CMD[@]}" > "${INVENTORY_LOG}" 2>&1
INVENTORY_RC=$?
set -e
[ "${INVENTORY_RC}" -eq 0 ] \
  || fail "the certified test image could not collect the exact suite inventory"

SUITE_LOG="${ART}/suite-${RUNSTAMP}.txt"
SUITE_CMD=(docker run --rm --network none "${TEST_IMAGE_REF}" tests/sentinel -q -rs)
set +e
SUITE=$("${SUITE_CMD[@]}" 2>&1)
SUITE_RC=$?
set -e
echo "${SUITE}" | tail -25
printf '%s\n' "${SUITE}" > "${SUITE_LOG}"

# This producer consumes only bytes emitted by the commands above. It binds the
# exact pre-suite manifest, immutable runtime/test digests, canonical command,
# sorted unique collection inventory and retained pytest log. It publishes by
# atomic no-clobber only when the exit/status counts prove a complete run.
"${HOST_PYTHON}" scripts/sentinel_test_run.py publish \
  --manifest "${PRE_SUITE_MANIFEST}" \
  --inventory-log "${INVENTORY_LOG}" --pytest-log "${SUITE_LOG}" \
  --exit-code "${SUITE_RC}" \
  --output "${ART}/test-run-${RUNSTAMP}.json" -- "${SUITE_CMD[@]}" \
  || fail "the suite did not produce complete certification-test-run evidence"

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
docker run --rm "${TEST_IMAGE_REF}" tests/sentinel/test_loader_parity.py -q \
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
# The `+psycopg` in an operator-supplied canonical DSN is not decoration. The
# canonical side goes through SQLAlchemy, and a bare
# `postgresql://` selects psycopg2 — which is NOT in the closure (the lock
# carries psycopg 3 only), so it fails as `No module named 'psycopg2'` wrapped
# in "the canonical corpus could not be read", one indirection away from the
# actual cause. When an approved DSN names bt-postgres's published host port,
# `--network host` is what makes 127.0.0.1 reach it: no shared Docker network,
# so Sentinel's isolation is unchanged — this reads a database, it does not
# depend on another application service.
#
# Both authorities are explicit. A certification run must not infer a database
# from a repository-known username or password.
[ -n "${SENTINEL_DATABASE_URL:-}" ] || fail \
  "SENTINEL_DATABASE_URL is unset. Real-window parity requires an explicit Sentinel DSN; no known-password fallback is permitted."
[ -n "${BT_DATABASE_URL:-}" ] || fail \
  "BT_DATABASE_URL is unset. Real-window parity requires an explicit canonical DSN; no known-password fallback is permitted."
docker run --rm --network host --entrypoint python \
  -e SENTINEL_DATABASE_URL="${SENTINEL_DATABASE_URL}" \
  -e BT_DATABASE_URL="${BT_DATABASE_URL}" \
  "${TEST_IMAGE_REF}" -m tools.corpus_parity \
  --start "${START}" --end "${END}" \
  > "${ART}/corpus-parity-${RUNSTAMP}.json" \
  2> "${ART}/corpus-parity-${RUNSTAMP}.err" \
  || {
  # A KILLED step leaves an EMPTY report, because `>` truncates before the
  # process runs. The OOM reaper did exactly that here: SIGKILL writes no
  # traceback, so a three-year comparison surfaced as a zero-byte JSON beside a
  # message instructing the operator to read it. Say which happened.
  PARITY_RC=$?
  if [ ! -s "${ART}/corpus-parity-${RUNSTAMP}.json" ]; then
    echo "  the report is EMPTY — the tool produced no output at all." >&2
    if [ -s "${ART}/corpus-parity-${RUNSTAMP}.err" ]; then
      echo "  stderr:" >&2
      sed 's/^/    /' "${ART}/corpus-parity-${RUNSTAMP}.err" >&2
    fi
    if [ "${PARITY_RC}" -ge 128 ]; then
      echo "  exit ${PARITY_RC} = signal $((PARITY_RC - 128)). 137 is an OOM" >&2
      echo "  kill: the comparison ran out of memory, it did not disagree." >&2
    fi
  fi
  fail "the seeded corpus does not match the canonical Wealth Core corpus,
  or the comparison could not be run at all. Read
  ${ART}/corpus-parity-${RUNSTAMP}.json — membership differences FIRST, then
  split_ratio, then dividends. Set both SENTINEL_DATABASE_URL and
  BT_DATABASE_URL explicitly: not having run this check is not the same as
  passing it."
  }

# ── 8c. deterministic Simplified Concordance LD-RC differential ─────────────
step "8c/9 deterministic Simplified Concordance LD-RC v3 integration differential"
CONCORDANCE_REPORT="${ART}/concordance-differential-${RUNSTAMP}.json"
docker run --rm --network host --entrypoint python \
  -e SENTINEL_DATABASE_URL="${SENTINEL_DATABASE_URL}" \
  "${TEST_IMAGE_REF}" -m tools.sentinel_concordance_differential \
  --end "${END}" > "${CONCORDANCE_REPORT}" \
  || fail "Simplified Concordance LD-RC deterministic differential failed. "\
"No expected allocation tape is used; read ${CONCORDANCE_REPORT}."
"${HOST_PYTHON}" - "${CONCORDANCE_REPORT}" <<'PY' || fail \
  "Simplified Concordance LD-RC differential did not prove zero mismatches"
import json, sys
r = json.load(open(sys.argv[1]))
if r.get("verdict") != "PASS":
    raise SystemExit(f"verdict={r.get('verdict')}: {r.get('first_divergence')}")
if r.get("strategy") != "sentinel-concordance-simplified-ldrc" or r.get("strategy_version") != 3:
    raise SystemExit("differential did not run Simplified Concordance LD-RC v3")
if r.get("metadata_mode") != "CURRENT_PUBLISHED_SNAPSHOT_FOR_INTEGRATION_PARITY_ONLY":
    raise SystemExit("differential metadata mode is ambiguous")
if r.get("historical_metadata_causality") != "NOT_CLAIMED":
    raise SystemExit("integration differential may not claim historical metadata causality")
if r.get("prospective_metadata_causality") != "SESSION_EFFECTIVE_RUNTIME_GATE":
    raise SystemExit("differential does not name the forward PIT runtime gate")
if r.get("sessions_compared", 0) <= 0 or r.get("field_comparisons", 0) <= 0:
    raise SystemExit("differential did not compare any strategy sessions")
print(f"  {r['sessions_compared']} sessions, {r['field_comparisons']} fields, zero mismatches")
print("  historical metadata causality: NOT CLAIMED; forward catch-up remains session-effective")
PY

# ── 9. the record ────────────────────────────────────────────────────────────
step "9/9  recording the rehearsal identity"
${RUN} identity --require-certified --start "${START}" --end "${END}" \
  > "${ART}/identity-${RUNSTAMP}.json" \
  || fail "the identity record could not be produced"
"${HOST_PYTHON}" - "${ART}/identity-${RUNSTAMP}.json" <<'PY'
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

# The frozen manifest becomes READY_FOR_REHEARSAL here. Its corpus hash and
# parity generations cannot exist before the corpus comparison; completion
# remains null until the separately authenticated rehearsal passes every gate.
"${HOST_PYTHON}" - "${ART}" "${RUNSTAMP}" <<'PYX' || fail "the manifest could not be completed"
import hashlib, json, sys
from pathlib import Path
art, stamp = Path(sys.argv[1]), sys.argv[2]
mp = art / f"manifest-{stamp}.json"
m = json.loads(mp.read_text())
rec = json.loads((art / f"identity-{stamp}.json").read_text())
c = rec.get("corpus") or {}
parity = json.loads((art / f"corpus-parity-{stamp}.json").read_text())
if parity.get("agrees") is not True:
    raise SystemExit("real-window parity report does not say agrees=true")
required = ("sentinel_data_version", "canonical_data_version",
            "canonical_source_mode")
missing = [key for key in required if parity.get(key) in (None, "")]
if missing:
    raise SystemExit(f"real-window parity lacks generation identity: {missing}")
if str(c.get("data_version")) != str(parity["sentinel_data_version"]):
    raise SystemExit(
        "Sentinel publication moved after real-window parity: "
        f"parity={parity['sentinel_data_version']} "
        f"identity={c.get('data_version')}")
if not c.get("corpus_hash"):
    raise SystemExit("the frozen Sentinel corpus has no corpus_hash")
sentinel_data_version = parity["sentinel_data_version"]
if (isinstance(sentinel_data_version, bool)
        or not isinstance(sentinel_data_version, int)
        or sentinel_data_version < 1):
    raise SystemExit(
        "real-window parity sentinel_data_version is not a positive integer")
m["corpus_hash"] = c["corpus_hash"]
m["postgres_server_version"] = c.get("postgres_server_version")
m["parity_generations"] = {
    "sentinel_data_version": sentinel_data_version,
    "canonical_data_version": str(parity["canonical_data_version"]),
    "canonical_source_mode": str(parity["canonical_source_mode"]),
}
ra = art / f"rejection-audit-{stamp}.json"
if ra.exists():
    m["preseed_rejection_audit_sha256"] = hashlib.sha256(
        ra.read_bytes()).hexdigest()
m["lifecycle"] = "READY_FOR_REHEARSAL"
m["verdict"] = None
m["failures"] = []
mp.write_text(json.dumps(m, indent=2, sort_keys=True))
print(f"  corpus_hash {m['corpus_hash']}")
print(f"  parity      {m['parity_generations']}")
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
