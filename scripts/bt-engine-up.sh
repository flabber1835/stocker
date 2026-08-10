#!/usr/bin/env bash
#
# Start bt-engine so it KNOWS which image it is running.
#
# A container cannot discover its own image id, and inspecting the tag after the
# fact answers a different question — what `stocker-bt-engine:latest` points at
# NOW, not what produced a three-hour rehearsal. Rebuild the tag in between and
# the certification manifest names the wrong image, with nothing about it
# looking wrong.
#
# So the order is: build, INSPECT, then start with the id injected.
#
#   docker compose build bt-engine
#        -> docker image inspect --format '{{.Id}}'
#             -> BT_ENGINE_IMAGE_ID=sha256:...  up -d --force-recreate
#                  -> every run records it in bt_wealth_core_runs.spec
#
# An ordinary `docker compose -f docker-compose.backtest.yml up -d bt-engine`
# still works and simply records `null`. The certification path REFUSES that, so
# a rehearsal started the casual way cannot be certified by accident — it can
# only be re-run.
set -euo pipefail

COMPOSE="docker compose -f docker-compose.backtest.yml"
BUILD=1
[ "${1:-}" = "--no-build" ] && BUILD=0

if [ "${BUILD}" -eq 1 ]; then
  echo "== building bt-engine"
  ${COMPOSE} build bt-engine
fi

# The image compose will actually run, resolved from the service definition
# rather than assumed — a project-name prefix or an `image:` override would make
# a hardcoded tag name wrong in a way that is invisible until the id is null.
REF=$(${COMPOSE} config --format json 2>/dev/null \
      | python3 -c "
import json,sys
try:
    svc = json.load(sys.stdin)['services']['bt-engine']
except Exception:
    sys.exit(0)
sys.stdout.write(svc.get('image') or '')" || true)
if [ -z "${REF}" ]; then
  # compose derives <project>-<service> when no image: is declared.
  PROJECT=$(basename "$(pwd)" | tr '[:upper:]' '[:lower:]')
  REF="${PROJECT}-bt-engine"
fi

ID=$(docker image inspect "${REF}" --format '{{.Id}}' 2>/dev/null || true)
if [ -z "${ID}" ]; then
  echo "REFUSED: could not inspect ${REF}. bt-engine would start without" >&2
  echo "         knowing its own image, and any rehearsal it ran could not be" >&2
  echo "         certified. Build it first, or pass the right --project-name." >&2
  exit 1
fi

echo "== bt-engine image"
echo "   ref ${REF}"
echo "   id  ${ID}"

# CHECK AGAINST THE FROZEN MANIFEST NOW, not after a three-hour rehearsal.
# The finalizer refuses a run whose engine image differs from the one the
# certification record named — correctly, and at the worst possible moment. The
# same comparison costs a second here, so a drifted engine is caught before the
# run rather than after it.
NEWEST_MANIFEST=$(ls -1t artifacts/sentinel/manifest-*.json 2>/dev/null | head -1 || true)
if [ -n "${NEWEST_MANIFEST}" ] && [ "${ALLOW_DRIFT:-0}" != "1" ]; then
  FROZEN=$(python3 -c "
import json,sys
try:
    print((json.load(open('${NEWEST_MANIFEST}')).get('bt_engine_image') or {}).get('id') or '')
except Exception:
    pass" || true)
  if [ -n "${FROZEN}" ] && [ "${FROZEN}" != "${ID}" ]; then
    echo >&2
    echo "REFUSED: this bt-engine image is NOT the one the certification" >&2
    echo "         manifest froze." >&2
    echo "  manifest ${NEWEST_MANIFEST}" >&2
    echo "  frozen   ${FROZEN}" >&2
    echo "  built    ${ID}" >&2
    echo >&2
    echo "  A rehearsal run on this image would be REFUSED at finalization," >&2
    echo "  after three hours. Either check out the certified commit and" >&2
    echo "  rebuild, or re-run scripts/sentinel-certify.sh to freeze a new" >&2
    echo "  record around this engine." >&2
    echo >&2
    echo "  ALLOW_DRIFT=1 starts it anyway — for non-certification work." >&2
    exit 1
  fi
  [ -n "${FROZEN}" ] && echo "   matches the frozen manifest"
fi

BT_ENGINE_IMAGE="${REF}" BT_ENGINE_IMAGE_ID="${ID}" \
  ${COMPOSE} up -d --force-recreate bt-engine

echo
echo "bt-engine is running and will record this image id on every run."
echo "Verify after starting a rehearsal:"
echo "  SELECT spec->'engine_identity' FROM bt_wealth_core_runs ORDER BY started_at DESC LIMIT 1;"
