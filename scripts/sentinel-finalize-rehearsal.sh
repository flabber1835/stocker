#!/usr/bin/env bash
#
# After the rehearsal: extract what it held, audit the interval against it, and
# close the manifest. NO HUMAN HANDOFF.
#
# The book is emitted by `rehearse_chain` and lands in the bt-engine run row's
# summary as `book_artifact`. Everything after that used to be an instruction:
# copy it out, save it as book.json, re-run the rejection audit with --book,
# note the hashes. That is no longer ticker transcription, and it is still a
# person moving evidence between two machines by hand — the step where a stale
# file, a wrong window or a forgotten re-run produces a CLEAN certification.
#
#   bt-engine run row
#        -> summary.book_artifact          extracted, hashed
#        -> sentinel rejection-audit --book   the REAL book, not an assertion
#        -> manifest completed             corpus, book, audit, rehearsal hashes
#
# The PRE-SEED audit asserted an empty book with --assert-no-holdings. That was
# true then and is NOT true of the interval the rehearsal actually traded, so
# this re-runs it against the realised book. Skipping it leaves the interval
# certified on a claim that has since become false.
#
# Usage:
#   scripts/sentinel-finalize-rehearsal.sh --start 2021-01-04 --end 2023-12-29 \
#       --run-id <bt_wealth_core_runs.run_id>
#   ... --from-json artifacts/bt/rehearsal-<id>.json     # if already exported
set -euo pipefail

COMPOSE="docker compose -f docker-compose.sentinel.yml"
RUN="${COMPOSE} run --rm -T sentinel"
ART="artifacts/sentinel"
START=""; END=""; RUN_ID=""; FROM_JSON=""

while [ $# -gt 0 ]; do
  case "$1" in
    --start) START="$2"; shift 2 ;;
    --end) END="$2"; shift 2 ;;
    --run-id) RUN_ID="$2"; shift 2 ;;
    --from-json) FROM_JSON="$2"; shift 2 ;;
    *) echo "unknown argument: $1" >&2; exit 2 ;;
  esac
done
[ -n "$START" ] && [ -n "$END" ] || { echo "--start and --end are required" >&2; exit 2; }
[ -n "$RUN_ID" ] || [ -n "$FROM_JSON" ] || {
  echo "one of --run-id or --from-json is required" >&2; exit 2; }

RUNSTAMP="${START}_${END}"
BOOK="${ART}/book-${RUNSTAMP}.json"
step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
fail() { printf '\n\033[31mFINALIZATION BLOCKED: %s\033[0m\n' "$*" >&2; exit 1; }

mkdir -p "${ART}"

# ── 1. extract the book the RUN emitted ──────────────────────────────────────
step "1/4  extracting the book from the rehearsal"
if [ -n "${FROM_JSON}" ]; then
  SRC="${FROM_JSON}"
else
  SRC="${ART}/rehearsal-${RUN_ID}.json"
  # BT_DATABASE_URL is the published host port the evaluator's bt_sql_query
  # already uses — no shared docker network, so Sentinel's isolation from the
  # retired stack is unchanged.
  [ -n "${BT_DATABASE_URL:-}" ] || fail "BT_DATABASE_URL is unset, so the
  rehearsal row cannot be read. Export it, or pass --from-json with a summary
  you exported yourself."
  python3 - "${RUN_ID}" "${SRC}" <<'PY' || fail "the rehearsal row could not be read"
import json, os, sys
import psycopg
run_id, out = sys.argv[1], sys.argv[2]
with psycopg.connect(os.environ["BT_DATABASE_URL"]) as c, c.cursor() as cur:
    cur.execute("SELECT summary FROM bt_wealth_core_runs WHERE run_id = %s",
                (run_id,))
    row = cur.fetchone()
if not row or not row[0]:
    sys.exit(f"no summary for run {run_id}")
open(out, "w").write(json.dumps(row[0], indent=2, sort_keys=True))
print(f"  read run {run_id} -> {out}")
PY
fi

python3 - "${SRC}" "${BOOK}" "${START}" "${END}" <<'PY' || fail "the book could not be extracted"
import json, sys
src, out, start, end = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
summary = json.load(open(src))
book = summary.get("book_artifact")
if not book:
    sys.exit(
        "the rehearsal summary carries NO book_artifact. An older engine "
        "produced this run — one that had the RunResult in hand and discarded "
        "it. Re-run the rehearsal on the current image rather than writing the "
        "book by hand: a hand-written book is exactly what this removes.")
w = book.get("window") or {}
if (w.get("start"), w.get("end")) != (start, end):
    sys.exit(
        f"the rehearsal covered {w.get('start')}..{w.get('end')} and you are "
        f"finalizing {start}..{end}. Refused: a book for a different window "
        f"omits every name held outside it, and a refused row on one of those "
        f"would then be cleared by admission floors that do not govern it.")
open(out, "w").write(json.dumps(book, indent=2, sort_keys=True))
print(f"  held={len(book['held'])} pending_terminal={len(book['pending_terminal'])}")
print(f"  -> {out}")
PY

# ── 2. the REAL rejection audit ──────────────────────────────────────────────
step "2/4  the rejection audit, against the REALISED book"
echo "  The pre-seed run asserted an EMPTY book. That was true before the first"
echo "  bootstrap and is not true of the interval the rehearsal traded."
${RUN} rejection-audit --start "${START}" --end "${END}" --book "/work/${BOOK}" \
  > "${ART}/rejection-audit-final-${RUNSTAMP}.json" \
  || fail "refused price rows in the interval are unexplained against the book
  the run actually held. Read ${ART}/rejection-audit-final-${RUNSTAMP}.json —
  every ticker under 'material' and 'undetermined' needs an answer. Do NOT
  relax the audit to clear it."

# ── 3. and 4. close the manifest ─────────────────────────────────────────────
step "3/4  completing the certification manifest"
python3 - "${ART}" "${RUNSTAMP}" "${SRC}" <<'PY' || fail "the manifest could not be completed"
import hashlib, json, sys
from pathlib import Path
art, stamp, src = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
mp = art / f"manifest-{stamp}.json"
if not mp.exists():
    sys.exit(f"{mp} does not exist — run scripts/sentinel-certify.sh first")
m = json.loads(mp.read_text())
summary = json.loads(src.read_text())

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

m["book_artifact_sha256"] = sha(art / f"book-{stamp}.json")
m["rejection_audit_sha256"] = sha(art / f"rejection-audit-final-{stamp}.json")
# THE HASHES THE REHEARSAL ITSELF PRODUCED. Without them the manifest names the
# environment and the corpus and says nothing about the run they produced.
m["rehearsal_hashes"] = summary.get("bulk_hashes") or None
m["rehearsal_equivalence"] = summary.get("equivalence") or None
m["settlement_counters"] = summary.get("settlement_counters") or None
m["terminal_reconciliation"] = summary.get("terminal_reconciliation") or None
mp.write_text(json.dumps(m, indent=2, sort_keys=True))
missing = [k for k in ("corpus_hash", "book_artifact_sha256",
                       "rejection_audit_sha256", "rehearsal_hashes")
           if not m.get(k)]
for k in missing:
    print(f"  INCOMPLETE: {k} is still null")
print(f"  -> {mp}")
sys.exit(1 if missing else 0)
PY

step "4/4  what to read, in this order"
cat <<'EOF'
  1  settlement counters and the per-episode terminal audit
     A CAGR without them cannot say how much of the book was VALUED rather than
     REALISED. `derived_last_mark_settlements == 0` beside nonzero
     `unresolved_terminal_events` means the book BLOCKED rather than settled.
  2  terminal_reconciliation: unreconciled_episodes MUST be 0
  3  the equivalence block — the session-by-session path reproduced the bulk
  4  only then, performance
EOF
printf '\n\033[32mREHEARSAL FINALIZED\033[0m — %s..%s\n' "${START}" "${END}"
echo "  book     ${BOOK}"
echo "  audit    ${ART}/rejection-audit-final-${RUNSTAMP}.json"
echo "  manifest ${ART}/manifest-${RUNSTAMP}.json"
