# Resumed provisional historical economic run

Production source: merged #430, `ee23c894c97a2c4023654ce3a56a62728f5b061e`.
Current Sentinel compact champion parameters remain unchanged. No #432/#433
challenger is active. Source-fork policy and action assumptions:
[economic-replay-resume-430.md](../../docs/economic-replay-resume-430.md).

This continues the existing $100,000 January 2006 formation, with CAGR measured
from July 31, 2006. It is a mixed-source, reconstructed-classification economic
experiment, not a uniform-code full-system certification. The full reference is
56.265349x / 22.323600% over twenty years; shorter current results must be compared
with the reference on the same endpoint.

## Runtime preparation and source binding

Export exact Git bytes from the named production revision into an unused local
runtime directory. Copy `runtime-run.py` from this evidence directory over its
`research/bounded_20y/run.py`; this differs from the retained original harness
only in the explicit source-revision pin and normalized line endings. The
repository's original harness and golden manifest remain unchanged.

Run `research/economic_replay60/fork_430.py` with the exact arguments below. It
checks the preserved predecessor files/checkpoint, requires only the reviewed
kernel/spin-off/ledger source changes, rejects changed rule/configuration identity,
and writes a separate analytical checkpoint. Its ordinary checkpoint-reader
verification passed; all book/account/baseline values are preserved. No deployed
state or authority is involved. `runtime-production-source.json` records the
actual resulting source manifest; `migration.json` records both identities.
Retained text uses LF line endings. `runtime-production-source.original.json.gz`
preserves the exact manifest bytes whose hash appears in the migration record.

## Executed commands

Existing runtime: Python 3.12.14; NumPy 2.4.6; pandas 3.0.5;
exchange_calendars 4.13.2; pytest 8.3.5. The root/shared and existing
`C:/GitHub/stocker/.codex-tmp/classification-check-runtime` directories were on
PYTHONPATH. Machine-specific paths identify retained local artifacts.

```powershell
git archive --format=zip --output=C:/GitHub/stocker/.codex-tmp/replay-runtime-ee23c894.zip ee23c894c97a2c4023654ce3a56a62728f5b061e
# Extract to unused C:/GitHub/stocker/.codex-tmp/merged-20y-runtime-ee23c894;
# copy the explicit runtime-run.py pin as described above.
& C:/GitHub/stocker/.codex-tmp/bounded-feed-venv/Scripts/python.exe research/economic_replay60/fork_430.py --runtime C:/GitHub/stocker/.codex-tmp/merged-20y-runtime-ee23c894 --old-runtime C:/GitHub/stocker/.codex-tmp/merged-20y-runtime-da7b64a9 --old-pointer C:/GitHub/stocker/.codex-tmp/economic-replay-merged-da7b64a9/segment-043/latest-checkpoint.json --output C:/GitHub/stocker/.codex-tmp/economic-replay-merged-ee23c894/migration --revision ee23c894c97a2c4023654ce3a56a62728f5b061e

& C:/GitHub/stocker/.codex-tmp/bounded-feed-venv/Scripts/python.exe -m pytest research/economic_replay60/test_fork_430.py research/economic_replay60/test_inputs.py -q -p no:cacheprovider --basetemp C:/GitHub/stocker/.codex-tmp/replay430-tests --junitxml audit/economic-replay-resume-430/tests.xml
& C:/GitHub/stocker/.codex-tmp/bounded-feed-venv/Scripts/python.exe -m research.economic_replay60.fork_mutations --output audit/economic-replay-resume-430/mutations.json --scratch C:/GitHub/stocker/.codex-tmp/replay430-mutants
```

Tests: **10 passed in 0.30s**. Mutations: **2/2 killed** after disabling each
source/revision fence. Initial mutation-driver import/scratch errors were
rejected as invalid falsifier results; the retained final report contains the
intended boundary failures. Syntax and test ownership checks pass. Research
checks are explicit local tests, not newly added production CI certification.

Worker command, from the isolated runtime directory:

```powershell
$env:PYTHONPATH="$PWD;$PWD\shared;C:\GitHub\stocker\.codex-tmp\classification-check-runtime"
& C:/GitHub/stocker/.codex-tmp/bounded-feed-venv/Scripts/python.exe -B -m research.economic_replay60.run --harness C:/GitHub/stocker/.codex-tmp/merged-20y-runtime-ee23c894 --archive C:/GitHub/stocker/.codex-tmp/pit-source-5bdc6b39.zip --sfp 'C:/GitHub/stocker/.codex-tmp/pit-prefix-source/PIT input data/SFP_SPY_BIL_PRICE_FACTORS_PIT_ONLY.csv.gz' --supplements C:/GitHub/stocker/.codex-tmp/economic-replay-merged-ee23c894/supplements.json --resume C:/GitHub/stocker/.codex-tmp/economic-replay-merged-ee23c894/migration/latest-checkpoint.json --output C:/GitHub/stocker/.codex-tmp/economic-replay-merged-ee23c894/segment-044 --seconds 1800
```

Segment 044 was deliberately stopped while waiting at December 7 to correct the
FDO issuer key. Its July 1 through July 6 rows remain valid; later rows are
superseded. Its inputs, checkpoints and original trace remain intact locally.
`resume-before-fdo.json` points to its unchanged July 6 checkpoint. The corrected
continuation used the same command with these arguments changed:

```text
--supplements C:/GitHub/stocker/.codex-tmp/economic-replay-merged-ee23c894/supplements-corrected.json
--resume C:/GitHub/stocker/.codex-tmp/economic-replay-merged-ee23c894/resume-before-fdo.json
--output C:/GitHub/stocker/.codex-tmp/economic-replay-merged-ee23c894/segment-045
--seconds 849
```

The 849-second allowance was computed from the original 22:00:24 UTC deadline;
the correction did not reset the budget. The resumed worker revalidated input
hashes and source binding. Baxter's first-session NAV exactly matches #430's
independent certificate; `action-checks.json` also records FDO cash/share
arithmetic and the corrected canonical delivered issuer keys.

No NAS or broker account was accessed; no strategy parameter or production code
was changed. Provider timing, classification and fractional-cash assumptions
remain limitations of these provisional economics.

## Accepted result and resume boundary

Completed January 20, 2016: 2,529 total sessions, 140 new accepted sessions since
June 30. Measurement July 31, 2006 through January 20, 2016:

| Series | Multiple | CAGR |
| --- | ---: | ---: |
| Current Sentinel | 3.632938x | 14.588657% |
| Matched-date reference | 4.560330x | 17.372019% |
| SPY | 1.767745x | 6.198397% |

Account NAV is $336,146.394052429; maximum drawdown is 29.773249%. The
measurement baseline is $92,527.416634823 after the January formation period,
so the reported multiple is not account NAV divided by the original $100,000.
Full twenty-year economics remain incomplete.

`verification.json`: PASS. Independent arithmetic over all 2,529 accepted
sessions, exchange-session coverage, checkpoint integrity, final holdings marked
from the PIT archive, and applied-supplement equality all pass. Wealth Core NAV
reconciliation residual is $2.975e-12; maximum CAGR arithmetic error is
6.772e-15. The 150 held/pending-allocation differences from the reference are
retained rather than asserted away. These checks establish arithmetic and trace
integrity, not absence of all strategy or software defects.

`accepted-daily.jsonl.gz` is derived by `build_series.py`. Its provenance records
313 predecessor overlap rows (six differ) and excludes all 107 superseded
segment-044 rows after July 6. The latest numbered predecessor retry owns each
date; no selection uses profitability. Original per-segment data stays intact.

The normal checkpoint reader reports RESUME_VERIFIED, state commitment
`81a86d899a26c093225de255d4aa6619023f1f49f11c73cc9b3ea414156b6bfe`.
`latest-checkpoint.json` retains the exact local path, SHA256 and size (15,189,178
bytes). Large checkpoint/runtime files stay local; the PR retains compact traces
and identities, not a self-contained copy of the licensed input archive.

Next blocker: DYAX on January 21. The SEC documents $37.30 plus a conditional
$4 right, with legal completion January 22. Although unheld, its leadership
return still needs the complete economic value. `dyax-unresolved.json` records
sources and the missing point-in-time valuation/event treatment. No zero-value,
full-payout or hindsight assumption was added. This is a data/modeling boundary,
not evidence that the controller itself failed.

Verification commands (same Python/PYTHONPATH as above):

```powershell
# From the feature checkout:
python audit/economic-replay-resume-430/build_series.py --root C:/GitHub/stocker/.codex-tmp --output C:/GitHub/stocker/.codex-tmp/economic-replay-merged-ee23c894/verification-series
# From the isolated runtime:
python -B -m research.economic_replay60.verify --segments C:/GitHub/stocker/.codex-tmp/economic-replay-merged-ee23c894/verification-series --reference research/bounded_20y/reference-daily.csv.gz --sfp 'C:/GitHub/stocker/.codex-tmp/pit-prefix-source/PIT input data/SFP_SPY_BIL_PRICE_FACTORS_PIT_ONLY.csv.gz' --archive C:/GitHub/stocker/.codex-tmp/pit-source-5bdc6b39.zip --supplements C:/GitHub/stocker/.codex-tmp/economic-replay-merged-ee23c894/supplements-corrected.json
```

For the resume-reader check, use the worker command with corrected supplements,
`--resume .../segment-045/latest-checkpoint.json`, an unused output directory,
`--seconds 1 --verify-resume`. It validates without advancing or writing a new
segment. For a future actual resume, resolve the DYAX evidence first, omit
`--verify-resume`, select a new segment directory and an explicitly bounded time.
