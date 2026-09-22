# Mechanical fitness investigation evidence

Production base: `ee23c894c97a2c4023654ce3a56a62728f5b061e`, freshly fetched and
unchanged at publication. Feature branch: `codex/economic-results-diagnosis`.
Git/gh PR delivery against `flabber1835/stocker:main`; no self-merge.

Read [findings and priorities](../../docs/sentinel-mechanical-fitness.md) and
[pre-experiment registration](../../docs/economic-results-diagnosis.md).
No production change, golden repin, NAS access or real broker access.

## Inputs and scope

- Completed diagnostic history: PR #434,
  `7b5dda96ce4235363c5c6ded3974d3fb2970f432`.
- Frozen reference: `2a1bd486241ae524eac395490b135cc79715e497`,
  `research/champion-certification-20y-v1/results/34544522249-1/`.
- Parameter helpers: PR #433,
  `f2a50c7b6ff4c9686f49b6eb53863e8e2b9959bb`.
- Owned impairment rule: PR #432,
  `7250ce3d65cc38a103989d460fe3c557a38343c8`.
- Original checkpoint/runtime/input bindings in each `window-*.json.gz`.
  Original licensed archive and checkpoints remain local; derived observations
  contain no per-security prices or holdings. Replay requires those inputs.
- `summary.json` records all accounting input object hashes and the independently
  retained final-checkpoint hash. CAGR uses the retained 365.2425 day-count.
- `phase-summary.json` records helper/source hashes, fixed cases/profiles,
  checks and all economic summaries. Helpers are extracted from the pinned Git
  objects to an isolated temporary package. Production imports come from this
  branch; no production code or constants are patched.

Historical accounting: 5,032 measured closes; both actual NAV paths reproduce
within `1.36e-14` relative error. Four crossed allocation/Core tapes are attribution
diagnostics, not runnable strategies. Full Sentinel vs Native includes both
divergence and recovery effects. Ledger checks establish cash continuity and
aggregate final shares; they do not independently validate every daily stock mark.

Synthetic panel: four formation lengths, seven frozen markets, six profiles;
3,360 scenario transitions, 168 account paths. Core is canonical, never reseeded
from a manually chosen book. This remains in-memory research plus production
projection, not the durable execution service. Formation length shifts both
book age and the fixed market waveform/calendar phase.

## Exact local commands

Executed from `C:/GitHub/stocker/.codex-tmp/economic-results-diagnosis`, using
the existing local Python 3.12 environment. Its dependencies required filesystem
permission outside the sandbox for the numerical/controller runs. No dependency
installation or network broker request was made.

```powershell
$taskPython = 'C:/GitHub/stocker/.codex-tmp/bounded-feed-venv/Scripts/python.exe'
$env:PYTHONPATH = "$PWD;$PWD/shared;C:/GitHub/stocker/.codex-tmp/classification-check-runtime"
& $taskPython -m research.economic_diagnosis.analyze --checkpoint C:/GitHub/stocker/.codex-tmp/economic-replay-merged-ee23c894/segment-084/checkpoints/checkpoint-2026-07-31.json.gz --output audit/economic-diagnosis
& $taskPython -m research.economic_diagnosis.phases --output audit/economic-diagnosis
& $taskPython -m pytest research/economic_diagnosis/test_analysis.py research/economic_diagnosis/test_mechanics.py -q -p no:cacheprovider --junitxml=audit/economic-diagnosis/unit-tests.xml
& $taskPython -m research.economic_diagnosis.mutations --output audit/economic-diagnosis/mutations.json
& $taskPython -m research.economic_diagnosis.verify_results
& $taskPython -m compileall -q research/economic_diagnosis
& $taskPython tools/validate_test_responsibility.py --base ee23c894c97a2c4023654ce3a56a62728f5b061e --output audit/economic-diagnosis/test-ownership.json
git diff --check
```

The three passive historical windows used these arguments. Scratch paths must be
new on a rerun; original checkpoints/artifacts are never overwritten.

```powershell
$taskArchive = 'C:/GitHub/stocker/.codex-tmp/pit-source-5bdc6b39.zip'
$taskSfp = 'C:/GitHub/stocker/.codex-tmp/pit-prefix-source/PIT input data/SFP_SPY_BIL_PRICE_FACTORS_PIT_ONLY.csv.gz'
$taskSupplements = 'C:/GitHub/stocker/.codex-tmp/economic-replay-merged-ee23c894/supplements-continued.json'
& $taskPython -m research.economic_diagnosis.window --harness C:/GitHub/stocker/.codex-tmp/merged-20y-runtime-da7b64a9 --checkpoint C:/GitHub/stocker/.codex-tmp/economic-replay-merged-da7b64a9/segment-017/checkpoints/checkpoint-2011-07-25.json.gz --archive $taskArchive --sfp $taskSfp --supplements $taskSupplements --scratch C:/GitHub/stocker/.codex-tmp/mechanics-window-2011 --end 2011-08-10 --output audit/economic-diagnosis/window-2011.json.gz
& $taskPython -m research.economic_diagnosis.window --harness C:/GitHub/stocker/.codex-tmp/merged-20y-runtime-ee23c894 --checkpoint C:/GitHub/stocker/.codex-tmp/economic-replay-merged-ee23c894/segment-057/checkpoints/checkpoint-2018-09-18.json.gz --archive $taskArchive --sfp $taskSfp --supplements $taskSupplements --scratch C:/GitHub/stocker/.codex-tmp/mechanics-window-2018 --end 2018-10-15 --output audit/economic-diagnosis/window-2018.json.gz
& $taskPython -m research.economic_diagnosis.window --harness C:/GitHub/stocker/.codex-tmp/merged-20y-runtime-ee23c894 --checkpoint C:/GitHub/stocker/.codex-tmp/economic-replay-merged-ee23c894/segment-084/checkpoints/checkpoint-2026-01-07.json.gz --archive $taskArchive --sfp $taskSfp --supplements $taskSupplements --scratch C:/GitHub/stocker/.codex-tmp/mechanics-window-2026 --end 2026-04-20 --output audit/economic-diagnosis/window-2026.json.gz
```

## Results and falsifiers

- 13 targeted tests pass, including independent small dollar-book accounting and
  observed-state interventions that identify the binding controller conditions.
- Four deliberately broken accounting implementations fail their independent
  tests: overnight ownership, transition fees, entry-gap timing and cash
  compounding. No production guard was introduced in this research PR.
- 3,760 current-controller state/decision parity closes pass.
- 224 canonical-state restart comparisons pass; 1,344 controller and 1,344
  account restart comparisons pass, including the owned-rule adapter.
- All split decisions/observations match controls. Exact pretrade split value
  conservation passes. Later lot-granularity effects of $0-$7.06 are retained.
- 196 comparisons to prior economic summaries pass (140 against #433, 56
  against #432; the current-policy comparisons overlap).
- 101 original-runtime historical decisions/economics match exactly:
  12 in 2011, 19 in 2018, 70 in 2026. Window wall times: 78.41s, 108.03s, 357.78s.
- Syntax and permanent-test-ownership validation pass. These research tests run
  explicitly with the commands above; ordinary CI is not represented as running
  the entire research panel or certifying its economics.

No relevant production regression suite was rerun because production files are
unchanged. No broad Wealth Core suite, full suite, threshold optimization or
full-history alternate-policy run was performed.

During harness development: a duplicate session keyword was corrected before
any phase result completed. The initial post-split final-NAV equality requirement
failed because whole-share granularity legitimately changes; it was replaced
with exact value conservation before trading plus explicit post-trade reporting.
The 80-session golden economic anchors were preserved, not edited. The attribution
script's first CAGR draft used 365.25; final output uses the retained 365.2425
convention. None of these corrections changes production policy or data.

## Decision boundary

This evidence supports a finite improvement program, not automatic promotion of
PR #432/#433 or economic certification. Known classification/action data issues,
provider finality and NAS/deployed qualification remain unresolved. No claim of
optimal expected CAGR follows from a small deterministic panel or one history.
