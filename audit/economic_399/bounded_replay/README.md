# Bounded historical replay evidence

Status: **REFUSED — no twenty-year economic result**. This is the completed
bounded pilot task, not completed economic certification.

Verified main base: `48f88fd4f3957c0dfc264e2eef2e35ecd753c9c1`.
Production reviewed/run: `624395dd04c48af7de3a8930cfd586ca2cc81245` (PR #425).
Harness source: `e0b029369c9dcdf63ee76f5443bc880158a67545`.
Design decisions preceded code in `docs/bounded-production-replay.md`.

## Findings and disposition

| Finding | Severity/scope | Evidence and disposition |
| --- | --- | --- |
| RSAS lacked settlement consideration | Historical input blocker, locally resolved for this scenario | SEC-backed $28 terms enter on 2006-09-18; daily output passes that date. `research/bounded_20y/supplement.py`; independent production settlement oracle verifies 173 shares yield $4,844. |
| TRZ and MVK lack settlement consideration | Blocking historical input gaps | Retained 2006-10-05 rows have `PIT_ACTION_INCOMPLETE:MISSING_CASH_PER_SHARE`; held quantities are 173 and 78. `blocking-terminal-inputs.json` and `pilot/result.json` inside the archive. |
| Unresolved equity cannot become certified returns | Locally verified refusal | `sentinel/shadow_observation.py:1518` refuses 2006-10-06. No guard disabled and no carried-price proceeds substituted. |
| Full replay exceeds requested local budget at sampled speed | Runtime constraint | 144.14s input verification/warmup; 48 completed sessions; total 336.28s including failed transition. Rough full-window projection 5.6h before margin. No full run launched. |

These observations establish input deficiencies, not a newly demonstrated
production algorithm defect. Completing this scenario requires authoritative
per-share TRZ/MVK cash/stock consideration, applicable share class, effective
date and availability timing. Bind those facts to the retained security IDs,
apply through canonical terminal handling, and require resolved accounting on
2006-10-06. Further missing inputs may appear later. No additional merger
research was attempted after this refusal, consistent with the owner's limit.

## Exact run

Host paths below were under `C:/GitHub/stocker/.codex-tmp`:

```powershell
docker run -d --name sentinel-bounded-20y-pilot --network none --memory 4g --cpus 2 --entrypoint python -e PYTHONPATH=/work:/work/shared -e PYTHONDONTWRITEBYTECODE=1 -v C:/GitHub/stocker/.codex-tmp/bounded-production-replay-worktree:/work:ro -v C:/GitHub/stocker/.codex-tmp:/inputs:ro -v C:/GitHub/stocker/.codex-tmp/bounded-production-replay-evidence:/evidence -w /work sentinel-test:ci -u -m research.bounded_20y.run --archive /inputs/pit-source-5bdc6b39.zip --prefix /inputs/pit-prefix-evidence/canonical-required-prefix --sfp '/inputs/pit-prefix-source/PIT input data/SFP_SPY_BIL_PRICE_FACTORS_PIT_ONLY.csv.gz' --output /evidence/pilot --capital 100000 --pilot-seconds 600 --max-seconds 7200
```

Image ID: `sha256:5d227c4740ad66a33e9719047cb368f60b9546e77cd6cc19f17695d3d2048146`.
This image supplied dependencies; the reviewed source was mounted read-only and
verified against 305 production Python hashes before execution. It is not a
newly built deployable image. No network, PostgreSQL, broker or NAS was used.
Container exit 2, OOMKilled false. Logs and exit state were retained, then the
stopped disposable container was removed.

## Targeted validation

Run in the same cached offline image with the source mounted read-only at
`/work`, `PYTHONPATH=/work:/work/shared`, `PYTHONDONTWRITEBYTECODE=1`:

```text
python -m pytest -q -p no:cacheprovider tests/sentinel/test_bounded_historical_performance.py
24 passed in 4.88s

python -m research.bounded_20y.mutations
5/5 killed: source_binding, source_uniqueness, settlement_cash,
projection_guard, deadline_guard

python -m pytest -q -p no:cacheprovider tests/sentinel/test_image_layout.py::TestTheBuildContextCarriesWhatTheDockerfilesCOPY
5 passed in 3.09s (SENTINEL_REPO_ROOT=/work)
```

Host Python 3.12 checks:

```text
python tools/validate_test_responsibility.py --output /evidence/ownership.json
PASS: 496 test modules; zero unowned
python -m pyflakes research/bounded_20y tests/sentinel/test_bounded_historical_performance.py
PASS
ast.parse of all five harness Python files and the test module
PASS: six files
git diff --check
PASS
```

`SHA256SUMS.json` binds the retained archive and every member. It contains exact
input/source identities, 48 daily outputs, the complete refusal/held-book record,
blocking source rows, container state, logs and validation results. Prior golden
and failed-run artifacts are unchanged. No twenty-year CAGR, multiple,
production/reference equality, NAS qualification or certification is claimed.
