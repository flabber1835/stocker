#!/usr/bin/env bash
set -euo pipefail
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"
OUT="${1:-artifacts/synthetic-market-lab/reference-world-v1}"
PYTHONPATH="$ROOT" python -m research.synthetic_market_lab.cli reproduce \
  --config research/synthetic_market_lab/config/reference-world-v1.json \
  --output "$OUT"
PYTHONPATH="$ROOT" pytest -q research/synthetic_market_lab/tests
