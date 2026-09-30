# Data-available research

The decision is documented in `docs/data-available-research.md`. Nothing here is
selected by the production runtime. No account, API key or network access is used.

Completed [crisis/recovery findings](results/crisis-2007-2010/findings.md),
[metrics](results/crisis-2007-2010/summary.md) and
[chart](results/crisis-2007-2010/comparison.png) cover 959 sessions.
The [observed GO anomaly replay](results/go-20260930/findings.md) reproduces
the September 30 coverage refusal and tests its isolation in the unchanged
stateful snapshot prototype, including a hypothetical held-position gap.

Four arms share canonical accounting and the same observations:

| Arm | Signals | Ownership rules |
| --- | --- | --- |
| baseline | Existing incremental Median-5/V5 | Existing review, lifetime stop and cooldowns |
| snapshot | Recomputed from current window | Same ownership rules |
| rolling300 | Current window | Existing review/cooldowns; peak expires after 300 sessions |
| account300 | Current window | Top-20 entry, top-40 retention, 30% window stop; current account only |

`snapshot.from_window` demonstrates the one-snapshot interface. It can consume a
replacement window with revised observations or a newly supplied missing row.
It does not compare that window with yesterday's archival records. The backtest
streams the retained tape for efficiency; a differential test checks that its
snapshot features equal a fresh window calculation.

`account.propose` is the account-only decision function. Its inputs are snapshot
features, window prices, positions, cash, equity and outstanding-order commitments.
`run.Arm` adapts its results to the canonical simulator's next-open queue. The
scoped research replacement of `adapter.decide` is single-threaded and always
restored; economic accounting is never replaced.

Run from the repository root with Python 3.12 and the repository's test dependencies:

```sh
PYTHONPATH=.:shared python -m pytest research/data_available -q
PYTHONPATH=.:shared python -m research.data_available.mutations
PYTHONPATH=.:shared python -m research.data_available.run \
  --archive /inputs/pit-source-5bdc6b39.zip \
  --supplements /inputs/owned55-formed-20y-run/qualification-001/supplements.json \
  --output artifacts/data-available-crisis \
  --end 2010-12-31 --seconds 7200
python -m research.data_available.report artifacts/data-available-crisis
```

The source archive and supplements are the existing private local research data;
they are not included in this PR. Their hashes are recorded in each run. Four
previously reviewed source-row repairs are retained as data in
`input-repairs.json` to avoid counting in-kind distributions twice in longer
experiments. No new ticker-specific strategy rule is introduced.

Output directories cannot overwrite earlier runs. A time-budget stop is labelled
as such, and an unresolved marked equity makes return/drawdown unavailable. This
runner currently restarts the experiment from its beginning rather than resuming
a partially completed file. It writes small progress records every 25 sessions.

The measured comparison starts on 2007-03-15 after 300 feature sessions. All arms
start with $50,000 cash; the first close queues orders for the next open. No prior
formed portfolio is transplanted. Core trading costs remain 10 basis points per
side. This measures the unscaled equity strategy, not Sentinel exposure, broker
execution slippage, taxes or the operation of a second paper account.

Do not infer hands-off readiness from profitable results. The historical tape
does not contain provider-vintage outages. Recovery tests cover declared gaps
and corrections; broker-adjusted balances and account availability still need a
forward paper experiment. Reviewed historical event terms remain an input to
the simulator, not a proposed manual dependency of the prospective trader.

The `stops` counter means trailing-stop signals in the first three arms and
combined rank/window exits in account300. Neither final market value nor return
assumes forced end-of-run liquidation.

The second-paper-account idea has a provider limitation: Alpaca documents that
paper trading excludes dividends; its staff has also reported unsupported paper
splits. Sources and dates are in the design document. The simulated canonical
account here therefore must not be mistaken for Alpaca's paper simulator.
