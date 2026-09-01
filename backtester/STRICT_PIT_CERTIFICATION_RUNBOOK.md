# Strict-PIT financial certification runbook

This runbook defines the active certification paths on `research/backtester`.
Historical diagnostic workflows and earlier source pins are superseded by the
current paths below.

## Active authorities

- Backtester branch: `research/backtester`
- Production source pin: `c851386fa4dddcf2e2533af3a1d313c38220b7f2`
- Warmup start: `2006-01-03`
- Measurement start: `2006-07-31`
- Measurement end: `2026-07-31`
- Canonical PIT dataset hash:
  `f9fb220871ad4152549d31a5da6e0dbcdd327dc7b05843764511b0e800ddb19b`
- Canonical package:
  `ghcr.io/flabber1835/stocker-canonical-pit@sha256:4f53e51d8171aab8a8ac9df90e116d27b0f9b54f95629154685ea8a2394c1265`
- Canonical dataset status: `PASS`
- Unresolved canonical corporate actions: `0`

The branch pointer `backtester/data/canonical-pit-20y.json` is the admission
authority for the dataset. Replay jobs must validate that pointer, package
digest, manifest and member hashes before strategy execution.

## Financial-grade invariants

Every certified replay is fail-closed on the following boundaries.

### Causality

Signals are formed after session close and may affect execution only at a later
tradeable raw open. Historical identity, security type, issuer grouping, listing
state, exchange and sector authority come from session-effective PIT evidence.
Current Sharadar TICKERS metadata has no historical economic authority.

### Terminal actions

The retained research 20-year entry point includes terminal grace semantics in
its canonical transform. A terminal event with incomplete consideration remains
an economic claim during the declared grace period. It is not liquidated at a
stale prior mark on the event session. Split and dividend entitlement ordering
is part of this same canonical path.

Production uses the pinned shared Wealth Core terminal-settlement implementation
and authenticated terminal corrections.

### Valuation

A financially certified measurement session must have resolved Wealth Core NAV.
A stale or estimated mark may exist as operational evidence but cannot enter the
certified NAV, controller history, CAGR, drawdown or other financial metrics.
Any unresolved measurement-session NAV terminates certification.

### Leadership witness

A selected recent-leadership security must have an economically resolved next
close observation. Missing next-close observations are not imputed as zero.
Certification stops until the return can be established from the authenticated
path.

### Dividend cash timing

Dividend entitlement enters economic NAV on the ex-date. Spendable cash uses a
fixed conservative settlement lag of **15 market sessions** in financial-grade
research and production replays. The lag is part of the certified execution
semantics and must not be changed silently.

### Capacity

The production certification path refuses an executable pending order when its
share quantity exceeds **10% of the prior 20 observed sessions' average share
volume** for that security. Only prior-session volume is used. Current-session
completed volume cannot authorize an opening fill because it is not known at the
open.

This is a certification ceiling. A run that crosses it has not demonstrated
financially supportable execution at the configured capital and must fail.

### Costs and performance fields

CAGR and maximum drawdown are computed from the authenticated daily NAV path.
The existing internal field named `sharpe` is a legacy annualized arithmetic
mean-return-to-volatility statistic unless an evidence bundle explicitly states
a risk-free subtraction. It must be described in reports as
`annualized_return_volatility_ratio`. It is not evidence of a conventional
excess-return Sharpe ratio.

A future schema migration may replace the legacy field with an excess-return
Sharpe computed from the authenticated causal Treasury series. Until then,
financial sign-off must not call the legacy statistic "Sharpe".

## Production certification

The active 20-year production chain is:

1. `.github/workflows/backtester-production-strict-pit-20y.yml`
2. `.github/workflows/backtester-production-strict-pit-year-worker.yml`
3. `backtester/run_production_strict_pit_20y_checkpointed.py`
4. `backtester/run_production_strict_pit_20y.py`
5. exact pinned production source at the SHA above

The annual chain runs 2006 through 2026 as a strict predecessor-linked sequence.
Each year authenticates its checkpoint, canonical dataset identity, production
source, workflow/source identity and predecessor certificate. Genesis also
requires uninterrupted-versus-resumed equivalence evidence.

A failed year stops certification. Restart uses the authenticated predecessor
checkpoint; it cannot silently rebuild strategy state from a target portfolio.

## Research certification

The active retained-research workflow is:

`.github/workflows/backtester-research-only-20y.yml`

It executes:

`backtester/run_research_strict_pit_20y.py`

The workflow pulls the exact admitted canonical package, verifies it, compiles
the generated canonical research source, confirms terminal grace is integrated,
and verifies the financial-grade audit contract before accepting output.

Warmup output must be labelled `CAGR=N/A`. Measurement begins on `2006-07-31`.

## Permanent regression gate

`.github/workflows/backtester-financial-causality-gate.yml` is the permanent
backtester correctness gate. It must:

- check out the exact pinned current-main production closure;
- verify the pinned production file hashes;
- compile the complete active backtester and retained backtester service;
- prove the runtime `backtester` package identity;
- compile the canonical retained-research transform;
- verify the financial-grade source contracts;
- run the complete `tests/backtester` regression suite.

A green replay with a red financial/causality gate is not certifiable.

## Canonical dataset facts

The admitted 20-year package currently records:

- 31,820,893 observation rows;
- 18,948 securities;
- 5,176 sessions;
- 32,167 metadata-timeline rows;
- 253,076 action rows;
- 10,652 terminal rows;
- 0 unresolved corporate actions.

Unknown historical security-type or issuer evidence remains explicit and is
handled by fail-closed eligibility semantics. Unknown evidence is not promoted
into positive eligibility by a present-day metadata fallback.

## Evidence required for financial sign-off

A financial-grade result requires all of the following from one immutable source
identity and one admitted canonical dataset:

1. financial/causality gate PASS;
2. canonical dataset validation PASS;
3. exact production source identity PASS;
4. resolved NAV on every measurement session;
5. no unresolved recent-leadership return used by the controller;
6. no capacity-ceiling violation;
7. authenticated annual predecessor/checkpoint chain for production;
8. complete daily and metric output hashes;
9. restart-equivalence evidence at genesis;
10. explicit terminal, split and dividend audit evidence.

Any failure means the financial performance result is uncertified.

## Files that cannot become historical authority

Do not use current Sharadar TICKERS fields, local temporary files, uncommitted
workspaces, package tags without a digest, or stale prior marks as historical
economic authority. Every economic input used for certification must be
content-addressed or carried in the authenticated canonical package and available
as of the simulated decision boundary.
