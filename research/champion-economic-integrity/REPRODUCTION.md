# Reproduction and evidence retention

Date: 2026-09-06. Investigation branch: `research/champion-certification-economic-integrity`.

Scope: source inspection, original-output comparison, bounded exact-prefix recovery, three preregistered one-factor controls, and offline accounting/causality probes. Final certification is on hold under `CERTIFICATION_ECONOMIC_SPEC.md`.

## Exact source and artifact identities

| Evidence | Run / source | Archive SHA256 |
|---|---|---|
| Corrected candidate | run 34007704385; source ba74e79490beb8950611b1d17f5d124833b3d91e; artifact 9981966560 | 4860751ea45f7480f785e927bc4cebba1c8be23b3783b354d186ce059d6fb09a841 |
| Formal certificate | run 34014048220; source 27bb992087182c42c3c051e62bf837895f5d2ab7; artifact 9985958324 | e20652e5d0b083590c828cfc271739e64ea6e3a91fd1329365d95ce15f076f08 |
| Earlier capacity diagnostic | run 33993610034; source 372e2e40a8f65e6992de36dfabe8a98e5c3417ad; artifact 9977902550 | 5543ac25ac4696198a3e2e4c30ec45f594a08f9504dc8edcee7e0e63850a37a2 |
| Source/history collection | run 34041287501; source a50a78357ee477f34329dceba5ccc2fce6ad4196; artifact 9991751468 | 2d1ba513508755b9ad2c378dcec5b6c3012e9f71d87fb4e8b16576a087e756fa |
| Bounded attribution | run 34042141867; source b0a3033d83584541f4d6f306ecee27e318d29a59 | Exact archive identity recorded by publication in evidence/artifacts-34042141867.json |
| Offline publication | run 34042966069; source ca70d61ac363e34a1c5019f0c814a21c3408ff62 | Publication result and durable file hashes are recorded in evidence/MANIFEST.json |

The authoritative artifact digests are also retained in the API metadata under `evidence/artifacts-*.json`. Verify the actual archive digest on retrieval; do not derive a download path from an artifact title.

Runtime: `887f479b15ad861313da666ad698034d3847121c`; Python 3.12.14 for the Actions replay. Dependencies are installed from the runtime's hash-locked requirements; `evidence/bounded-prefix/python-environment.txt` records installed packages.

Profile: `strategy9-e3-research-champion-v1`; hash `1101e99ae9ca327278d79d5334556ca01bbc167e2cb3410ab4902b89550e5c26`.

Corpus: `5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`.

Package: `ghcr.io/flabber1835/stocker-canonical-pit@sha256:f05e40d9e1bff53ae50507719b5f589fb01b6184c79eceef800ddc2548f6209c`.

Manifest hash: `cfa94043084c1cbd83230b5a7225baa45b526797db4581c192561e0fb82ab5b0`.

## Existing evidence first

The publication workflow commits selected raw evidence and all derived audit data under `research/champion-economic-integrity/evidence/`. This includes the original complete daily paths, original summaries, original candidate generated source, certificate JSON evidence, five bounded state-stage streams, generated/instrumented programs, baseline-reproduction proof, fills, accounting checks, source-lineage histories, and machine-readable comparisons.

GitHub Actions artifacts have 90-day retention. The committed evidence bundle preserves the audit's cited facts beyond that artifact window. The full original candidate role/path journal is larger than this bundle; its original artifact hash and source/corpus identities remain recorded for deliberate regeneration. The canonical market dataset remains identified by its GHCR digest.

After cloning the investigation branch, verify the durable bundle:

```bash
python - <<'PY'
import hashlib, json
from pathlib import Path
root = Path('research/champion-economic-integrity/evidence')
manifest = json.loads((root / 'MANIFEST.json').read_text())
for name, item in manifest['files'].items():
    path = root / name
    assert path.stat().st_size == item['size_bytes'], name
    assert hashlib.sha256(path.read_bytes()).hexdigest() == item['sha256'], name
print('Durable audit evidence verified:', len(manifest['files']), 'files')
PY
```

## Offline first-divergence and accounting analysis

Copy the retained bounded evidence into a scratch directory, then run the versioned analyzer:

```bash
cp -a research/champion-economic-integrity/evidence/bounded-prefix /tmp/champion-economic-prefix-review
python backtester/summarize_champion_economic_prefix.py \
  --root /tmp/champion-economic-prefix-review
```

Outputs include `economic-attribution.json`, `controlled-replays.csv`, per-case open-entitlement and over-capacity observations, and file hashes. These operations do not fetch a new corpus or execute a historical replay.

The analyzer compares chronological eligible sets, durable rankings, recent-leadership selections, pending orders, fills, held quantities, cash, dividend receivables, open/close NAV and allocation. Its numerical comparison tolerances are explicit in source. Full-precision state streams remain available for stricter independent comparisons.

## Exact-source defect probes

Expose the candidate and pinned runtime source trees, using existing Git objects or the retained source archive:

```bash
git worktree add --detach ../champion-candidate-source ba74e79490beb8950611b1d17f5d124833b3d91e
git worktree add --detach ../champion-certified-source 27bb992087182c42c3c051e62bf837895f5d2ab7
git worktree add --detach ../champion-runtime-source 887f479b15ad861313da666ad698034d3847121c
E=research/champion-economic-integrity/evidence
python backtester/champion_economic_source_probes.py \
  --candidate "$E/bounded-prefix/candidate/economic-generated.py" \
  --certified "$E/bounded-prefix/certified/economic-generated.py" \
  --classifier ../champion-candidate-source/backtester/research_champion_corrected_classification.py \
  --corrections ../champion-candidate-source/backtester/data/champion-historical-security-type-corrections-v1.csv \
  --adapter ../champion-runtime-source/shared/stock_strategy_shared/wealth_core/adapter.py \
  --output /tmp/champion-source-probes.json
python backtester/champion_certification_claim_probe.py \
  --source-file ../champion-certified-source/backtester/certify_backtest_result.py \
  --replay-evidence "$E/original-certificate/pit-v2/pit-replay-evidence.json" \
  --output /tmp/champion-collector-claim-probe.json
```

The first probe uses exact extracted functions and synthetic fixtures for the shared open-dividend boundary and PDS evidence availability. Its success means the defects were reproduced. The second tests the evidence collector only and never invokes a finalizer or issues a certificate.

## Deliberate bounded-replay reproduction

The exact pinned workflow is `.github/workflows/champion-economic-prefix-audit.yml` at `b0a3033d83584541f4d6f306ecee27e318d29a59`. Re-running its existing run reproduces the original workflow commit:

```bash
gh run rerun 34042141867 --repo flabber1835/stocker
gh run watch 34042141867 --repo flabber1835/stocker
```

This is a deliberate reproduction command, not a request to repeat completed work during the current investigation. Its attempt number changes, so artifact retrieval must use the actual attempt-specific name. The publication workflow currently references original attempt 1; preserve that identity when analyzing the original audit.

The workflow sets the original full dataset end to 2026-07-31, warmup to 2006-01-03, measurement start to 2006-07-31, and capital to the original $100M. A read-only observer stops after 2006-08-02. The two baseline cases recover evidence; the three controls alter only execution participation, dividend settlement lag, or unknown-security-type classification respectively.

Each case records source/runtime/profile/corpus identities, exact generated-source digest, normalized economic AST digest and observer-stripped AST equality. The original candidate program is compared with the retained generated source; both baseline measured prefixes must reproduce the three original daily records through 2006-08-02.

## Interpretation and resumption

No control is a replacement certified result. The short prefix identifies mechanisms and first events; it does not provide a full 20-year CAGR decomposition or a full-horizon terminal/P&L proof. The classification control inherits candidate evidence limitations. The open-entitlement probe is an independent completeness test in addition to recorded-ledger arithmetic.

Resume future work from the latest audit branch checkpoint and its durable manifest. Resolve the explicitly recorded F-class contract questions, repair demonstrated defects with mutation-sensitive tests, and complete exact-Champion accounting/causality proof before any new final certification. Champion parameters and initial capital remain frozen throughout this investigation.
