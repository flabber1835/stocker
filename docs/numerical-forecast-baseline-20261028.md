# Numerical forecasting baseline — 2026-10-28

## Decision and scope

The owner requested a numerical baseline for the mathematical allocation model,
using only existing Alpaca and free OpenFIGI sources. This study measures a
forecast, not an account, Core, Sentinel or execution replay. No production code,
service, database, broker account endpoint or trading authority is involved.
Small matrix construction and regression run privately as research calculations;
there is no reason to stage another hosted financial replay. Only code and
synthetic tests are delivered through research PR 542. Market payloads remain
private, with hashes and provenance retained in the separate research case.

## Frozen first specification

Before fetching prices, select 64 distinct asset IDs from the completed
2026-10-03 Alpaca/OpenFIGI diagnostic feed. Rank by SHA256 of
`numerical-baseline-001:<asset_id>`. Preserve the selected names without
performance-based replacement. Verify current active US-equity Alpaca identity
and free OpenFIGI Common Stock, ADR, REIT, partnership or royalty-trust mapping.
Exclude incompatible or ambiguous mappings explicitly. SPY is a context series,
not a sampled target. Fewer than 32 eligible price series is an insufficient
first baseline, not permission to redraw the cohort.

Retrieve daily SIP bars from Alpaca for 2024-01-02 through 2026-10-27 inclusive,
with both `raw` and `split` adjustments and an explicit symbol as-of date.
Use only the existing provider credential configuration. The collector permits
GET assets/bars and anonymous POST OpenFIGI mapping; it cannot call account,
orders, positions, activities or databases. Fixed request/time/byte bounds and
complete unique pagination apply. Save actual provider replies, request metadata
and hashes without credentials. Do not substitute Sharadar, Yahoo, a paid feed,
news, fundamentals or an LLM. Missing or invalid observations remain missing.

Two separate heads predict from close t:

1. Next session's raw open-to-close price return: `C[t+1]/O[t+1]-1`.
2. Next session's split-adjusted close-to-open **price gap**:
   `split_O[t+1]/split_C[t]-1`. This is not a dividend-inclusive wealth return.

Features available by close t are fixed: split-price 5/21/63-session momentum,
21/63-session close volatility, 63-session price drawdown, log current volume
relative to its trailing 21-session average, current intraday return and price
gap, SPY 21/63 momentum and 21 volatility, and 63-session SPY beta/correlation.
Require 127 consecutive valid common-market observations; do not forward-fill.
Each head is scaled by its own trailing 21-session population standard deviation
(floor 0.001). Training residuals are returned to raw-return units for reporting.

Use pooled ridge with training-only centering/scaling, unpenalized intercept and
fixed lambda=1 in `mean(squared_error) + lambda*sum(beta**2)`. There is no parameter
search. Beginning January 2026, refit monthly using only labels realized before
that month's first target session; at least 126 preceding realized target dates
are required. Score each prediction once in chronological 2026 months, against
zero and the same admissible training mean. Do not use test months to choose
features, lambda, sample members, cutoffs or model selection.

Report pooled and monthly MSE, MAE, squared-error skill against each comparator,
direction accuracy, calibration slope, and coverage of an explicitly nominal
80% training-residual interval. Cross-sectional observations are dependent;
report daily-average loss differences with a fixed five-lag Newey-West standard
error, and do not interpret row counts as independent sample counts. No CAGR,
drawdown, portfolio optimizer or replacement recommendation is inferred.

## Interpretation limits

The initial input check refused exact same-session raw/split return equality.
Actual provider replies contain 794 unequal ratios; all 37,818 paired bars admit
one positive OHLC scale factor when each published split price is allowed its
half-cent rounding interval. Exact provider examples remain private. Admission requires intersecting
the four scale-factor intervals with half-cent tolerance (plus 1e-9 arithmetic
epsilon). This is an input precision check, not a return correction. Preserve
the initial refusal and diagnostic; never alter the provider prices or labels.
The maximum observed raw/split intraday ratio difference is about 8.04 basis
points. Split-price features and gap targets inherit this measurement noise.

This cohort was retained in October 2026 and rechecked using current metadata;
it is survivor-conditioned, not the historical investable universe. Historical
provider revisions, current mappings and the researcher's knowledge of this
period prevent an unseen-out-of-sample claim. Split ratios preserve comparable
price units but gap labels still include ex-dividend price effects; no total
return or entitlement reconstruction is claimed. SPY context is not a sector
label. A one-day forecast test cannot certify multi-day crash protection,
transaction-cost value, joint tail probabilities or portfolio performance.
Negative skill is a valid outcome: it leaves the allocation optimizer without
a qualified expected-return forecast rather than justifying threshold tuning.

## Verification proportionate to this change

Target numerical correctness, monthly label cutoffs, future-data mutation,
missing-session adjacency, asset identity and endpoint/credential boundaries.
Use synthetic inputs for tests. Review actual source manifests and independently
recompute reported forecast metrics from saved prediction rows. No historical
Core/account replay and no broad production test suite is needed.
