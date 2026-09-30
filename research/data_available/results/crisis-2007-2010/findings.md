# Findings: simplify the data interface, retain useful state

The experiment completed 959 measured sessions, 2007-03-15 through 2010-12-31,
in 42.9 minutes. It began with 300 feature-only sessions and $50,000 cash in
each arm. This is an unscaled Wealth Core comparison, not a Sentinel deployment
or a twenty-year backtest.

## Result

The baseline, stateful snapshot and rolling-300 owned-peak variants produced
identical daily equity, held identities, fills, fees, pending-order counts and
stop counts throughout the measured interval. Each ended at $74,594.86: a 49.19%
return, 11.11% annualized return and 46.55% maximum drawdown. Each made 222 fills
and incurred $509.04 of modelled costs. SPY returned -1.92% over the matched
interval, with a 55.20% maximum drawdown.

This is observed trading equivalence on this dataset, not bitwise equivalence
of all features. The snapshot eligible-universe count differs on 441 sessions,
by at most three securities. The experiment explicitly replaces mixed-precision
running calculations with direct window calculations and checks complete
required observations. Those differences did not change a selected holding here.
The 300-session owned-peak expiry did not change a trade in this interval; that
does not establish equivalence over every possible holding path.

The account-only rules generated 3,778 fills and $7,578.07 in modelled costs,
with 113 unresolved valuation sessions. Their final modelled equity is
$38,184.37, but the report deliberately withholds full-path return and drawdown.
Fourteen terminal settlements used the canonical last-mark convention rather
than exact terms, with $29,357.93 aggregate settlement notional. This is not a
clean performance ranking against the other arms. It does demonstrate much
greater turnover under the proposed simple top-20/top-40 rules.

## What this supports

Keep useful ownership and order state while simplifying the market-data
interface to the current window. The controlled replay supports investigating
this change without simultaneously replacing the holding rules. Isolated tests
show that a corrected snapshot can restore eligibility without replaying the
portfolio, and that known account equity can allow unaffected names to proceed
despite a held-name snapshot gap.

It does not prove hands-off provider or broker operation. The source is a
retrospectively revised Sharadar tape, with existing reviewed event terms and
classification assumptions. It contains no archived daily provider vintages.
The offline account adapter uses canonical book equity; it has no independent
broker valuation with which to resolve the 113 gaps. It does not simulate the
exact proposed prospective Alpaca account behavior.

An unheld FJDI/FJDIU-like anomaly could become an isolated eligibility exclusion
instead of a whole-universe refusal under this design. Today's exact GO bundle
has not been replayed through this prototype. Backup budgets, worker deadlines
and CI failures are independent issues. Before production adoption, replay those
actual acquisition failures against the new boundary and test forward account
reconciliation. No production behavior is changed by this branch.

Alpaca's paper simulator also cannot be assumed to replace economic accounting:
its documented dividend exclusion and dated staff statement about unsupported
splits are linked in the design document. A second paper account is therefore
an execution experiment, not an established total-return reference book.

## Validation and provenance

Implemented and measured from verified main
`b812db40bcb68b06a9d79eb1ad8e7a6885180671`; replay implementation is present in
research commit `feebc926`. `identity.json` contains the actual launch-time
source and data hashes. Reporting and additional tests were improved while the
replay ran; the run, policy, account and canonical economic files were frozen.
The delivery branch subsequently incorporates main's PR #458; its Wealth Core
economic implementation is unchanged from the measured base.

Commands executed in Python 3.12 using `sentinel-test:acquisition-data-local`,
with network access disabled and `/work:/work/shared` on `PYTHONPATH`:

```sh
python -m pytest research/data_available -q -p no:cacheprovider --tb=short
# 33 passed
python -m research.data_available.mutations
# 8 deliberate defects detected
python -m research.data_available.run \
  --archive /inputs/pit-source-5bdc6b39.zip \
  --supplements /inputs/owned55-formed-20y-run/qualification-001/supplements.json \
  --output /work/artifacts/data-available-crisis-v2 \
  --end 2010-12-31 --seconds 7200
# COMPLETE, 959 sessions
```

The final report independently checked the daily-file hash, interval, return
and drawdown calculations. All ten research Python files passed AST parsing.
The baseline driver also matches the canonical public runner's state, ledger
and equity in the targeted differential test. A discovered research bug that
confused failed entry filters with missing observations was demonstrated by two
failing tests, corrected, and included in the defect campaign before this run.

`summary.md`, `result.json`, `yearly.csv`, `equity.csv` and `comparison.png`
contain aggregate results. Missing values remain blank/gaps in the equity file
and chart. The three stateful curves overlap exactly. The raw observations,
supplements and full daily holding trace remain local; they are not published.
