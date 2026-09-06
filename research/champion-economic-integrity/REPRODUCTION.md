# Reproduction and evidence retention

Date: 2026-09-06. Branch: `research/champion-certification-economic-integrity`. Readiness: **HOLD / outcome E**. Scope: original-output comparison, source/intent audit, bounded state recovery, three preregistered one-factor controls, and independent offline probes.

## Exact archives and checkpoints

All listed attempts are attempt 1. Digests apply to the downloaded ZIP bytes.

| Evidence | Run; source; artifact | ZIP SHA256 |
|---|---|---|
| Original candidate | 34007704385; ba74e79490beb8950611b1d17f5d124833b3d91e; 9981966560 | 4860751ea45f7480f785e927bc4cebba1c8be3783b354d186ce059d6fb09a841 |
| Original certificate | 34014048220; 27bb992087182c42c3c051e62bf837895f5d2ab7; 9985958324 | e20652e5d0b083590c828cfc271739e64ea6e3a91fd1329365d95ce15f076f08 |
| Older capacity comparison | 33993610034; 372e2e40a8f65e6992de36dfabe8a98e5c3417ad; 9977902550 | 5543ac25ac4696198a3e2e4c30ec45f594a08f9504dc8edcee7e0e63850a37a2 |
| Six-source/history collection | 34041287501; a50a78357ee477f34329dceba5ccc2fce6ad4196; 9991751468 | 2d1ba513508755b9ad2c378dcec5b6c3012e9f71d87fb4e8b16576a087e756fa |
| Five bounded observations | 34042141867; b0a3033d83584541f4d6f306ecee27e318d29a59; 9992417046 | 25f80f5378348f6c500513f3c9ff0bf959909910c26a8c3789b1bd25bf948b5c |
| Pinned collector fixture | 34043631885; 8ff8343d67c54dd4df758c5e7f42a45f671f25e7; 9992424691 | 6a8c81f0e8ce01103d79ba8b1f064857f5e10a25f93e3e7d7f09f2c633ca8b57 |
| Complete offline publication | 34044202728; d342842550e177cc8e4f006956da8f987a970bbf; 9992592953 | 7928b4f5e0bcb249e7c1f56172866d5601d80f3afdbb90e7eae3b9ea37c97f67 |
| Additional core publication | 34044212525; 33aacbf8c27a9c7c4c0248653b51ec0a62238fed; 9992595534 | ff32a8edb4da639f01076cc8b199df13e413818a9e6c8e0fbe8c9702215cda35 |

Runtime: `887f479b15ad861313da666ad698034d3847121c`. Replay and offline Actions validation use Python **3.12.14** and the runtime's hash-locked requirements. Installed packages are retained in `evidence/bounded-prefix/python-environment.txt`.

Profile: `strategy9-e3-research-champion-v1`; SHA256 `1101e99ae9ca327278d79d5334556ca01bbc167e2cb3410ab4902b89550e5c26`.

Corpus: `5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`.

Canonical manifest: `cfa94043084c1cbd83230b5a7225baa45b526797db4581c192561e0fb82ab5b0`.

Package: `ghcr.io/flabber1835/stocker-canonical-pit@sha256:f05e40d9e1bff53ae50507719b5f589fb01b6184c79eceef800ddc2548f6209c`.

## Durable evidence and the two manifests

Complete publication commit **ede62f51d2047394b8b1fa089a6cb848beffa2c7** contains **142 hash-listed evidence files**, including original complete measured daily paths, original certificate JSON, source histories, executable-rule enumeration, full-path first differences, run/artifact metadata and logs, all five bounded state streams, generated programs, independent checks, source probes and collector fixture.

Its `research/champion-economic-integrity/evidence/MANIFEST.json` has SHA256 **1368456ce1603c16241d65ba0ecd11a6c47333fdad693f62627a5602dbde047d**.

Core publication commit **14ba19b7ec26201d65de271a7b35556b2c6bb95b** supplies a second manifest covering **89 core evidence files**. Its manifest SHA256 is **b1c0f06a586c2b91a6af4c8e56cc6f49983887ac8929e7c5183533a8060b940a**. All 89 common payload files have the same size and digest in both publications. The 53 additional full-publication files remain in Git history and in the branch tree. The newer 89-file manifest does not enumerate those extra files.

Use the complete publication's immutable manifest to verify all 142 files. This command verifies the bytes directly from that Git commit:

```bash
python - <<'PY'
import hashlib, json, subprocess
commit = 'ede62f51d2047394b8b1fa089a6cb848beffa2c7'
base = 'research/champion-economic-integrity/evidence/'
def read(name):
    return subprocess.check_output(['git', 'show', f'{commit}:{base}{name}'])
raw = read('MANIFEST.json')
assert hashlib.sha256(raw).hexdigest() == '1368456ce1603c16241d65ba0ecd11a6c47333fdad693f62627a5602dbde047d'
manifest = json.loads(raw)
for name, item in manifest['files'].items():
    data = read(name)
    assert len(data) == item['size_bytes'], name
    assert hashlib.sha256(data).hexdigest() == item['sha256'], name
print('Verified', len(manifest['files']), 'immutable evidence files')
PY
```

Actions artifacts have 90-day retention. Committed evidence preserves the cited audit findings beyond that window. The larger full original candidate role/path journal remains identified by its original artifact and source/corpus hashes; it is not included in the 142-file audit bundle. The canonical market dataset remains identified by its GHCR digest.

## Re-run the offline analysis using existing evidence

Use an environment with the pinned runtime's dependencies and Python 3.12.14. The following commands reuse the committed observation files:

```bash
E=research/champion-economic-integrity/evidence
WORK=$(mktemp -d)
cp -a "$E/bounded-prefix" "$WORK/prefix"
python backtester/validate_champion_economic_prefix.py \
  --root "$WORK/prefix" \
  --original-candidate "$E/original-paths/candidate" \
  --original-certified "$E/original-paths/certified"
python backtester/summarize_champion_economic_prefix.py --root "$WORK/prefix"
echo "Offline results: $WORK/prefix"
```

Outputs include `baseline-reproduction.json`, `controlled-replay-identities.json`, `economic-attribution.json`, `controlled-replays.csv`, per-case entitlement/capacity observations and file hashes.

The validator maps the two promoted original-report columns explicitly, verifies all retained case payload hashes, requires 147 observed sessions and zero failed arithmetic checks per case, rechecks observer-stripped AST equality and compares 30 original daily columns across the three measured dates. Tolerances are recorded in its result.

The analyzer finds the first eligible/ranking/order/fill/share/cash/NAV differences, distinguishes unexercised dividend checks and records over-capacity observations separately from interpretation of actual deferrals.

## Exact-source synthetic and collector fixtures

Expose the exact source trees:

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

The first fixture extracts the exact functions and reproduces dividend/open-equity and PDS evidence-availability defects. The second calls the exact evidence collector only. A passing fixture records that the defective behavior was reproduced; it issues no final certificate.

## Exact historical observation workflow

The observation workflow is `.github/workflows/champion-economic-prefix-audit.yml` at **b0a3033d83584541f4d6f306ecee27e318d29a59**. Its original run **34042141867** completed all five observations and failed in the original report-column postprocessor. Successful offline publication **34044202728** repaired that postprocessor using the same observation bytes. No historical replay was repeated for the repair.

The workflow pins the two source checkouts, runtime, dependencies and corpus package. It executes `backtester/champion_economic_prefix_audit.py` in each exact source tree for cases `candidate`, `certified`, `certified_capacity_off`, `certified_dividend_1` and `certified_candidate_types`. Its fixed endpoint is 2006-08-02, capital is $100M, warmup starts 2006-01-03 and measurement starts 2006-07-31. Each case records the exact changed dimension and generated/normalized-AST hashes.

For a deliberate reproduction of the historical observation itself, GitHub can rerun the exact original workflow commit:

```bash
gh run rerun 34042141867 --repo flabber1835/stocker
```

That exact historical workflow also reproduces its known postprocessing KeyError. Retrieve the new attempt's observation artifact and run the corrected offline validator above. Original attempt 1 remains the evidence authority for this investigation. Ordinary continuation should consume the retained evidence.

## Failure and recovery history

Run 34042141867: all economic observations succeeded; report-column postprocessor failed. Run 34042966069: publication stopped on the predecessor's overall failure flag. Run 34044013414: log download failed at the signed redirect. The authenticated request was scoped to the GitHub origin; publication 34044202728 then passed baseline validation, source probes, attribution and durable commit. Additional core publication 34044212525 also passed. No failure in this sequence required an economic-code change or another historical replay.

## Interpretation and continuation

The prefix proves two exercised causal mechanisms and one unexercised dividend-lag control. It does not quantify the full CAGR gap or prove full-horizon terminal/dividend/P&L accounting. The source fixtures expose separate correctness defects. The 60-rule economic inventory still contains explicit F-class contract decisions.

Continue from the latest audit branch. Resolve those intended-contract decisions, repair the demonstrated defects, test the exact generated Champion for accounting/causality/resume correctness, then execute a newly specified full certification replay. Parameters, initial capital and production/main remain frozen during this investigation.
