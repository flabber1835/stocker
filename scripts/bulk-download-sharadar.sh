#!/usr/bin/env bash
# Bulk-export the Sharadar tables to local ZIPs.
#
# WHY THIS EXISTS. bt-data pages the datatables API cursor by cursor, which is
# right for a nightly topup and painful for a full history: the ~35M-row SEP
# backfill runs for hours and any interruption resumes from a chunk boundary.
# Nasdaq's bulk export hands you the whole table as one ZIP in minutes. It is a
# FASTER ROUTE TO THE SAME DATA, not a second source — nothing here writes to
# bt-postgres, and the corpus is still loaded by bt-data.
#
# WHY IT RUNS IN A CONTAINER. The NAS has no pip and no python3 with the
# nasdaq-data-link package, and installing one on a DSM host to run a download is
# the kind of thing nobody remembers doing six months later. A throwaway
# python:3.12-slim leaves the host exactly as it found it.
#
# THE KEY IS NEVER PRINTED, never passed on the command line (where it would land
# in `ps` and in shell history), and never baked into an image. It is read from
# .env and handed to the container through its environment only.
set -euo pipefail

cd "$(dirname "$0")/.."
ROOT="$(pwd)"

OUT_DIR="${SHARADAR_BULK_DIR:-$ROOT/artifacts/sharadar-bulk}"
TABLES="${SHARADAR_BULK_TABLES:-SEP TICKERS ACTIONS SFP SF1}"
IMAGE="${SHARADAR_BULK_IMAGE:-python:3.12-slim}"

usage() {
    cat <<'USAGE'
Usage: scripts/bulk-download-sharadar.sh [--tables "SEP SF1"] [--out DIR] [--force]

  --tables   space-separated Sharadar table names (default: SEP TICKERS ACTIONS SFP SF1)
  --out      destination directory (default: artifacts/sharadar-bulk)
  --force    re-download a table whose ZIP already exists
  --help

The API key is read from .env (SHARADAR_API_KEY) and never echoed.
USAGE
}

FORCE=0
while [ $# -gt 0 ]; do
    case "$1" in
        --tables) TABLES="$2"; shift 2 ;;
        --out)    OUT_DIR="$2"; shift 2 ;;
        --force)  FORCE=1; shift ;;
        --help|-h) usage; exit 0 ;;
        *) echo "unknown argument: $1" >&2; usage; exit 2 ;;
    esac
done

# ── the key ──────────────────────────────────────────────────────────────────
# Parsed rather than sourced. `source .env` executes the file, so a stray
# backtick or $(...) in any value — including one that arrived by a git pull —
# would run as a shell command. A download script has no business doing that.
if [ ! -f "$ROOT/.env" ]; then
    echo "no .env at $ROOT/.env — cannot find SHARADAR_API_KEY" >&2
    exit 1
fi
# Trailing whitespace is stripped as well as leading. `KEY = value ` reads as a
# valid assignment to every other tool that touches .env, and a key with a
# trailing space fails as a 403 several minutes into a multi-GB download — a long
# way from the one character that caused it.
KEY="$(sed -n 's/^[[:space:]]*SHARADAR_API_KEY[[:space:]]*=[[:space:]]*//p' "$ROOT/.env" \
       | tail -n 1 | tr -d '\r' \
       | sed -e 's/[[:space:]]*$//' \
             -e 's/^"//' -e "s/^'//" -e 's/"$//' -e "s/'$//" \
             -e 's/[[:space:]]*$//')"
if [ -z "$KEY" ]; then
    echo "SHARADAR_API_KEY is missing or empty in .env" >&2
    exit 1
fi
echo "key loaded from .env (${#KEY} chars)"     # length only — never the value

mkdir -p "$OUT_DIR"
echo "destination: $OUT_DIR"
echo "tables     : $TABLES"
echo

# Skip what is already on disk unless --force. A re-run after a partial batch
# should cost nothing for the tables that already landed — SEP alone is several
# GB and re-fetching it to get TICKERS would be absurd.
PENDING=""
for t in $TABLES; do
    if [ "$FORCE" -eq 0 ] && [ -s "$OUT_DIR/SHARADAR_$t.zip" ]; then
        echo "  $t — already present, skipping (--force to re-download)"
    else
        PENDING="$PENDING $t"
    fi
done
if [ -z "${PENDING// /}" ]; then
    echo; echo "nothing to do."
    exit 0
fi

docker run --rm \
    -e NDL_KEY="$KEY" \
    -e TABLES="$PENDING" \
    -v "$OUT_DIR:/out" \
    "$IMAGE" \
    bash -c '
set -euo pipefail
pip install --quiet --no-cache-dir nasdaq-data-link
python - <<"PY"
import os, time
import nasdaqdatalink as ndl

ndl.ApiConfig.api_key = os.environ["NDL_KEY"]

for name in os.environ["TABLES"].split():
    code = f"SHARADAR/{name}"
    # Write to a .part first and rename on success. An interrupted export
    # otherwise leaves a truncated ZIP that looks complete to the skip check
    # above, and the next run would happily skip it forever.
    part  = f"/out/SHARADAR_{name}.zip.part"
    final = f"/out/SHARADAR_{name}.zip"
    print(f"[{name}] requesting bulk export …", flush=True)
    t0 = time.time()
    try:
        ndl.export_table(code, filename=part)
    except Exception as exc:
        print(f"[{name}] FAILED: {exc}", flush=True)
        if os.path.exists(part):
            os.remove(part)
        raise
    os.replace(part, final)
    mb = os.path.getsize(final) / 1e6
    print(f"[{name}] done — {mb:,.1f} MB in {time.time()-t0:,.0f}s", flush=True)
PY
'

echo
echo "── downloaded ───────────────────────────────────────────────────────────"
ls -lh "$OUT_DIR"
echo
echo "These are RAW EXPORTS. Nothing has been loaded into bt-postgres — the"
echo "corpus is still whatever bt-data has ingested. Loading them is a separate"
echo "step and a separate decision."
