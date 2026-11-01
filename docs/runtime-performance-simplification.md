# Reducing repeated runtime work

Decision recorded before implementation. Verified base:
`c585b7ff1f5a443720b4ce7585bd4fac36c84118`. Delivery is a feature branch and a
pull request to `flabber1835/stocker:main`. This change does not install software,
contact the production database or broker, or authorize financial operations.

## Validation ownership

Rolling continuation currently restores the predecessor in the runtime and
again in the daily wrapper. The daily writer also calls complete observation
history verification immediately before and after an observation operation
which already performs those checks itself.

The runtime will pass its authenticated predecessor, observer, publication and
binding directly to the existing daily commit operation while retaining the
same writer ownership and publication pin. Observation will expose an internal
typed result containing its already verified predecessor economics and retained
record. The public observation API continues returning the same result. The daily
writer consumes those records immediately instead of verifying them again.
Keep the observation's pre-transition verification, exact append/readback,
canonical state and economic checks, and the runtime's fresh post-commit
checkpoint/authority binding. No verification verdict is reused across a commit,
request or publication pin. The number of necessary checks follows those
boundaries; seven-to-three was an estimate, not a safety requirement or promised
speedup. Further reduction requires separate evidence, not a generic cache.

## Identity and snapshot readers

Build a permanent-security reverse listing index alongside the ticker index.
Reverse lookup still proves its unique effective symbol through the existing
forward ambiguity check. Preserve ordering, listing-boundary proof bytes and
all rename/reuse refusal behavior.

Current main already has a publication-scoped readiness operation and fused
readiness statistics. Reuse those contracts. Within a complete content scan,
validate the generation/manifest/evidence once and use common private typed row
iterators for bars and benchmarks. Standalone readers continue to validate their
own generation. Keep the same retirement/publication pins, complete content and
key hashes, row validation, counts, session coverage and corruption refusal.
There is no persistent or connection-wide verification cache.

## Temporary state allocation

Public session serialization will bound feed arrays without first copying them,
then perform the existing single deep copy per retained series. This preserves
isolation even for nested JSON values and preserves strict canonical bytes and
validation. Synchronous hashing retains its existing private borrowed view.

The normalized session's unused filtered `signal_windows` compatibility map
becomes lazy. Canonical security bars keep positional missing values and remain
the strategy input. Accessing the compatibility map still returns the same
filtered, independently allocated lists. A slice already creates a new list;
remove the redundant surrounding list construction in `signal_window`.

## Execution reads

Index immutable observation order and exact-evidence tuples privately, without
adding serialized/dataclass fields. Preserve existing duplicate-id/key
validation, first-match semantics and fresh indexes on replaced observations.
Legacy mutable sequences retain uncached lookup behavior.

Add optional security and exact-client-key predicates to the command loader.
Revision selection reads only the named plan/security. Reduction settlement
reads only its required keys, retaining missing-key, exact quantity and FILLED
checks. Reconciliation's complete command-history reconstruction is unchanged.
Preserve durable revisions, protected terms, UNKNOWN outcomes and Decimal values.

## Durable data and backups

Assess redundancy against the current normalized shared-session layout,
compressed/shared observation storage, dependency-aware retirement and physical
backup retention. An overlapping physical representation is not sufficient
evidence that its financial provenance or recovery purpose is redundant.
Do not delete commands, fills, event journals, origins, exact inputs, receipts,
action evidence, backup files or WAL as a side effect of this performance work.
Any newly identified removable payload needs explicit dependency and restore
evidence before a deletion-policy change. Record findings here after inspection.

Inspection of current main found that complete session blocks and acquisition
parts already share content-addressed payloads; observation histories already
compress/share series groups. Dependency-aware retirement already releases
unpinned snapshot payloads, unused reference/source bytes and worker scratch.
Current backup retention preserves the selected base and the newest two complete
bases, with the verified producer/WAL chain. These are different recovery
responsibilities. No additional durable payload has yet been proved redundant.
This change therefore removes repeated computation and reads, without adding a
data deletion policy or running database/backup cleanup.

## Preserve the retained book's identity

Current production binds economic implementation and the complete Wealth Core
source tree into the canonical book. A source-neutral refactor must not abandon
that book merely because its file bytes change. Add a closed, independently
qualified structural witness for exactly `sentinel.core.session`,
`sentinel.feed.universe` and `stock_strategy_shared.wealth_core.feed`, rooted in
the complete original bytes at the verified base above. Bind the exact member
set, predecessor hashes, final candidate hashes, schema, no-authority effect and
normalized checker implementation. Only those complete recognized candidate
bytes retain their prior economic contribution. Unknown neighboring edits and
unknown modules keep their actual identity; unknown dependencies still refuse.

The complete runtime/environment attestation continues hashing actual bytes.
Only the strategy's economic contribution uses the reviewed mapping. Preserve
the original economic manifest's implementation/dependency maps, baseline book
identity, historical witnesses and goldens. Qualify the mapping with independent
baseline reconstruction, canonical/economic differential and unknown-byte,
member-set, witness-tamper and removed-guard falsifiers. For snapshot traversal,
extend the existing closed physical-read witness's exact candidate hash and its
mechanical C84 proof; preserve its original baseline, member set and checker.
Refresh only the current full-runtime structural candidate seal after the final
reviewed source is known. None of these witnesses grants broker/deploy authority.

The retained-origin mechanical decision proof must also recognize this exact
strategy-only Wealth Core hash handoff. Reverse only the unique adjacent import
of `wealth_core_source_hash` and its exact call with `package_root` back to the
original `identity.source_hash(package_root)` assignment, then require the
existing complete-module AST equality. Keep the original old/current complete
source hash fences and full runtime seal. Different imports, arguments,
keywords, placement, duplicate blocks or unrelated expressions still refuse;
qualify these cases and an executed removed-proof falsifier before admission.

## Additional simplification findings

Remove the repeated final architecture/deployment documentation blocks, keeping
the first complete copy byte-for-byte. Their dated historical policy statements
retain their original scope; no operating policy changes in this cleanup.

Acquisition reference preparation in `feed/acquisition_parts.py:Parts.put`
currently serializes/hashes the reference payload for `content_sha256`, then
serializes/hashes it again for `reference_sha256`. A later focused change can
reuse the already canonical byte hash while preserving the independent price
fingerprint when prices are present. This is repeated computation, not evidence
that the acquisition part or its reference payload should be deleted. It remains
outside this PR's production source changes.

## Measurements and qualification scope

All measurements below use isolated Python 3.12.13 containers, no external
network and explicit CPU/memory limits. They compare the same logical values.
They are mechanism measurements, not deployed or end-to-end latency evidence.

| Mechanism | Previous | Candidate | Workload / interpretation |
| --- | ---: | ---: | --- |
| Reverse identity lookup | 1.008790 s | 0.000577 s | Median of three trials, 5,000 listings and 500 lookups; existing forward ambiguity check retained. |
| Observation client-key lookup | 0.327676 s | 0.003039 s | 1,000 orders, 21,000 lookups; candidate includes index construction. |
| Public canonical session serialization | 3.548804 s | 2.914669 s | Single wall-time samples, 5,000 securities by 260 observations, exact dictionary equality. |

The serialization probe's traced peaks were 56,853,864 and 56,643,200 bytes.
The old implementation replaced per-series copies incrementally, so this result
supports reduced traversal time, not a substantial peak-memory improvement.
The lazy compatibility history removes eager allocation when unused; the
canonical positional histories remain intact.

The final rolling continuation test counts four complete history-verification
calls: initial authenticated closure, observation before/after, and the fresh
committed closure. This removes three duplicate passes from the prior seven.
Both persisted-content corruption and a deliberately omitted readback are
exercised. A single total verification is not claimed.

During early validation, compiler witnesses changed while read-only test
processes were still running. Their retained errors are not accepted results.
The Windows checkout also contained CRLF-converted copies of committed LF
sources. Before final qualification, restore only files whose normalized bytes
exactly match their Git blobs, then hold all production source/witness bytes
fixed for fresh validation. Historical goldens and baseline witness contents
remain byte-identical to Git.

Final qualification uses the common flags
`-q -ra --tb=short -p no:cacheprovider`; the final focused/identity/compatibility
runs also use `--maxfail=3`. Commands below run with Python 3.12.13 and isolated
PostgreSQL 17 in the test lens built from the verified runtime image and the
repository's hash-locked test dependencies. The source mount is read-only,
network is disabled, memory/no-swap caps are 768--1,536 MiB, and CPU caps are
1--1.5. An immutable Linux copy with per-file hash checks avoids repeated Windows
filesystem metadata overhead. The existing historical correction registry is
included as a test input; no retired market-data source is re-enabled.

Core allocation/feed regression: 95 passed, two pre-existing golden-result
xfails. Their original reason remains `intentional golden result-hash drift;
one authorized re-pin pending`; no fixture was changed.

```sh
python -m pytest tests/sentinel/test_state_hash_allocations.py tests/sentinel/test_canonical_session_kernel.py tests/sentinel/test_production_state.py tests/wealth_core/test_feed_stream_validation.py tests/wealth_core/test_issue_286_ineligible_holding_exits.py tests/wealth_core/test_golden_fixture.py -q -ra --tb=short -p no:cacheprovider
```

Economic identity and independent reconstruction: 124 passed. Complete retained
source admission and full-source seal: 97 passed. Exact original strategy and
data semantics identities remain unchanged; full runtime hashes remain actual.

```sh
python -m pytest tests/sentinel/test_performance_source_basis.py tests/sentinel/test_identity_source_hash_bookkeeping.py tests/sentinel/test_production_decision.py tests/sentinel/test_economic_implementation_boundary.py -q -ra --tb=short --maxfail=3 -p no:cacheprovider
python -m pytest tests/sentinel/test_backed_paper_source.py tests/sentinel/test_transition_registry.py tests/sentinel/test_financial_source_boundary.py tests/sentinel/test_readiness_work_source_seal.py -q -ra --tb=short --maxfail=3 -p no:cacheprovider
```

Execution/reconciliation/revision recovery: 239 passed. Current protected-order
terms and funding: 104 passed. Executed stale-index, security-filter and empty-key
mutants were detected independently of their passing baselines.

```sh
python -m pytest tests/sentinel/test_execution_read_efficiency.py tests/sentinel/test_execution_contract.py tests/sentinel/test_journal_and_reconcile.py tests/sentinel/test_two_phase.py tests/sentinel/test_projection_and_executor.py tests/sentinel/test_unknown_absence_finality.py -q -ra --tb=short -p no:cacheprovider
python -m pytest tests/sentinel/test_order_terms_journal.py tests/sentinel/test_limit_day_execution_wiring.py tests/sentinel/test_limit_day_plan_cash_funding.py -q -ra --tb=short -p no:cacheprovider
```

Feed/identity/storage: the initial selection had 136 passing cases and 17 setup
errors from concurrent witness edits. The frozen-source 48-case retry below
covers every affected case and all current physical-proof tests. Counts overlap;
they must not be added as distinct cases. The original errors and interrupted
Windows-mount runs are retained in local qualification logs and are not accepted
qualification results. Scanner, ambiguity, retirement, content corruption and
invalid pin-reuse falsifiers pass.

```sh
python -m pytest tests/sentinel/test_identity_reverse_index.py tests/sentinel/test_feed_universe.py tests/sentinel/test_historical_symbol_identity.py tests/sentinel/test_reused_symbol_identity.py tests/sentinel/test_rolling_snapshot_storage.py tests/sentinel/test_rolling_readiness_fusion.py tests/sentinel/test_rolling_snapshot_verification_scope.py tests/sentinel/test_normalized_streaming.py -q -ra --tb=short -p no:cacheprovider
python -m pytest tests/sentinel/test_rolling_readiness_fusion.py tests/sentinel/test_rolling_snapshot_verification_scope.py tests/sentinel/test_physical_read_source_basis.py tests/sentinel/test_identity_reverse_index.py -q -ra --tb=short --maxfail=3 -p no:cacheprovider
```

Final continuation coverage focuses on the changed append/commit branches rather
than unrelated service-status fixtures. The commands retain positive canonical
equivalence, actual read counts, mutation/refusal controls, rollback, lost replies,
writer ownership, post-commit cutoff and interrupted-book recovery.
The observation/daily selection passes 77 cases; the focused runtime/recovery
selection passes all seven cases, including the shock and both crash parameters.

```sh
python -m pytest tests/sentinel/test_shadow_observation.py tests/sentinel/test_rolling_daily.py::test_daily_advances_pending_book_and_matches_canonical_transition tests/sentinel/test_rolling_daily.py::test_failed_write_rolls_back_record_and_checkpoint tests/sentinel/test_rolling_daily.py::test_lost_commit_reply_recovers_once tests/sentinel/test_rolling_daily.py::test_final_write_rechecks_authority tests/sentinel/test_rolling_daily.py::test_writer_lock_excludes_continuation -q -ra --tb=short --maxfail=3 -p no:cacheprovider
python -m pytest tests/sentinel/test_rolling_runtime.py::test_daily_runtime_continuation_and_bounded_restart tests/sentinel/test_rolling_runtime.py::test_publication_and_writer_locks_span_candidate_and_authority_commits tests/sentinel/test_rolling_runtime.py::test_postcommit_cutoff_crossing_cannot_issue_authority tests/sentinel/test_rolling_recovery.py::test_interrupted_book_matches_continuous_production_run tests/sentinel/test_rolling_recovery.py::test_recovery_crash_keeps_exact_candidate_without_retransition -q -ra --tb=short --maxfail=3 -p no:cacheprovider
```

Python syntax (29 changed Python files), strict UTF-8/JSON and permanent test responsibility checks pass
(13 owners, 808 test modules, zero unowned). `git diff HEAD --check` passes.
Historical certification, NAS qualification, deployment and broker activation
remain separate from this PR.

## Acceptance

Use focused regressions and executed falsifiers for verification/corruption,
immutable ownership, identity ambiguity, replacement indexes, query scope,
retry/recovery and canonical state/decision equivalence. Measure operation counts
and representative isolated timing where feasible. Do not infer an end-to-end
speedup from a smaller lookup benchmark. No golden fixture or historical source
witness is repinned. Actual runtime identities continue covering actual bytes;
any retained-book compatibility addition must use the existing closed,
independently qualified structural-transition mechanism.
