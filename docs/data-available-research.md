# Data-available strategy research

Research decision, 2026-09-30. Base: b812db40bcb68b06a9d79eb1ad8e7a6885180671.
This experiment is isolated from production selection and deployment. The owner
requested both simpler data handling and simpler rules bounded by 300 sessions.

## Question and variants

Owner clarification: simplicity is the primary objective: one daily 300-session
snapshot plus the current account. Include `account300` as a comparator. Its
decision function consumes only that snapshot and a normalized account view.
The other three arms preserve progressively more existing behavior. Freeze these simple rules
before measuring results (no parameter search): rank positive-momentum, nonnegative
recent-return eligible stocks by the existing durable score; buy from the top 20;
keep existing positions while they remain in the top 40 and above 70% of the
300-session signal-price high; sell otherwise. Twenty follows the existing book
size; forty is a predeclared 2x retention band to reduce rank-boundary turnover.
The 30% stop threshold is retained, but now measures a window high, including
pre-entry observations. A new candidate must clear that same price condition.

No ownership-age review, episode peak, cooldown, five-day median ranking or
historical portfolio formation is used by account300. Fill empty places at up
to 5% of current account equity each, funded by current cash after outstanding
buy commitments; keep existing position sizes. Orders outstanding for an
instrument prevent another command. Missing held inputs defer that instrument;
unknown account equity prevents new purchases. Cash expected from an unfilled
sale is never available to fund a purchase. Same-session terminal veto applies.
Complete price/volume facts that fail admission filters are distinguishable from
missing facts. A held stock that becomes illiquid or falls below the entry price
floor leaves the eligible ranks and can exit; its failed entry filter must not
be interpreted as an unavailable observation.
This is research authorization to explore account-driven strategy rules, not a
change to the production broker/shadow boundary.

Further clarification: internal state is allowed. The account-only rule set is
an optional simplification comparator, not a requirement to discard ownership
state. The stateful snapshot arm directly tests the narrower objective. The
account300 high is the maximum available positive observation within 300 market
sessions; its ranking still requires 127 complete consecutive closes. Earlier
gaps or a shorter listing do not impose a second 300-observation admission rule.

The canonical book is the simulated account and supplies accurate economic
events for backtesting. Its ages, peaks and cooldowns are ignored by account300.
Historical event terms still matter to simulated P&L even though the prospective
strategy would read broker-adjusted account balances. Broker feed reliability
and forward execution remain untested by this offline experiment.
The pure account rule can continue selecting unaffected names when account
equity is known despite a held-stock market-data gap. The offline adapter has
no independent broker valuation: unresolved canonical equity still blocks
purchases in that replay. This distinction is covered by a direct account-rule
test and must remain explicit in interpreting blocked-session counts.

Can current-window features and automatic instrument eligibility replace the
requirement that every old source observation remain unchanged, without losing
useful economics? Compare four independently evolving canonical Wealth Core
books with identical cash, dates, source observations, fees and event terms:

* `baseline`: current V5/Median-5 features, lifetime owned-episode stop, review,
  ranks, cooldowns and canonical accounting.
* `snapshot`: recompute momentum, recent return, formation volatility and
  liquidity from the currently available window. Missing required observations
  exclude a candidate until its window becomes sufficient. Preserve the existing
  ownership/review/stop rules. Use canonical signal functions in double precision
  rather than historical mixed-precision running accumulators; this numerical
  change is part of the experimental profile, not claimed bitwise equivalence.
* `rolling300`: snapshot features plus a stop peak over the last 300 market
  sessions of actually owned closing observations. Existing review and cooldown
  rules remain. A peak expires; the stop does not include pre-ownership prices.
  Canonical corporate-action reference transformations rescale retained owned
  observations before adding the current close. These bounded observations are
  carried strategy state, not reconstructed historical ownership.
* `account300`: the simpler account-based rule set specified above.

All variants call the canonical feed, stepper, book, action handling and fills.
No parallel economic book or broker adapter is implemented. This first comparison
isolates Wealth Core; it does not claim combined Sentinel/Alpaca performance.
The baseline verifies the research driver against the canonical public runner.

## Current-snapshot boundary

Window corrections affect future signals; they do not undo trades, change cash,
or retrospectively apply dividends. A research snapshot update accepts only
dated rows inside the last 300 market sessions, with unique permanent identities
and explicit raw/signal price domains. It validates the complete update before
mutation. No provider-wide historical equality requirement is imposed.
Changing a carried signal basis requires a declared positive uniform rescaling
of both the series and owned references. Conflicting current share/action facts
are still unresolved. No inferred split, invented fill, automatic write-off or
broker quantity copied into the shadow book is introduced by this experiment.

Unheld gaps affect candidate eligibility. Held missing marks continue to block
new admissions through canonical unresolved-equity handling; exits/reconciliation
retain canonical semantics. Unknown terminal economics remain visible. A backtest
with unresolved marks must report unavailable performance, not silently use stale
marks. Existing canonical terminal settlement assumptions are counted separately.

## Data and evaluation

Use the retained local Sharadar research archive, including dead securities;
do not filter to present-day survivors. No new provider download is needed.
Start with 300 feature sessions and a fresh $50,000 book, followed by the same
measured sessions in each arm. This deliberately tests a simpler startup rather
than importing the earlier formed portfolio. Use available reviewed event data
equally in every arm and disclose that dependency; removing archival equality
does not make missing economic terms appear.

The retained tape contains revised historical observations, not archived daily
provider vintages. Returns are a retrospective strategy comparison. Injected
missing rows, revisions, splits and restarts establish specific recovery behavior;
they cannot establish historical provider timeliness or Alpaca completeness.

Record measured dates, returns, drawdown, turnover/fees, holdings, blocked sessions,
settlement outcomes, source identity and timing. Do not optimize thresholds after
seeing results. Run a bounded pilot first; retain complete daily results and report
the actual completed interval. No incomplete prefix may be labelled a full run.

Tests must cover candidate exclusion/readmission, held gaps, dated corrections,
split value conservation, rolling peak expiry, no pre-ownership peak, corporate
reference rebasing, next-open execution and restart equivalence. Remove selected
guards deliberately and require the corresponding falsifiers to fail.

The first substantial interval is 2007-03-15 through 2010-12-31, including the
financial crisis and recovery, following 300 feature-only sessions beginning in
2006. It is not a twenty-year result. The retained classification reconstruction
and existing canonical terminal-settlement conventions are common assumptions
across arms. Actual Alpaca asset availability is not substituted for the
historical eligible universe. Production promotion requires a separately
reviewed decision; this branch only answers research questions.

## Broker-hosted reference account alternative

The owner also proposed a separate Alpaca paper account running full-exposure
Wealth Core, with Sentinel controlling the other account. This is a separate
architecture option: broker positions and corporate-action processing would own
the reference account's accounting, but fills, outages, funding and order rejects
would then affect the reference signal. It still needs candidate market data and
persistent ages, review flags and cooldowns. The offline experiment below does
not qualify that broker behavior. Evaluate it in a forward paper trial with an
explicit policy for reference-account outages and cross-account divergence;
do not claim a second paper account provides deterministic historical outcomes.

Provider check, 2026-09-30: Alpaca's [paper trading documentation](https://docs.alpaca.markets/us/docs/paper-trading)
explicitly excludes dividends. A [2026-03-14 Alpaca staff response](https://forum.alpaca.markets/t/ped-reverse-split-not-handled-in-paper-accounts/18569)
also says paper accounts do not support stock splits. The latter is a dated
support statement, not fresh account-level verification. Consequently a paper
reference account cannot currently be assumed to represent total-return economics.
The live-account [mandatory corporate action documentation](https://docs.alpaca.markets/us/docs/mandatory-corporate-actions)
must not be used as proof of paper simulation support. Retaining internal
economic state remains useful even with a simple market-data interface. This
experiment does not implement account adjustments or change any paper account.

Alpaca's [historical bars API](https://docs.alpaca.markets/us/reference/stockbars)
exposes explicit raw, split, dividend and spin-off adjustments, symbol mapping
and separate SIP/IEX feeds. A future snapshot adapter must request the intended
price domains and feed explicitly; `all` is not a substitute for the current
split-adjusted, dividend-unadjusted signal domain. Single-exchange volume cannot
silently replace consolidated volume under the same dollar-liquidity thresholds.
The documented [historical coverage begins in 2016](https://docs.alpaca.markets/us/docs/about-market-data-api),
so this 2007–2010 retained-data experiment cannot qualify Alpaca historical
acquisition. Delayed end-of-day access and real-time account access are different
requirements; no paid market-data subscription is assumed by this experiment.
