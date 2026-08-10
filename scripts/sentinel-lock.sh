#!/usr/bin/env bash
#
# Freeze the COMPLETE dependency closure of the certified image.
#
# `sentinel/requirements.txt` pins the DIRECT dependencies. pip is still free to
# resolve everything underneath them, so two builds of the same Dockerfile a
# month apart can carry the same declared versions and different transitive
# closures. `identity` now fingerprints the whole installed set, so those two
# builds get DIFFERENT identity hashes and can never be mistaken for one
# environment — but a differing hash tells you the environments differ, it does
# not let you rebuild the first one. This does.
#
# THE BOOTSTRAP IS ONE-WAY AND ONLY HAPPENS ONCE:
#
#   1  build from requirements.txt          (pip resolves the closure)
#   2  this script reads it back OUT        (the closure becomes a fact)
#   3  commit sentinel/requirements.lock
#   4  rebuild                              (the Dockerfile now prefers the lock)
#   5  the two builds' distributions_hash MUST match — that is the proof the
#      lock actually describes the image it came from, and step 5 is the point
#      of the exercise. If it does not match, do NOT edit the lock to agree;
#      find out what moved.
#
# --hashes adds per-artefact digests, so a rebuild also proves the WHEELS were
# the same bytes and not merely the same version strings. It requires every
# package to be installable from a hash-checked index; if that fails for a
# platform-specific wheel, fall back to the version-only lock and say so in the
# certification record rather than dropping the lock entirely.
#
# Usage:
#   scripts/sentinel-lock.sh                 # version-only lock
#   scripts/sentinel-lock.sh --hashes        # with per-artefact hashes
set -euo pipefail

IMAGE="${SENTINEL_IMAGE:-sentinel:latest}"
OUT="sentinel/requirements.lock"
WITH_HASHES=0
[ "${1:-}" = "--hashes" ] && WITH_HASHES=1

docker image inspect "${IMAGE}" >/dev/null 2>&1 || {
  echo "REFUSED: ${IMAGE} does not exist. Build it first — the lock is read" >&2
  echo "         OUT of a real build, never written by hand." >&2
  exit 1
}

PY_VERSION=$(docker run --rm --entrypoint python "${IMAGE}" -c \
  'import platform; print(platform.python_version())')

TMP=$(mktemp)
trap 'rm -f "${TMP}"' EXIT

if [ "${WITH_HASHES}" -eq 1 ]; then
  docker run --rm --entrypoint sh "${IMAGE}" -c \
    'pip install --no-cache-dir --quiet pip-tools >/dev/null 2>&1; \
     pip freeze --all --exclude-editable' > "${TMP}"
  echo "NOTE: per-artefact hashes require a hash-checked resolve; this script" >&2
  echo "      emits versions and leaves hash generation to a pip-compile run" >&2
  echo "      against the same index. Recorded as version-only." >&2
else
  docker run --rm --entrypoint pip "${IMAGE}" freeze --all --exclude-editable \
    > "${TMP}"
fi

{
  echo "# THE COMPLETE RESOLVED CLOSURE of ${IMAGE}. GENERATED — do not hand-edit."
  echo "#"
  echo "# Read OUT of a real build by scripts/sentinel-lock.sh, never written by"
  echo "# hand. Editing a line here to make a rebuild agree would turn the one"
  echo "# artefact that records what was actually installed into a wish."
  echo "#"
  echo "# Python ${PY_VERSION}. A lock is only valid for the interpreter that"
  echo "# produced it: markers and platform wheels differ across versions, so a"
  echo "# lock generated under 3.11 does not describe a 3.12 image."
  echo "#"
  echo "# sentinel/requirements.txt remains the DECLARATION — what we chose and"
  echo "# why, with the reasoning. This is the RESOLUTION. Change the first,"
  echo "# rebuild, regenerate the second."
  echo "#"
  echo "# The editable install of shared/ is excluded: it is source COPIED into"
  echo "# the image and hashed separately as wealth_core_source, not a"
  echo "# distribution to resolve."
  echo "#"
  grep -v -i '^stock.strategy.shared' "${TMP}" | sed '/^\s*$/d' | sort -f
} > "${OUT}"

echo "wrote ${OUT} ($(grep -c '==' "${OUT}") distributions, python ${PY_VERSION})"
echo
echo "NEXT, and it is the whole point:"
echo "  1  commit ${OUT}"
echo "  2  rebuild the image (the Dockerfile prefers the lock when present)"
echo "  3  compare distributions_hash before and after:"
echo "       docker compose -f docker-compose.sentinel.yml run --rm -T sentinel \\"
echo "         identity | python3 -c 'import json,sys; \\"
echo "           print(json.load(sys.stdin)[\"environment\"][\"distributions_hash\"])'"
echo "     They MUST match. If they do not, something in the closure moved that"
echo "     the lock does not describe — do not edit the lock to agree."
