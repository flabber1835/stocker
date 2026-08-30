# Retained research causal-timing certification runbook

## Scope and immutable authorities

This certification executes the retained research strategy through the existing strict-PIT transformation chain and applies causal instrumentation only to the final generated source.

Certified bounded window:

- Warmup start: `2006-01-03`
- Measurement start: `2006-07-31`
- End: `2007-12-31`
- Canonical dataset ID: `strict-pit-2006-01-03-2007-12-31-08db292b78f0968b`
- Dataset hash: `08db292b78f0968b149ec033671b5c5df62ad98a4b2692bcc5dfa575585fa4e6`
- Manifest SHA-256: `008f768539c8e6d0e5f2f01a05dab1baf93560c2ffeb7ca7b1521b1a236263e1`
- Package: `ghcr.io/flabber1835/stocker-canonical-pit@sha256:37b41e3b91a8e26cfa3030039467ca94d71d0090839dae48e290453d7a17eadb`
- Pinned production source: `887f479b15ad861313da666ad698034d3847121c`

The package pointer and every package member are verified before execution. Strategy code has no dataset-construction authority.

## Executable chronology

For each canonical session `T`, the final generated replay performs these phases in order:

1. Activate the runtime causal clock at `T` and validate that the current observation group contains only `T`.
2. Update the right-aligned rolling price, momentum, recent-return, volatility, and ADV state using non-negative session lookbacks.
3. Resolve strict-prior issuer, security-type, sector, listing, liquidity, and eligibility state as of `T`.
4. Rank the current eligible universe and update prior-selection leadership returns.
5. Settle prior receivables, apply canonical splits effective at `T`, read terminal action signals effective at `T`, and mark open Wealth Core equity.
6. Execute previously pending orders at the raw open of `T`. Close-generated orders require a signal index strictly less than the fill index. A terminal signal effective at the open may execute at that same open.
7. Accrue dividends effective at `T` from the prior-close as-traded quantity.
8. Mark closes, update peaks, evaluate trailing stops, evaluate age-119 review logic, calculate Wealth Core equity, and calculate breadth.
9. Generate close-`T` exit and admission orders. These cannot fill during `T`.
10. Derive the native close target and LD-RC close target.
11. Mark NAV using allocation made effective at the open from the prior close's pending target.
12. Emit the canonical session trace, then persist the close targets for the next valid session open.

## Runtime causal-access boundary

The causal runtime rejects any strategy request dated after the active session. The boundary covers:

- Direct market-observation groups.
- Cached corporate-action maps.
- Metadata, security type, issuer, and sector timelines.
- Canonical session hashes.
- Rolling-window indices.
- Vectorized benchmark calculations, which are recomputed from `frame.loc[:T]` and compared at every session.
- Position entry dates, ages, review dates, and fill dates.
- Pending allocation targets and current effective allocation.
- Portfolio and NAV trace timestamps.

The full canonical package may be loaded into process memory. Strategy-visible retrieval remains session-scoped. Prefix invariance and future poisoning cover preprocessing and caches whose values are computed before the chronological loop.

## Canonical session trace

Every session emits deterministic canonical JSON bytes. Floats are represented by `float.hex()`. The trace contains:

- Exact eligible security IDs.
- A SHA-256 fingerprint and canonical byte length for every current-session source and derived signal tuple.
- Exact ranking order.
- Exact selected positions and complete held-position state.
- Pending orders, close-generated orders, fills, decisions, splits, dividends, and terminal signals.
- Wealth Core open/close equity and cash state.
- Breadth and recent leadership state.
- Native target and native-controller state.
- LD-RC desired target and controller state.
- Prior-close pending allocation, current-open effective allocation, and next-close target.
- Control NAV and SPY NAV.

Prefix and poison comparisons compare the decompressed trace line bytes directly through each cutoff. A digest is recorded only after direct byte equality succeeds.

## Prefix-invariance cutoffs

The suite runs a physically truncated dataset and strategy endpoint at each cutoff:

- `2006-07-05` — initial eligible universe and first close orders.
- `2006-07-06` — initial next-open fills.
- `2006-07-28` — last warmup session.
- `2006-07-31` — measurement start.
- `2006-08-15` — MED age-119 review and stop-precedence session.
- `2006-08-16` — MED next-open exit and held CSX split.
- `2006-09-07` — existing research/production divergence boundary.
- `2006-09-29` — quarter-end reporting.
- `2007-02-21` — held ACLI split.
- `2007-08-16` — bounded-window maximum drawdown.
- `2007-09-28` — quarter-end reporting after the ETELY split boundary.
- `2007-12-31` — bounded endpoint.

For each cutoff, every trace byte through the cutoff must equal the full-window baseline.

## Future-poisoning domains

For every cutoff before the endpoint, the structurally valid future is deterministically replaced in all populated domains:

- Raw opens and closes.
- Signal closes.
- Reported and raw-compatible volume.
- Split ratios and dividends.
- Issuer, security type, SIC/FF12 sector, listing, tradeability, and metadata admission.
- Canonical corporate-action values and evidence fields.
- Terminal settlement terms.
- Benchmark levels/returns.
- Historical cash factors.

Security IDs, tickers, session dates, required columns, positive price constraints, positive volume constraints, and admissible enumerations remain structurally valid. Each poison run records source rows after the cutoff and poisoned-row counts. A populated domain with zero poisoned rows fails certification.

## MED targeted regression

The bounded trace must contain exactly one MED age-119 witness:

- Entry session: `2006-02-24`.
- Review/stop-precedence session: `2006-08-15`.
- Chronological age: `119` sessions.
- Review basis: split-adjusted execution-session open, expected `6.8`.
- Entry-session close initializes the position peak and never replaces the review basis.

The witness records whether the trailing stop has precedence, whether the position is underwater relative to the execution basis, and whether the review qualification condition is satisfied.

## Static leakage audit

The final generated executable source is parsed and scanned for:

- Negative `shift`, `pct_change`, `diff`, or `numpy.roll` periods.
- Centered rolling windows.
- Backward filling.
- Forward `merge_asof` joins.
- Current TICKERS snapshot authority or survivor-last-date filtering.
- Future-index metadata joins.

Classified safe uses:

- Right-aligned rolling benchmark calculations, runtime-recomputed from each prefix.
- Ring-buffer references at `gday`, `gday-21`, and `gday-126` or other non-negative lookbacks.
- `bisect_right` metadata resolution with effective date no later than `T`.
- Per-session `numpy.lexsort` ranking.
- Chronologically appended peak, return, and controller-state arrays.

Classified reporting-only uses:

- Whole-quarter knowledge in `_quarter_last`, which controls progress printing only.
- Post-run CAGR, drawdown, Sharpe, and trailing-window metrics, which are never fed back into strategy state.

The retained research strategy consumes canonical terminal action signals. It does not consume terminal settlement terms. Settlement-term poisoning therefore proves economic non-dependence for this implementation.

## Local or isolated-run command

After extracting and verifying the immutable package:

```bash
python backtester/run_research_causal_certification_v2.py \
  --canonical-dataset backtester-results/canonical-pit-2006-2007 \
  --output backtester-results/research-causal-certification
```

The isolated workflow is `.github/workflows/backtester-research-causal-certification.yml`.

## Fail-closed gates

Certification terminates unsuccessfully on any of the following:

- Immutable pointer, package digest, member hash, manifest hash, or dataset-hash mismatch.
- Future-dated runtime access.
- Non-chronological session or position-age state.
- Same-session fill from a close-generated signal.
- Current-open allocation different from the prior close's pending target.
- Prefix trace-byte mismatch.
- Future-poison trace-byte mismatch.
- Populated future domain left unpoisoned.
- MED regression mismatch.
- Static leakage blocker.
- Missing evidence artifact.

No failure is suppressed or converted to a warning.

## Bounded-proof limitations

- The proof applies to the immutable 2006–2007 package only.
- The bounded trace contains no defensive allocation transition. Pending-close to next-open allocation timing is still asserted on every session and covered by a synthetic unit test.
- No held position consumes a terminal settlement term during the bounded window. Terminal action timing is exercised; settlement terms are an economically inert input to retained research.
- The identical suite must run against the completed immutable 20-year package before claiming a 20-year causal certification.
