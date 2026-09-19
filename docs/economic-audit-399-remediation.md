# Economic audit 399: remediation and certification evidence

Base: `aff4461d9af6d4a7367018768fda18d948958b49`, reviewed against
[issue 399](https://github.com/flabber1835/stocker/issues/399) and its retained
audit evidence. This record separates implementation acceptance, historical
economic/reference compatibility, provider capability acceptance, and deployed
NAS qualification. None implies the others. Overall certification is BLOCKED
until all required evidence has an explicit passing disposition.

The NAS never passed GO. Preserve failed attempts; no operational book is
migrated, no certificate is issued, and broker mutations are outside this work.

## Numeric decisions (before implementation)

F2: the intended-dollar and available-cash bounds use the same exact quotient
over decimal-spelled price, cost and capital. Floor once to whole shares; no
epsilon can create a share outside either bound. This corrects the documented
budget semantics even where the frozen research implementation differs.

F9: serialized canonical close equity is economic input, so retain its full
canonical precision as already done for opening equity. Round only in a human
display. The exact current close remains independently retained in the shadow
NAV history. Do not weaken the long-only/unlevered projection guard to absorb a
rounded denominator. Acceptance covers both sub-cent directions and the real
warmup, admission, next-open fill, restart and target path.

F10: the inclusive stop compares decimal-spelled signal close with exactly
seven tenths of the owned peak using rational arithmetic, independent of binary
multiplication and the ambient Decimal context. Ownership, next-open execution,
split basis and cooldown timing remain unchanged. Production source identity
must change; the frozen research source remains historical evidence.

The old golden fixture is not an oracle for these corrected boundaries. Retain
its bytes and explain every economic/reference delta before approving any new
compatibility reference. Test success is not authority to repin a golden.

## Recovery and evidence decisions (before implementation)

Expired preparation attempts (F4) transition through the existing immutable
expiry protocol while holding the request identity lock, then a single fresh
successor may be enqueued. Live leases and published receipts are preserved.

Historical reference continuity (F3) compares metadata and symbol identity at
the same prior decision date. Only the new session may use a newly effective
name. Commands keep their original label as provenance; current instrument
identity follows the permanent security and broker asset, not that old label.

Retained action enumeration (F15) starts from authenticated publication
commitments, including declared empty intervals. A missing coverage row or
payload is an integrity refusal. Sparse dividend evidence (F16) establishes
the affected held security set from those complete source/identity commitments
before requesting prices; unheld payers cannot create a price requirement for
unrelated holdings. Missing evidence for a held payer still refuses.

The current complete reference bundle and retained aliases establish every
possible label of a held permanent identity. An unresolved source payer may be
ignored only when its label is outside that set. A held identity missing from
both reference sets, or an unresolved label that could name a held identity,
still refuses; no symbol fallback assigns economic ownership.

F11 uses one exact non-exponent decimal encoding for numeric digest inputs;
equal values share an identity regardless of trailing zeroes or exponent.
F7 retains UNKNOWN after absent reads until affirmative terminal evidence is
available. Observation may recover positive facts, but absence and elapsed
local time grant no new command, cancellation, or finality authority.

F17/F18: account-bound read-only recovery owns durable command obligations,
not the current shadow target. If the shadow publication is ahead of a retained
cycle, do not rederive or authorize that obsolete target. Observe and reconcile
the original commands with the complete action history from their earliest
basis date. The same history is required for planless and adopted-generation
recovery, including fully exited positions. Fresh target creation retains every
current shadow, generation, time and execution-authority check.

## Finding ledger

### Pre-NAS follow-up decisions

The prior-session notional leadership share undergoes a source split before
same-session terminal consideration, matching the canonical corporate-action
ordering. Multiply terminal consideration by that source share multiplier
before translating the retained prior raw/signal basis. A delivered-security
split is already reflected in its current price and contractual exchange terms.
The corrected champion economic schema advances to `audit399-decimal-terminal/2`;
the old schema and historical reference remain evidence, not authority.

Native fill acceptance must also compare the incoming set with durable history
before publishing an observation. An individually coherent replacement set of
new activity IDs must not add a second economic copy of already retained fills.
Validate the immutable union against the exact order's cumulative quantity and
notional; complete lifetime history must include all previously retained IDs.
Retain contradictions as diagnostics and publish no normal fills or watermark.
This strengthens local consumers without accepting provider completeness.

Restore must distinguish an uninitialized rolling publication from missing
origin evidence. Surviving strategy lineage without its origin is corrupt,
including when no daily checkpoint has yet been written. It cannot be reported
as a valid empty restore. Numeric and execution-time parser refusals retain
the same account-bound raw diagnostic as native identity/type refusals.

The Trading Activity SSE reference requires `since_id` with `until_id`; the
candidate's lone `until_id` query is invalid. With no independently accepted
initial native cursor, repeat the same valid timestamp-bounded request and
require identical contents. Name this evidence a repeated bounded snapshot,
not fixed-event-frontier replay; version its unaccepted semantics to V2 and
explicitly report no fixed-frontier or late-publication finality. Keep every
production acceptance/capability bit false. This repairs the wire request and
removes an overstated evidence claim without inventing a genesis cursor.

F1 permits a uniform adjusted-price scale only when every overlapping pair
admits one common positive factor within the source's published mill precision.
Intersect rational rounding intervals; do not compare rounded ratios or use a
relative epsilon. Raw economics, action history, identity and overlap keys
remain exact. This supersedes the older exact-ratio presentation requirement.

F2 also computes the 5% admission budget from decimal-spelled equity before
converting to the canonical float representation. Binary multiplication must
not move an exactly affordable budget below its whole-share boundary.

F8: a recovery overlay must check accepted fill-history capability before
calling any nested fill producer. An unavailable producer yields an incomplete
observation with no terminal watermark, not an accepted empty fill history.

F12/F13: an incident's immutable payload contains only fields in its identity;
the transient leader holder is not part of that incident. Logical enqueue
conflicts are reported separately and cannot starve independent queued alerts.
Each dispatcher has a unique process incarnation. Delivery results must match
both that owner and the claimed attempt number, while its lease is current.
An expired/older attempt cannot change the successor's delivery state.

F5: once execution has begun, a callback failure or terminal refusal does not
end observation of durable obligations. Enter read-only reconciliation first.
After all obligations settle, a refused old intent is superseded; it cannot
mint replacement revisions. A later eligible session can prepare a fresh plan.

F14: restore validation dispatches by publication format and authenticates
rolling origin, latest checkpoint, shadow chain, attestation and current sealed
snapshot, plus the publication-owned retained action closure. This is structural
validation in a read-only session and grants no freshness, GO or transport
authority. Retired historical price payloads are not required for restore.

F19: native trade events retain asset, side, explicit execution type and raw
provider provenance. Join them to exact order identity before publication;
reject impossible timestamps, duplicate identities, excess quantity and
inconsistent cumulative gross notional. A complete lifetime fill observation
must equal the order's filled quantity. An incomplete set remains retryable and
cannot publish fills, normal fill alerts or a permanent entitlement amount.
Without an accepted provider average-price rounding contract, a non-exact gross
comparison refuses rather than silently accepting a tolerance. Consumer scans
also require the durable fill quantities/notionals to cover the command book.
Rejected observations and native identity/type/correction parser refusals retain
their raw evidence separately as diagnostics, never economic rows. The diagnostic is
bound to the verified account identity and does not advance a recovery cursor.
Correction/bust events still refuse append-only accounting; retaining them does
not establish correction support or grant producer authority.

C2: prior leadership membership earns the source-bound terminal economic return
before the security leaves the sensor. Cash consideration uses the retained
same-security signal/raw basis; a confirmed write-off earns -100%. A conversion
uses contractual cash plus exchange-ratio times the delivered security's actual
current raw close. Missing terms, a missing current delivered close, ambiguous
terminal events or a missing source price basis refuse. The witness does not
read broker holdings, and source identity changes bind this economic revision.

Corrected admission/opening uses `wealth-core-v5-total-cash-open-sizing-v2`.
The initial compact champion remediation bound `audit399-decimal-terminal/1`;
the pre-NAS split/terminal correction advances it to `audit399-decimal-terminal/2`.
Historical reference metrics remain attached to the original implementation;
neither a previous certificate nor an old restart profile authorizes this one.
This first deployment needs fresh reviewed authority, not a state migration.

| Finding | Required disposition / acceptance surface |
|---|---|
| F1 | Source-precision rebase proof; genuine historical revisions still refuse |
| F2 | Exact intended-dollar whole-share bound; canonical and account projection |
| F3 | Dated rename continuity and historical-command/current-symbol separation |
| F4 | Expired preparation retries converge without erasing failed attempts |
| F5 | Live/uncertain obligations retain recovery after refusal or callback death |
| C1/F6 | Accepted account-bound cash producer, incremental completeness and finality |
| F7 | Missing current order evidence never manufactures terminal cancellation |
| F8 | Every nested activity dependency obeys its accepted capability boundary |
| F9 | Full-precision NAV and independently correct target quantities |
| F10 | Inclusive exact stop, pending exit, restart and next-open economics |
| F11 | Canonical numeric identity in grace and strict recovery completion |
| F12 | Immutable health-incident identity; independent queued delivery progresses |
| F13 | Process-incarnation and per-attempt notification result fencing |
| F14 | Restore validates authoritative rolling state and its dependency closure |
| F15 | Publication-derived complete retained action-coverage closure |
| F16 | Sparse dividend evidence is scoped to affected owned securities |
| F17 | Historical obligations can reconcile after shadow advancement |
| F18 | Planless/adopted recovery retains the command book's action units |
| F19 | Native fill identity, amount, time and complete ownership evidence |
| C2 | Explicit source-bound terminal-return policy for the leadership sensor |
| C3 | Accepted predecessor-incarnation completeness before restored transport |

The ledger also retains issue 400 dependencies where issue 399 explicitly
requires them: missed-session recovery, transient failure classification,
backup/restore lifecycle, deployment entrypoints and bounded operations.
Unsupported provider guarantees must remain visible; they cannot be supplied
by changing a capability flag or by interpreting an empty response as finality.

## Evidence acquired

The retained audit branch was fetched independently. Its unmodified positive
economic acceptance module reproduced 6 failures and 5 passing controls on this
base, using the existing Python 3.12 test image with no network. The failures
are F2 (3), F9 (2), and F10 (1). These are failures of required economic results,
not tests that count a defect reproduction as successful certification.

### Implementation disposition

All numbered findings were reviewed against the retained issue evidence. The
following are local implementation acceptance results, not deployed acceptance:

| Finding | Implemented behavior and positive acceptance evidence |
|---|---|
| F1 | Common source-precision scale accepted; nonuniform revisions refuse (`test_rolling_audit_acceptance.py`) |
| F2/F9/F10 | Independent rational quantity/stop oracles, canonical warmup/fills/restart, full NAV target sizing (`test_economic_boundaries.py`, `test_nav_quantity_precision.py`) |
| F3 | Dated rename advances; settled old command labels do not replace current identity; live conflicting obligations still refuse (`test_rolling_audit_acceptance.py`, `test_historical_command_symbol.py`) |
| F4 | Expired preparation gets one coalesced successor while preserving the failed attempt (`test_operational_snapshot.py::test_expired_first_attempt_gets_one_fresh_successor`) |
| F5 | Actual callback SIGKILL before/after acknowledgement commit retains reconciliation; mixed-refusal runtime remains recoverable (`test_execution_callback_death.py`, `test_automation_runtime.py`) |
| F7 | Repeated complete absence preserves UNKNOWN; later original order/fill recovers with one submission (`test_unknown_absence_finality.py`) |
| F8 | Accepted-capability boundary prevents nested SSE calls for both reachable and forbidden candidate endpoints (`test_recovery_capability_boundary.py`) |
| F11 | Equivalent numeric spellings do not renew cash/position grace or change strict completion (`test_cash_grace_identity.py`, `test_recovery_numeric_identity.py`) |
| F12/F13 | Leader-independent incident identity; stale attempt cannot finish its successor; result writes and per-recipient Web Push writes are fenced (`test_alert_attempt_fencing.py`, operator/outbox regressions) |
| F14 | Read-only restore accepts intact rolling state and rejects altered HMAC/current snapshot (`test_rolling_restore_integrity.py`) |
| F15 | Missing first, middle or latest publication coverage refuses after real retirement (`test_retained_coverage_closure.py`) |
| F16 | Current/retired equity and BIL entitlements price only held payers; ambiguous/missing held identity still refuses (`test_sparse_entitlement_scope.py`) |
| F17 | Old-cycle obligations reconcile after current shadow advancement (`test_historical_cycle_recovery.py`) |
| F18 | Held and fully exited equity/BIL recover retained 2x/3x action units without a current plan (`test_planless_action_units.py`) |
| F19 | Invalid native identity, execution type, quantity, gross notional and time cannot publish economic rows/normal fill alerts; late complete history converges (`test_native_fill_acceptance.py`). Provider acceptance remains open below. |
| C2 | Cash merger, write-off and stock consideration use owned signal basis; missing terms/basis/delivered close refuse (`test_terminal_leadership_return.py`) |

### Test commands and observed results

Commands below ran in the existing `sentinel-test:ci` image, Python 3.12, with
the checkout mounted at `/repo`, an empty fixture `.env`, and
`PYTHONPATH=/repo:/repo/shared SENTINEL_REPO_ROOT=/repo`. Database fixtures start
isolated PostgreSQL instances. No NAS or real broker was used. Each pytest
command used `-q --tb=short --show-capture=no -p no:cacheprovider`.

**96 passed** in the issue-specific positive acceptance run:

```sh
python -m pytest \
  tests/sentinel/test_alert_attempt_fencing.py \
  tests/sentinel/test_cash_grace_identity.py \
  tests/sentinel/test_economic_boundaries.py \
  tests/sentinel/test_execution_callback_death.py \
  tests/sentinel/test_historical_cycle_recovery.py \
  tests/sentinel/test_historical_command_symbol.py \
  tests/sentinel/test_native_fill_acceptance.py \
  tests/sentinel/test_nav_quantity_precision.py \
  tests/sentinel/test_planless_action_units.py \
  tests/sentinel/test_operational_snapshot.py::test_expired_first_attempt_gets_one_fresh_successor \
  tests/sentinel/test_recovery_capability_boundary.py \
  tests/sentinel/test_recovery_numeric_identity.py \
  tests/sentinel/test_retained_coverage_closure.py \
  tests/sentinel/test_rolling_audit_acceptance.py \
  tests/sentinel/test_rolling_restore_integrity.py \
  tests/sentinel/test_sparse_entitlement_scope.py \
  tests/sentinel/test_terminal_leadership_return.py \
  tests/sentinel/test_unknown_absence_finality.py
```

**320 passed** in the strategy/controller regression run:

```sh
python -m pytest tests/champion tests/median5 tests/v5 \
  tests/sentinel/test_economic_boundaries.py \
  tests/sentinel/test_nav_quantity_precision.py \
  tests/sentinel/test_terminal_leadership_return.py \
  tests/wealth_core/test_state_machine.py
```

This run preceded the nine additional terminal policy cases in the 96-test run.
Counts overlap across commands and are not a distinct-test total.

**78 passed** in the entitlement/account-parser recovery run:

```sh
python -m pytest tests/sentinel/test_sparse_entitlement_scope.py \
  tests/sentinel/test_alpaca_boundary_overlay.py \
  tests/sentinel/test_alpaca_activity_sse_accounting.py \
  tests/sentinel/test_p0_recovery_and_staleness.py
```

This run preceded the two additional missing/ambiguous ownership cases.

After adding raw native identity/type/correction refusal diagnostics, **158
passed** with the final parser/reconciler implementation:

```sh
python -m pytest tests/sentinel/test_native_fill_acceptance.py \
  tests/sentinel/test_alpaca_boundary_overlay.py \
  tests/sentinel/test_alpaca_activity_sse_accounting.py \
  tests/sentinel/test_recovery_capability_boundary.py \
  tests/sentinel/test_journal_and_reconcile.py
```

This adds two correction/bust diagnostic cases to the issue-specific selection
(98 cases at delivery). Repeated rejected events preserve one diagnostic and
publish no fill, entitlement or recovery-cursor authority.

**114 passed, 2 existing xfailed** in supervision and historical economics:

```sh
python -m pytest tests/sentinel/test_automation_composition.py \
  tests/sentinel/test_issue_201_automation_financial_grade.py \
  tests/sentinel/test_paper_package_architecture.py \
  tests/wealth_core/test_golden_fixture.py tests/wealth_core/test_terminal.py \
  tests/wealth_core/test_terminal_admission.py \
  tests/wealth_core/test_terminal_opening_causality.py
```

The two existing golden-hash mismatches remain explicitly unresolved; no golden
fixture or xfail was added or repinned. An independent golden-scenario trace
on this revision still produces the audited-main result hash
`11566dc3608fa06644d31aecb90f470ab3c2cec7075b9d32ab84e063a10ecaef`, state hash
`11ee55f9687417d1`, ledger hash `1405d6573c67b811`, 41 events, 24 final positions
and cash `34824.73117999994`. This is a synthetic Wealth Core scenario, not the
corrected V5 champion's full historical replay. The historical-reference cash
delta explanation in issue 399 remains separate evidence.

**234 passed** in the affected operational regression run:

```sh
python -m pytest tests/sentinel/test_journal_and_reconcile.py \
  tests/sentinel/test_automation_outbox.py \
  tests/sentinel/test_operator_monitoring.py \
  tests/sentinel/test_high_impact_durable_remediation.py \
  tests/sentinel/test_automation_runtime.py \
  tests/sentinel/test_automation_service.py \
  tests/sentinel/test_paper_performance_quarantine.py
```

One installed Starlette/httpx deprecation warning was emitted. Changed-code
static checking compiled 60 Python files and found no new pyflakes diagnostics;
75 diagnostics already existed in the corresponding base files. Whole-tree
pyflakes is not clean and is not represented as passing.

Mutation checks (passing unmodified baseline followed by an expected failure):

```sh
python tools/v5_mutation_check.py
python tools/champion_mutation_check.py
python tools/economic_audit_mutation_check.py fills
python tools/economic_audit_mutation_check.py coverage
python tools/economic_audit_mutation_check.py attempt
```

Results: 43 V5 mutations and 4 champion mutations killed. Disabling fill
validation breaks six coherence cases; disabling coverage enumeration breaks
the missing-prior-publication case; removing attempt fencing lets an old worker
finish its successor and fails the acceptance case. These are intentional
mutant failures, not failing delivered tests.

### Remaining certification gates

1. **C1/F6 and F19 provider acceptance remain BLOCKED.** No accepted production
   account-cash/incremental-fill producer, correction/bust semantics or fixed
   interval finality was established. The provider's cumulative-average rounding
   contract also remains open.
   Candidate HTTP fixtures cannot supply these guarantees; production
   capability flags remain false.
2. **C3 restored-incarnation completeness remains BLOCKED.** Structural restore
   validation cannot prove that a provider exposed every predecessor command.
   Keep the restore epoch transport fence until that capability has accepted
   account-bound evidence. The issue's retained physical-restore simulator
   campaign is useful historical evidence, not NAS qualification for this code.
3. **Corrected-profile economic replay remains BLOCKED.** Replay the corrected
   V5/champion identities over authoritative complete historical data, reconcile
   all economic deltas independently, and review a new reference only after
   those results are explained. Prior research metrics cannot be transferred.
4. **NAS qualification remains BLOCKED.** On 2026-09-18 the supplied connection
   `king@kingdom` was reachable, but this session's noninteractive SSH attempt
   returned `Permission denied (publickey,password)`. No remote state changed.
   Once authenticated access is available, inventory deployed image/source,
   failed attempts, current publication/checkpoint/action closure and backup
   evidence using read-only probes. First GO and paper operation require their
   own subsequent evidence and authorization.
5. **Full semantic inventory remains open.** Close the remaining issue 400
   dependencies and compound lifecycle cases, including missed-session
   continuation, recovery after outages, restore/retention and deployed bounded
   operations. The passing targeted tests here do not claim an exhaustive
   economic audit of every source event or provider lifecycle.

Issue 399 must remain open. No economic, operational or provider certificate
is issued by this remediation PR.

### CI integration follow-up

The internal-state lifecycle is a synthetic assembly lab, not provider
certification. Its process-external simulator supplies complete native fills,
so its adapter instance explicitly enables that modeled capability. A companion
assertion verifies that a separately constructed production adapter still has
the capability disabled. This preserves positive lifecycle coverage without
allowing the harness to depend on the former nested-capability bypass.
