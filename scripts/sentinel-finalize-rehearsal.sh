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
step "1/4  extracting and AUTHENTICATING the rehearsal"
if [ -n "${FROM_JSON}" ]; then
  SRC="${FROM_JSON}"
else
  SRC="${ART}/rehearsal-${RUN_ID}.json"
  # BT_DATABASE_URL is the published host port the evaluator's bt_sql_query
  # already uses — no shared docker network, so Sentinel's isolation from the
  # retired stack is unchanged.
  [ -n "${BT_DATABASE_URL:-}" ] || fail "BT_DATABASE_URL is unset, so the
  rehearsal row cannot be read. Export it, or pass --from-json with an
  envelope EXPORTED BY THIS SCRIPT — not an arbitrary summary."
  python3 scripts/sentinel_rehearsal.py export --run-id "${RUN_ID}" --out "${SRC}" \
    || fail "the rehearsal row could not be exported"
fi

# ONE VALIDATOR, BOTH PATHS. `--from-json` used to skip the authentication
# entirely and go straight to reading `book_artifact`, so a hand-written file
# with the right window and fabricated equivalence/reconciliation fields
# bypassed every check the --run-id path had just gained. A second entrance
# with weaker locks is not a second entrance, it is the entrance.
python3 scripts/sentinel_rehearsal.py authenticate \
  --envelope "${SRC}" --book-out "${BOOK}" \
  --start "${START}" --end "${END}" \
  || fail "the rehearsal envelope was REFUSED"

# ── 2. the REAL rejection audit ──────────────────────────────────────────────
step "2/4  the rejection audit, against the REALISED book"
echo "  The pre-seed run asserted an EMPTY book. That was true before the first"
echo "  bootstrap and is not true of the interval the rehearsal traded."
# THE BOOK HAS TO REACH THE CONTAINER. The sentinel service's only volume is
# `sentinel_state:/var/lib/sentinel` — there is no /work and no artifacts mount
# — so a path like /work/artifacts/... simply does not exist inside it. ONE file
# is mounted read-only rather than the repository: the container needs this
# artifact and nothing else, and a repo mount would also put the source it must
# not import back on its filesystem.
${COMPOSE} run --rm -T -v "${PWD}/${BOOK}:/tmp/certified-book.json:ro" \
  sentinel rejection-audit --start "${START}" --end "${END}" \
  --book /tmp/certified-book.json \
  > "${ART}/rejection-audit-final-${RUNSTAMP}.json" \
  || fail "refused price rows in the interval are unexplained against the book
  the run actually held. Read ${ART}/rejection-audit-final-${RUNSTAMP}.json —
  every ticker under 'material' and 'undetermined' needs an answer. Do NOT
  relax the audit to clear it."

# ── 3. and 4. close the manifest ─────────────────────────────────────────────
step "3/4  completing the certification manifest"
python3 - "${ART}" "${RUNSTAMP}" "${SRC}" <<'PY' || fail "the certification conditions were NOT met. The evidence HAS been written — read the BLOCKED lines above and ${ART}/manifest-${RUNSTAMP}.json. A rehearsal whose session path did not reproduce its bulk replay, or whose terminal episodes do not reconcile, is not a certified rehearsal."
import hashlib, json, os, subprocess, sys
from pathlib import Path
art, stamp, src = Path(sys.argv[1]), sys.argv[2], Path(sys.argv[3])
mp = art / f"manifest-{stamp}.json"
if not mp.exists():
    sys.exit(f"{mp} does not exist — run scripts/sentinel-certify.sh first")
m = json.loads(mp.read_text())
env = json.loads(src.read_text())
# THE ROW'S CLAIMS AND THE RUN'S PAYLOAD, read from where each actually lives.
# They used to be flattened into one object, so a payload field could answer a
# question the database row was supposed to answer.
summary = env.get("summary") or {}
spec = env.get("spec") or {}

def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()

m["book_artifact_sha256"] = sha(art / f"book-{stamp}.json")
m["rejection_audit_sha256"] = sha(art / f"rejection-audit-final-{stamp}.json")
# THE HASHES THE REHEARSAL ITSELF PRODUCED. Without them the manifest names the
# environment and the corpus and says nothing about the run they produced.
m["rehearsal_hashes"] = env.get("parity_hashes") or summary.get("bulk_hashes") or None
m["rehearsal_run_id"] = env.get("run_id")
m["rehearsal_spec"] = spec or None
m["rehearsal_equivalence"] = summary.get("equivalence") or None
m["settlement_counters"] = summary.get("settlement_counters") or None
m["terminal_reconciliation"] = summary.get("terminal_reconciliation") or None

def sh(*c):
    try:
        return subprocess.run(c, capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:
        return None

# WHAT THE RUN SAID ABOUT ITSELF, recorded at its start. Compared BELOW against
# what the MANIFEST froze — not against a fresh inspect of a mutable tag, which
# answers "what does the tag point at now" and would accept any correctly
# self-identifying artefact that happens to run after the freeze.
ident = spec.get("engine_identity") or {}
m["bt_engine_identity"] = ident or None

mp.write_text(json.dumps(m, indent=2, sort_keys=True))

# ── THE CERTIFICATION CONDITIONS, AS GATES ───────────────────────────────────
# These were RECORDED and then narrated to the operator. "REHEARSAL FINALIZED"
# meant evidence exists, not that it passed — so a run with unreconciled
# episodes or a non-zero residual printed green.
eq = m.get("rehearsal_equivalence") or {}
tr = m.get("terminal_reconciliation") or {}
failures = []
for k in ("state_hash_matches", "ledger_hash_matches", "final_cash_matches"):
    if eq.get(k) is not True:
        failures.append(f"equivalence.{k} is {eq.get(k)!r} — the session-by-"
                        f"session path did not reproduce the bulk replay")
for k in ("unreconciled_episodes", "unexplained_episodes"):
    v = tr.get(k)
    if v:
        failures.append(f"terminal_reconciliation.{k} = {v}")
    elif v is None:
        failures.append(f"terminal_reconciliation.{k} is MISSING — the "
                        f"reconciliation did not run")
residual = tr.get("residual")
if residual is None:
    failures.append("terminal_reconciliation.residual is MISSING")
elif round(float(residual), 2) != 0.0:
    failures.append(f"terminal_reconciliation.residual = {residual}, not 0 — at "
                    f"least one episode's audit is internally inconsistent")
# COVERAGE. `residual: 0.00` and `unreconciled_episodes: []` were both true
# while the cash bucket held 3 of 8 episodes and $132k of $342k — every green
# light on, and most of the money outside the check.
# COVERAGE MUST BE 1.0, not merely present. Checking only for the field's
# EXISTENCE proves nothing and reproduces the exact failure this gate was added
# for: `residual: 0.00` and both episode lists empty were true while the cash
# bucket held 3 of 8 episodes and $132k of $342k. Every green light on, and most
# of the money outside the check.
#
# If exact-terms NON-CASH settlement is ever supported, the general rule is an
# ACCOUNTED coverage fraction spanning both buckets. For THIS certification the
# accepted gate is 100% of the population inside the cash reconciliation.
cov = tr.get("cash_coverage_fraction")
if cov is None:
    failures.append("terminal_reconciliation.cash_coverage_fraction is MISSING")
elif float(cov) != 1.0:
    failures.append(
        f"terminal_reconciliation.cash_coverage_fraction = {cov}, not 1.0 — "
        f"{tr.get('cash_settled_episodes')} of {tr.get('episodes')} episodes "
        f"are inside the reconciliation, so 'residual == 0' is a claim about a "
        f"subset. Non-cash episodes: {tr.get('non_cash_episodes')}, carried "
        f"{tr.get('non_cash_carried_notional')}")

# THE ENGINE THAT PRODUCED THE NUMBERS, bound to the one being certified.
# `sentinel:latest` carries a Wealth Core source tree; the rehearsal imported
# one. If they differ, the manifest describes an engine that did not produce
# these results — the single most consequential mismatch in the record, because
# it is about economics rather than packaging.
if not ident:
    failures.append(
        "bt_engine_identity is MISSING — the rehearsal did not record what "
        "engine ran it, so its numbers cannot be bound to any Wealth Core "
        "source. Re-run on the current bt-engine image")
else:
    ran = ident.get("wealth_core_source_hash")
    certified = m.get("wealth_core_source_hash")
    if not ran:
        failures.append("bt_engine_identity carries no wealth_core_source_hash")
    elif certified and ran != certified:
        failures.append(
            f"the rehearsal ran Wealth Core {ran[:16]} and the certified image "
            f"carries {certified[:16]}. These numbers were produced by a "
            f"different engine than the one being certified")
    if not ident.get("bt_engine_app_source_hash"):
        failures.append(
            "bt_engine_identity carries no bt_engine_app_source_hash — the "
            "Wealth Core tree alone does not identify the engine that LOADED "
            "the corpus and built the rehearsal inputs")
    # THE LOADER SOURCE, bound to the FROZEN value. Required-present is not the
    # same as bound: only Wealth Core was compared, so a change to the code that
    # READS THE CORPUS could land after the manifest was written and still
    # match, because Wealth Core had not moved.
    ran_app = ident.get("bt_engine_app_source_hash")
    frozen_app = m.get("bt_engine_app_source_hash")
    if not ran_app:
        failures.append(
            "bt_engine_identity carries no bt_engine_app_source_hash — the "
            "Wealth Core tree alone does not identify the engine that LOADED "
            "the corpus and built the rehearsal inputs")
    elif frozen_app and ran_app != frozen_app:
        failures.append(
            f"the rehearsal ran bt-engine loader source {ran_app[:16]} and the "
            f"manifest froze {frozen_app[:16]}. The code that reads the corpus "
            f"changed after the certification record was written")

    # THE IMAGE, compared against the one the MANIFEST NAMED at freeze time.
    # Two bt-engine containers can carry the same Wealth Core tree and different
    # interpreters, dependencies, loader code and client libraries — and
    # bt-engine is what reads the corpus.
    recorded = ident.get("image_id")
    frozen = (m.get("bt_engine_image") or {}).get("id")
    if not recorded:
        failures.append(
            "bt_engine_identity has no image_id — the rehearsal did not know "
            "which image it was running. Start bt-engine with "
            "`scripts/bt-engine-up.sh` (build, inspect, inject, then start) and "
            "re-run")
    elif not frozen:
        failures.append(
            "the manifest does not name a bt-engine image, so the id the run "
            "recorded cannot be checked against anything. Re-run "
            "scripts/sentinel-certify.sh, which builds bt-engine and freezes "
            "its id BEFORE any rehearsal exists")
    elif recorded != frozen:
        failures.append(
            f"the rehearsal ran bt-engine image {recorded[:19]}... and the "
            f"manifest froze {frozen[:19]}.... The engine was rebuilt after the "
            f"certification record was written, so these numbers were not "
            f"produced by the artefact being certified")

# THE SOURCE HAS NOT MOVED SINCE THE FREEZE. Everything above binds images and
# hashes; this binds the CHECKOUT. Without it the manifest can name commit A
# while the tree has since become B — and every artefact comparison would still
# pass, because they compare against values frozen from A.
head = sh("git", "rev-parse", "HEAD")
if m.get("git_commit") and head and head != m["git_commit"]:
    failures.append(
        f"HEAD is {head[:12]} and the manifest was frozen at "
        f"{m['git_commit'][:12]}. The source moved after the certification "
        f"record was written")
if sh("git", "status", "--porcelain") != "":
    failures.append(
        "the working tree is DIRTY at finalization, so no commit identifies "
        "what produced this evidence")

missing = [k for k in ("corpus_hash", "book_artifact_sha256",
                       "rejection_audit_sha256", "rehearsal_hashes")
           if not m.get(k)]
for k in missing:
    failures.append(f"{k} is still null")

for f in failures:
    print(f"  BLOCKED: {f}")
print(f"  cash_coverage_fraction: {cov}")
print(f"  -> {mp}")
sys.exit(1 if failures else 0)
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
