# Wider trailing-stop episode diagnostic

The owner authorized one quick comparison of 30%, 35% and 40% stops after the
concentration-aware tighter-stop screen. This is a conditional exit diagnostic,
not a Core replay, a new book, a portfolio CAGR/drawdown claim or an installation.
Core, Sentinel, broker state and all existing backtests remain unchanged.

## Frozen scope and question

Use the same 17 P00 episodes that reached 10% of original Core NAV. Preserve
original entries and quantities and original Core NAV denominators. The wider
stop activates at the first recorded 10% weight; before activation the original
30% rule applies. There are exactly three arms, 30%, 35%, 40%, with no further
parameter search. The old concentration-budget curve and 30% cap do not apply.
This does not evaluate a uniform wider stop on every Core holding.

All 17 episodes appear in coverage and outcome tables. Sixteen original exits
are trailing-stop sales; the remaining CRS episode is still held at the source
end. An independent non-stop exit, unsupported ownership change, missing quote
or unqualified corporate action must not silently become a continued holding.

For each completed episode set a common endpoint to the RAW open 60 original
exchange sessions after its original sale open. The 30% arm sells at its
recorded original open and holds zero-interest cash to that endpoint. A wider
arm sells at its own next-open trailing-stop execution, or at the predeclared
endpoint open if no stop has executed. This forced endpoint exit is scheduled
in advance, not a same-close stop execution. If the frozen source ends before
that open, mark at the last source close and report separately as censored;
never use short follow-up in the primary ranking or select a shorter horizon
because of results. The still-open CRS source episode is a separate reference,
not evidence about an extension after an original stop.

The DATA-only coverage qualification found 13 full-follow-up completed episodes,
and three completed censored episodes: SNDK has 17 later sessions, WDC 11 and
STX 10. All available bounded rows are tradeable and present. There are no
post-exit splits or terminal events in these windows. Two ordinary post-exit
dividends (LLY 2025-08-15 and PWR 2025-04-03) require exact RAW-share action
corroboration; their observation and action rows must agree. This coverage is
fixed before outcomes. Neither hosted process may suppress contrary input.

## Price, action and execution contract

Authenticate original P00 daily/checkpoint journals using the admitted DATA
reader pinned to d482a44ace51114d22cc98c3a4ce251410f8d153 (PR 577). Retain its
17-episode eligibility, source-identity and RAW/split-adjusted unit checks.
Load post-exit observations from the existing authenticated frozen corpus,
archive/corpus.zip (archive SHA256
c0a62a6bbb8b67f77a1fca34f5e836a36f90bdf67dd83e196ef3d3369a7925f6).
The source calendar is the original 2,156-session P00 axis, ending 2026-07-31.
Use exact security IDs, source RAW opens/closes, qualified splits, ordinary
dividends and explicit terminal/action evidence. No ticker stitching, quote
forward fill, total-return price used as a cash price, or invented continuity.

The archived CSV uses 17-digit binary64 serialization while admitted P00 JSON
uses the canonical reader's shortest float representation. Reproduce that
existing reader's finite binary64 parsing, then convert its shortest decimal
representation to exact rational arithmetic for the diagnostic. Preserve the
authenticated lexical source in the DATA inventory. Do not interpret incidental
CSV serialization digits as a different RAW price or change a recorded fill.

Reproduce all original 30% signal dates, open dates, shares, RAW prices and
10bp sale fees before admitting results. In particular reconcile pre-split
AGNT's source share units; do not compare a RAW close to an adjusted peak.
For a continuing wider arm update its own close peak after the old exit.
Use a nondecreasing position-value stop in constant share units. No retained
70%-of-peak floor may override a wider rule. A closing breach signals the next
authenticated session's RAW open; if the original breach already crosses the
wider threshold, it executes at the same original open. A last-close signal
without an authenticated later open remains unexecuted.

At the first 10% activation initialize the wider floor from the current source
peak and the selected 35%/40% distance; deliberately replace the pre-activation
30% floor once. Thereafter that arm's floor never decreases. Carrying the old
30% floor across this activation would define a different mixed rule and is
forbidden here.

Apply split terms before an effective opening and accrue cash dividends from
the shares entitled before that opening's sale, including an ex-date sale.
Track each entitlement once; do not infer a dividend from price returns.
Terminal wealth includes the face value of earned dividend claims, not a claim
that each dividend has settled as cash. No proceeds or dividends are reinvested
and cash earns zero, so issuer payment dates do not change this comparison.
Deduct 10bp on each actual/endpoint sale once. A censored position is a closing
mark with no invented sale or fee. Require positive finite RAW prices and
supported action/terminal semantics throughout the bounded follow-up, even
if the particular arm exits before the problematic observation. Refuse an
unqualified case rather than exclude a loser or manufacture an outcome.

## Comparisons and limitations

Primary score: mean paired terminal net difference versus the 30% cash arm,
divided by the same original Core NAV at first 10% activation, restricted to
episodes with the full predeclared 60-session follow-up. Ties favor 30%, then
35%. Report mean, median, wins/losses/ties, raw episode dollars, source-exit
date blocks (2018-20, 2021-23, 2024-26), and leave-largest-beneficiary-out.
The sum of different episode dollars is not a funded portfolio profit.
Censored episodes are visible separately and cannot choose the winner.

Report additional occupied sessions, deepest close loss/giveback, and later
rebound captured versus the original sale. Compare the continuing stock's
fractional gross return during the delay with the original slot replacement's
recorded fractional gross return over the same observed overlap, where there
is a direct replacement. This is only a descriptive opportunity-cost proxy:
no reused capital, reconstructed replacement book or double ownership. Missing
replacement evidence is unavailable, not zero. If a reliable replacement proxy
cannot be formed, say so and report the delay and replacement identities only.

This deliberately fixed-cohort screen cannot establish portfolio CAGR,
portfolio max drawdown, effects on future eligibility/sizing, Sentinel reactions,
an optimum, unseen validation, or a deployment recommendation. A positive
signal would require a separately authorized canonical full-book experiment.
No automatic production parameter adoption follows any result.

## Execution, verification and delivery

Verified current main: 1e7f4b181fbcb998b3086833ab813c21b1c2ca8e.
New isolated branch: codex/wider-stop-diagnostic, delivered through a ready PR.
Reuse pinned DATA/transport dependencies: legacy
0bc38753ac1f85b31eb95f560720e6b037e892c5, original-book transport
553590ca197c55942aadeb690d5436abd49a35d1, and prior screen
d482a44ace51114d22cc98c3a4ce251410f8d153. Do not merge/copy their entire branches.

All hypothetical stop paths, outcome arithmetic and numerical falsifiers run
only in credential-free, network-disabled GitHub-hosted containers. Local
work is DATA inspection/filtering, hashes, AST/launcher tests, authenticated
transport and already-recorded result analysis. No local financial replay,
canonical strategy imports, production database or broker contact.

Authenticate the existing encrypted input archive and pinned runtime image;
read-only source mounts, bounded resources, non-root, dropped capabilities and
explicit worker/reviewer stopped inspections remain mandatory. An independent
process recomputes every signal/fill, endpoint/dividend/fee arithmetic and the
primary aggregates/ranking. Falsifiers cover retained 30% cap, missing/future
open, same-open wider breach, post-exit new peak, split continuity, dividend
on sale ex-date, endpoint ordering, insufficient follow-up and altered input.
Nonzero, OOM, UNKNOWN stop or failed review forbids a qualified conclusion.
