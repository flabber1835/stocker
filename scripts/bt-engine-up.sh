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
#
# AFTER A FREEZE, DO NOT REBUILD. `sentinel-certify.sh` has already built
# bt-engine and frozen its image id into the manifest; rebuilding here can only
# produce an artefact different from the one just certified. The certified path
# is therefore:
#
#   scripts/bt-engine-up.sh --no-build --start 2021-01-04 --end 2023-12-29
#
# which inspects the frozen image, checks it against THAT interval's manifest,
# and starts exactly it. `--start/--end` matters: selecting the NEWEST manifest
# by mtime compares against whatever certification ran last, which may be an
# unrelated interval.
#
# Ordinary build behaviour and ALLOW_DRIFT=1 remain for non-certification work.
set -euo pipefail

COMPOSE="docker compose -f docker-compose.backtest.yml"
BUILD=1; START=""; END=""; MANIFEST=""
while [ $# -gt 0 ]; do
  case "$1" in
    --no-build) BUILD=0; shift ;;
    --start) START="$2"; shift 2 ;;
    --end) END="$2"; shift 2 ;;
    --manifest) MANIFEST="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done

if [ "${BUILD}" -eq 1 ]; then
  echo "== building bt-engine"
  ${COMPOSE} build bt-engine
fi

# THE SAME RESOLVER THE CERTIFICATION HARNESS USES, so the two cannot form
# different opinions about which artefact they mean. The previous version
# guessed `$(basename $(pwd))-bt-engine`, but Compose uses the file's top-level
# `name:` as the project — `stocker-bt-bt-engine`, not `stocker-bt-engine`.
REF=$(python3 scripts/compose_image.py \
  --file docker-compose.backtest.yml --service bt-engine) || {
  echo "REFUSED: the bt-engine image could not be resolved from its compose" >&2
  echo "         file. NOT guessed — a wrong name that resolves is worse than" >&2
  echo "         one that does not." >&2
  exit 1
}

ID=$(docker image inspect "${REF}" --format '{{.Id}}' 2>/dev/null || true)
if [ -z "${ID}" ]; then
  echo "REFUSED: could not inspect ${REF}. bt-engine would start without" >&2
  echo "         knowing its own image, and any rehearsal it ran could not be" >&2
  echo "         certified. Build it first, or pass the right --project-name." >&2
  exit 1
fi
REVISION=$(docker image inspect "${REF}" --format \
  '{{ index .Config.Labels "org.opencontainers.image.revision" }}' \
  2>/dev/null || true)
if [ -z "${REVISION}" ] || [ "${REVISION}" = "unknown" ]; then
  echo "REFUSED: ${REF} has no immutable source revision label." >&2
  echo "         Rebuild it through the certification harness." >&2
  exit 1
fi

echo "== bt-engine image"
echo "   ref ${REF}"
echo "   id  ${ID}"
echo "   rev ${REVISION}"

# CHECK AGAINST THE FROZEN MANIFEST NOW, not after a three-hour rehearsal.
# The finalizer refuses a run whose engine image differs from the one the
# certification record named — correctly, and at the worst possible moment. The
# same comparison costs a second here, so a drifted engine is caught before the
# run rather than after it.
# THE MANIFEST FOR THIS INTERVAL, not merely the newest one. Selecting by mtime
# compares against whatever certification ran last, which may cover an unrelated
# window — a comparison that passes or fails for reasons having nothing to do
# with the run about to start.
if [ -n "${MANIFEST}" ]; then
  USE_MANIFEST="${MANIFEST}"
elif [ -n "${START}" ] && [ -n "${END}" ]; then
  USE_MANIFEST="artifacts/sentinel/manifest-${START}_${END}.json"
  [ -f "${USE_MANIFEST}" ] || {
    echo "REFUSED: no manifest for ${START}..${END}" >&2
    echo "         (${USE_MANIFEST}). Run scripts/sentinel-certify.sh first." >&2
    exit 1
  }
else
  USE_MANIFEST=$(ls -1t artifacts/sentinel/manifest-*.json 2>/dev/null | head -1 || true)
  [ -z "${USE_MANIFEST}" ] || echo "   comparing against the NEWEST manifest" \
    "(${USE_MANIFEST}) — pass --start/--end to name the interval"
fi
FROZEN=""
if [ -n "${USE_MANIFEST}" ]; then
  if ! FROZEN=$(python3 - "${USE_MANIFEST}" <<'PY'
import json
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
try:
    with path.open(encoding="utf-8") as handle:
        manifest = json.load(handle)
except (OSError, UnicodeError, json.JSONDecodeError) as exc:
    raise SystemExit(f"{path}: cannot read a JSON manifest: {exc}")
if not isinstance(manifest, dict):
    raise SystemExit(f"{path}: manifest root must be an object")
image = manifest.get("bt_engine_image")
if not isinstance(image, dict):
    raise SystemExit(f"{path}: bt_engine_image must be an object")
image_id = image.get("id")
if not isinstance(image_id, str) or not image_id.strip():
    raise SystemExit(f"{path}: bt_engine_image.id must be a non-empty string")
print(image_id.strip())
PY
  ); then
    echo "REFUSED: ${USE_MANIFEST} is not a complete certification manifest" >&2
    echo "         with a non-empty bt_engine_image.id." >&2
    exit 1
  fi
fi
if [ -n "${USE_MANIFEST}" ] && [ "${ALLOW_DRIFT:-0}" != "1" ]; then
  if [ "${FROZEN}" != "${ID}" ]; then
    echo >&2
    echo "REFUSED: this bt-engine image is NOT the one the certification" >&2
    echo "         manifest froze." >&2
    echo "  manifest ${USE_MANIFEST}" >&2
    echo "  frozen   ${FROZEN}" >&2
    echo "  built    ${ID}" >&2
    echo >&2
    echo "  A rehearsal run on this image would be REFUSED at finalization," >&2
    echo "  after three hours. After a freeze, start the CERTIFIED image" >&2
    echo "  without rebuilding:" >&2
    echo "    scripts/bt-engine-up.sh --no-build --start ... --end ..." >&2
    echo "  Or re-run scripts/sentinel-certify.sh to freeze a new record" >&2
    echo "  around this engine." >&2
    echo >&2
    echo "  ALLOW_DRIFT=1 starts it anyway — for non-certification work." >&2
    exit 1
  fi
  echo "   matches the frozen manifest"
fi

BT_ENGINE_IMAGE="${REF}" BT_ENGINE_IMAGE_ID="${ID}" \
  BT_ENGINE_SOURCE_REVISION="${REVISION}" \
  ${COMPOSE} up -d --force-recreate bt-engine

echo
echo "bt-engine is running and will record this image id on every run."
echo "Verify after starting a rehearsal:"
echo "  SELECT spec->'engine_identity' FROM bt_wealth_core_runs ORDER BY started_at DESC LIMIT 1;"
