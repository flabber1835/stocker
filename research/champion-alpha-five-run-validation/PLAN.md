# Five-run alpha hypothesis validation

Status: BLOCKED_AT_BASELINE_PREFLIGHT. Backtester runs started: 0 of 5.

## Isolation and authority

Repository: flabber1835/stocker.
Dedicated branch: research/champion-alpha-five-run-validation.
Exact starting commit: 5b4b4681fa46b3f867557c7ad8be9829a4e1be62.
Reference run: 34064302990; artifact 9999003664.
Existing files and branches remain unchanged. This commit adds only this research directory.
No workflow is started by this study. No backtester engine is invoked by the verification script.

## Blocking finding

The reference certificate declares dividend_lag_sessions=1. The hash-bound executable
appends dividend receivables with due session gday+15. Its engine summary also reports
15. The source-build report declares 1 while its generated program also uses 15.

The economic overlay tests for the substring gday+1; that substring also occurs in
gday+15. The exact AST check in verify_baseline.py rejects this mismatch.

Reconcile the intended dividend-settlement specification and its executable evidence
before freezing the executable experiment baseline. The study does not estimate the
performance effect of this mismatch and does not alter the baseline implementation.
All five authorized backtester runs remain available.

## Prespecified experiment arms

Run 1: BASELINE. Reproduce the reconciled, pinned baseline and verify its full daily
path against its matching reference. Record the source, runtime, corpus, classification
and profile identities. Failure prevents valid attribution for every experimental arm.

Run 2: FRESH_REPLACEMENT. Set only the vacated-slot cooldown to zero. Retain the
21-session security-specific cooldown, the one-new-admission-per-day limit, entry
sizing, ranking, stock-selection conditions and next-session-open execution. A slot
vacated at today's open can generate a replacement decision at today's close.

Run 3: EARLY_WEAK_REVIEW. Add an assessment at holding age 59, with resulting exits
at the next available open. Apply the existing underwater-and-not-qualifying test.
Preserve the original age-119 assessment and existing stop. Passing the early check
does not mark the original review completed.

Run 4: STAGED_RECOVERY. Preserve baseline stock decisions and risk-controller state.
At the first close that sets the baseline exposure target to zero, store that close's
SPY benchmark level. While the baseline target remains zero, count elapsed sessions
and consecutive closes satisfying all of: SPY above the stored level; SPY trailing
20-session return positive; stock-book trailing 5-session return positive; no current
fast-shock signal. Following at least 10 zero-target sessions, permit 25% stock-book
exposure after five consecutive qualifying closes and 55% after ten. A failed
condition restores the zero target. Baseline positive targets end/reset this probe.
Every changed target executes at the following session's open. Apply the existing
transaction-cost convention to every exposure change.

Run 5: COMBINED. Apply the exact changes from runs 2, 3 and 4 together. Its definition
is fixed before any experimental outcomes. No result-dependent choice of components.

No parameter sweeps, replacement arms, partial economic trial replays or automatic
reruns are authorized. Synthetic unit tests and static source checks execute no
historical portfolio replay. Every actual engine start counts toward the limit.

## PIT and classification gates

Pin the canonical market/corporate-action corpus
5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993,
package digest f05e40d9e1bff53ae50507719b5f589fb01b6184c79eceef800ddc2548f6209c,
and runtime 887f479b15ad861313da666ad698034d3847121c. Preserve the reference warmup
2006-01-03, measurement start 2006-07-31 and end 2026-07-31.

Use the existing production-equivalent factual-security-type contract. It permits
later authoritative documents to establish earlier legal type. Strict archival
availability of every classification source is a separate claim. Every classification
must apply to the precise canonical security and historical interval. Classification
research must use no price, return, rank, survival or strategy-outcome information.

Check each experimental dependency path: universe population and ranking inputs,
leadership inputs, pending orders, held positions, and corporate-action/terminal
identities. Unknown classifications or unsupported intervals stop the relevant arm
and produce an exact security-ID/ticker/interval/evidence-gap review queue. Do not
change a classification to preserve a desirable result. Revisions require a new,
explicitly frozen classification authority before any resumed replay.

Assert that decision inputs are available at the decision close, and that executions
use the next session. Preserve causal dividend and terminal-event treatment after
the baseline specification is reconciled. Record input timestamps, order decision
sessions, execution sessions, source hashes, path coverage and unresolved events.

## Reporting and interpretation

Report every completed and blocked arm. For completed arms provide net CAGR,
wealth multiple, maximum drawdown, Sharpe, volatility, annual and rolling returns,
market exposure, stock-book cash, vacancy durations, holding counts, trades,
turnover, modeled transaction costs and the 2008/2020 protection paths.
Separate incremental return from additional exposure and risk. Preserve complete
trade/holding evidence and the first divergence from the matching baseline.

The already inspected 20-year history is an in-sample research sample. These runs
can validate a historical mechanism and causal implementation. They do not establish
unbiased prospective alpha or justify automatic production promotion.

## Current classification expansion status

Not yet determined: no experimental portfolio path has executed. The present blocker
is the baseline certificate/source mismatch, not an identified new classification case.
