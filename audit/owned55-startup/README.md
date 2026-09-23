# Owned55 and $50k formation: local evidence

Date: 2026-09-22. Verified main base:
`ee23c894c97a2c4023654ce3a56a62728f5b061e` (#430), freshly fetched again before
delivery. Branch: `codex/owned55-bootstrap`. Design was committed first as
`bce259745810c46c67777ff132a1a335a83e9cdd`. See the PR head for the reviewed
implementation commit; `implementation-source.json` pins the tested Python files.

**INCOMPLETE / NOT DEPLOYABLE.** Owned55 policy and the independent formation
component are implemented. Fresh GO does not yet acquire formation history or
admit a formed genesis. This is not Stage 1 closure or economic certification.

## What is established locally

- The new production identity applies a 55% ceiling after five severe owned-book
  closes, releases after eight healthy closes, and preserves lower parent
  allocations including independent zero causes. It never changes Core holdings.
- New service, automation, panel and deployment defaults use $50,000. Explicit
  capital remains explicit; source, policy and state identities cannot silently
  relabel old books. Execution uses independently observed account capital.
- The candidate formation wrapper calls canonical feature warmup and kernel:
  252 feature sessions and 126 economic sessions; checkpoints at 0, 1, 47, 63,
  125 and 126 reproduce uninterrupted state exactly. Operational price state
  remains at most 300 sessions. Candidates are explicitly `NOT_ADMITTED`.
- A held security survives a rename and doubles shares at a 2:1 split without
  creating cash. Its dividend becomes a receivable, then cash on the next
  session. Every synthetic session reconciles cash and shares from ledger
  movements. Independent whole-share math uses $50k, not accumulated shadow NAV.
- Rejected duplicate/gapped inputs, changed source/capital, checkpoint tampering,
  and a late failure after book calculations cannot advance the candidate.
- Current controller breadth uses residual-correlation peers, not sector labels.
  A mixed stressed book distinguishes the two and is invariant to sector labels;
  bypassing peer breadth is killed by the test. Exchange labels are also ignored
  by current eligibility, with positive admissions proving the comparison is not
  a vacuous empty book. Future first-session dates and unknown security types
  prevent admission. Historical sector/exchange membership is not a requirement.

## Commands and results

Commands run from the worktree on Windows; Python is
`../bounded-feed-venv/Scripts/python.exe`. Local imports use
`PYTHONPATH=<worktree>;<worktree>/shared` (plus `/scripts` for GO checks).
No command below contacted a broker or NAS. Test groups overlap; counts are not
added together as a coverage claim.

```text
python -m pytest tests/champion tests/median5/test_warmup.py tests/sentinel/test_production_state.py -q -p no:cacheprovider --basetemp=../owned55-bootstrap-tests-a
71 passed in 40.78s

python audit/economic_399/rolling_status/run_local.py test tests/sentinel/test_rolling_initialization.py tests/sentinel/test_rolling_daily.py tests/sentinel/test_rolling_runtime.py tests/sentinel/test_rolling_paper_inputs.py tests/sentinel/test_projection_and_executor.py tests/sentinel/test_shadow_service.py tests/scripts/test_sentinel_go_validate.py tests/champion tests/sentinel/test_historical_formation.py
302 passed, 1 failed in 643.44s

python -m pytest tests/champion tests/sentinel/test_historical_formation.py tests/sentinel/test_authority_static_architecture.py tests/sentinel/test_feed_static_architecture.py tests/sentinel/test_shadow_static_ownership.py tests/wealth_core/test_static_restore_ownership.py tests/sentinel/test_shadow_service.py::test_new_installation_defaults_to_fifty_thousand_across_runtime_callers -q -p no:cacheprovider --basetemp=../owned55-bootstrap-final-unit
96 passed in 148.08s

python audit/economic_399/rolling_status/run_local.py test tests/scripts/test_sentinel_go_validate.py tests/sentinel/test_shadow_service.py
96 passed in 1.06s

python audit/economic_399/rolling_status/run_local.py test tests/sentinel/test_autonomous_deploy.py tests/sentinel/test_automation_runtime.py
76 passed in 4.79s

python -m pytest tests/sentinel/test_historical_formation.py::test_current_controller_uses_correlation_peers_not_sector_labels -q -p no:cacheprovider --basetemp=../owned55-bootstrap-sector-falsifier
1 passed in 20.70s

python -m pytest tests/sentinel/test_historical_formation.py::test_current_eligibility_ignores_exchange_but_requires_first_session -q -p no:cacheprovider --basetemp=../owned55-bootstrap-metadata-test
1 passed in 19.52s

python -m pytest tests/sentinel/test_historical_formation.py::test_rejected_input_does_not_advance_candidate -q -p no:cacheprovider --basetemp=../owned55-bootstrap-late-refusal
1 passed in 2.80s

python -B tools/owned55_startup_mutations.py --output audit/owned55-startup/mutations
8/8 KILLED; original source restored after each case

git diff --check
PASS
Python ast.parse over each changed/new Python file
23 files PASS (hashes in implementation-source.json)
```

The isolated Linux harness uses existing image `sentinel-test:ci`, image ID
`sha256:5d227c4740ad66a33e9719047cb368f60b9546e77cd6cc19f17695d3d2048146`,
`--network none --memory 4g --cpus 2`. It copies the read-only mounted worktree
into the container and runs its local PostgreSQL fixtures.

The one initial Linux failure was a GO fixture reporting $100k when the request
now defaulted to $50k. The guard correctly refused. The positive test now covers
both the new default and explicit $100k; negative fixtures use matching capital
so other faults are not masked. An intermediate Windows GO run had 58 passes and
one POSIX `0600` permission failure; the entire file passed in Linux above.
The original formation test mistakenly named `feed.sessions` instead of
`feed.seen_sessions`; its corrected bounded-state assertion passes. No golden
data was repinned, no xfail/skip added and no production invariant weakened.

## Real archive preview

`tools/historical_formation_preview.py` streams the original archive, not a
prebuilt portfolio. The 378-session slice is 2025-01-29 through 2026-07-31;
formation starts 2026-01-30. Original archive SHA256:
`7d86c6f728f0392516dec5e2a709c16d45b2f46bc139fe7f3d29af25ae4dfce8`.
Dataset identity:
`5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`.
Original archive, supplements and research golden outputs are preserved.

The runner uses the separately frozen sibling `../owned55-formation-runtime`;
348 hashes are in `preview-source.json`. Outputs/checkpoints are retained in
`../owned55-formation-preview`. At publication the preview is still in progress;
do not treat a partial prefix as complete validation. It has a 1,800-second
segment budget and supports `--resume`; never start a duplicate process. Inspect
the process as well as `status.json`: a budget exit leaves the latest daily
status, so `RUNNING` alone is not liveness evidence.

```text
PYTHONPATH=../owned55-formation-runtime;../owned55-formation-runtime/shared
python -u ../owned55-formation-runtime/tools/historical_formation_preview.py --archive ../pit-source-5bdc6b39.zip --supplements ../economic-replay-merged-ee23c894/supplements-continued.json --output ../owned55-formation-preview --seconds 1800
# Only after that worker exits: the identical command with --resume.
```

This archive has research SEP-tape/SEC identities rather than native Sharadar
permatickers. Its classification assumptions and known SILV issuer error on
12 warmup sessions remain explicit. It cannot authorize GO or establish
historically exact economic performance. No July checkpoint will be deployed:
fresh GO must acquire current inputs and build its own book.

## Remaining gates and NAS handoff

1. **P1 / local design and provider contract:** choose historically dated
   classification/identity inputs or an explicitly different prospective startup
   policy using current metadata. Ordinary TICKERS snapshots do not establish
   historical metadata vintages. See `docs/owned55-historical-startup.md`.
2. **P1 / local implementation:** connect formation acquisition, durable progress,
   authenticated formed-genesis admission and publication overlap to actual GO.
   Current `Formation` is a candidate-only component. The cold-seed rejection
   remains intact in `sentinel/shadow_observation.py`.
3. **P1 / local acceptance:** drive empty PostgreSQL through that GO caller,
   interruption/restart, changed inputs, lost acknowledgements and duplicate
   invocation. Prove zero historical broker calls and one authorized current
   execution intent; do not substitute direct kernel tests for this gate.
4. **P1 / data-dependent:** finish and review the unqualified real-data preview;
   resolve source limitations for whichever production policy is selected.
   Research metadata is not an authoritative production source.
5. **P1 / delivery:** green required CI on the final integrated PR; user review
   and merge. This draft must not be deployed as completed historical startup.
6. **NAS-only, after 1-5:** verify final merged source/image identity, $50k reviewed
   configuration, fresh Sharadar publication, backup/restore and resource budgets.
   Run the repository's existing `bash scripts/sentinel-go-validate.sh` from the
   merged checkout and retain its validation bundle. Inspect with
   `bash scripts/sentinel-autonomous-deploy.sh --explain` before the reviewed
   deployment flow. No deployment command was executed for this task.

NAS pass criteria must include the exact fresh 252+126 session axis, selected
metadata policy/source commitments, authenticated formed state and controller
cursor, actual paper starting capital and whole-share projection, restart
continuity, no historical orders, execution identity/reconciliation evidence,
and successful bounded-resource/restore checks. Any missing or stale required
evidence is NO-GO. Ordinary green CI cannot grant economic certification.
