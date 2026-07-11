#!/usr/bin/env bash
# Real-image import smoke — run on a Docker host (NAS/CI) BEFORE `up -d`.
#
# Builds each service image and runs `python -c "import app.main"` inside it —
# catching container-only import failures (wrong layout, missing COPY, path
# arithmetic tuned to the repo checkout) that unit tests cannot see. The
# no-Docker CI twin is tests/smoke/test_image_layout_imports.py.
#
# Usage:
#   ./scripts/smoke-image-imports.sh                 # default service set
#   ./scripts/smoke-image-imports.sh bt-engine ...   # specific services
#
# Requires the stocker-base image (built by the normal compose build).
set -u
cd "$(dirname "$0")/.."

SERVICES=("$@")
if [ ${#SERVICES[@]} -eq 0 ]; then
  SERVICES=(bt-engine bt-data bt-scheduler backtester evaluator)
fi

DUMMY_ENV=(-e DATABASE_URL=postgresql+asyncpg://smoke:smoke@localhost/smoke
           -e BT_DATABASE_URL=postgresql+asyncpg://smoke:smoke@localhost/smoke
           -e ALPACA_API_KEY= -e AV_API_KEY=demo)

fail=0
for svc in "${SERVICES[@]}"; do
  df="services/$svc/Dockerfile"
  if [ ! -f "$df" ]; then echo "SKIP  $svc (no Dockerfile)"; continue; fi
  echo "── $svc: build ──────────────────────────────────────────────"
  if ! docker build -q -f "$df" -t "smoke-$svc" . >/dev/null; then
    echo "FAIL  $svc: image build failed"; fail=1; continue
  fi
  if docker run --rm "${DUMMY_ENV[@]}" "smoke-$svc" python -c "import app.main" ; then
    echo "OK    $svc: app.main imports inside the image"
  else
    echo "FAIL  $svc: import app.main FAILED inside the image — this container would crash-loop"
    fail=1
  fi
done
exit $fail
