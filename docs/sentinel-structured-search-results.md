# Structured Sentinel search: first-batch evidence

## Verdict

The frozen first batch found **no qualifying improvement**. All 576 new
configurations produced lower CAGR than recorded Sentinel over the combined
chronological evaluation, even when ranked afterward with hindsight. There were
555 distinct applied exposure paths. This is substantially broader negative
evidence than the earlier neighboring-rule experiments, not proof that Sentinel
is optimal or that new signals cannot help.

The design was recorded in [sentinel-structured-search.md](sentinel-structured-search.md)
before implementation. Runtime froze the complete menu/protocol before scoring
and each inner selection before its outer block. No settings were changed after
observing the outer results. The separate candidate review reads saved paths;
its whole-period rankings are diagnostic and cannot promote a policy.

## Evaluation boundary and results

The immutable fractional Core snapshot spans 2006-07-31 through 2022-08-09.
Earlier years supply model fitting and validation. The five outer evaluation
blocks cover **2013-01-02 through 2022-08-09**, with 2012-12-31 as common NAV
baseline and 2,418 return sessions. These dates differ from earlier full-prefix
and 2016-start experiment windows; compare only contemporaneous columns.

Every figure below includes the existing next-open scalar accounting and ten
basis points per unit allocation turnover. Models train only on outcomes known
at their cutoff. Modeled NAV and overnight exposure carry across block changes.

| Chronological policy or control | CAGR | Multiple | MaxDD | Switches |
| --- | ---: | ---: | ---: | ---: |
| Recorded Sentinel | 16.3895% | 4.2961 | 22.4010% | 14 |
| Overall selector | 9.4739% | 2.3854 | 24.1164% | 109 |
| Revised state-rule selector | 14.6383% | 3.7140 | 26.0939% | 30 |
| Trend/volatility selector | 10.0661% | 2.5123 | 34.5632% | 83 |
| Predictive-model selector | 10.6917% | 2.6528 | 24.1164% | 81 |
| Combination selector | 10.5241% | 2.6145 | 22.4010% | 107 |
| Always Core | 12.5230% | 3.1056 | 29.4517% | 0 |
| Fixed simple trend | 9.0010% | 2.2883 | 34.7169% | 133 |
| SPY | 13.7622% | 3.4502 | 33.7001% | — |

Each family selector may retain Sentinel when its inner candidates do not
qualify. The overall selector chooses among all families and Sentinel using
only the preceding validation window. These selections use information available
at each simulated cutoff; they are not the best complete paths chosen afterward.

The hindsight-highest individual configuration is `state-066`: 16.0447% CAGR,
4.1754 times wealth, 22.4010% MaxDD, 23 switches. Its parameters are entry 2,
healthy release 13, warning expiry 5, recovery confirmation 8 and no recovery
timeout. It improves one block, ties two and loses two. Even this retrospective
best falls short of Sentinel. Highest individual CAGR by family is 16.0447%
(state), 12.4145% (trend), 14.9107% (predictive), and 16.0197% (combination).

No selector meets the 25–30% target or the declared improvement screen. The
family results do not justify promoting a replacement.

## Mechanical findings

**Earlier winners did not transfer reliably.** In the five validation windows,
67, 11, 19, 181 and 15 candidates respectively improved CAGR within the incumbent
drawdown limit. Only 0, 1, 0, 13 and 0 respectively retained both improvements in
the next block. These are correlated trial counts, not independent samples or
significance estimates. The highest validation CAGR is a poor selection rule in
this experiment; enlarging the menu did not produce an economically superior
outer candidate that the selector merely overlooked.

**Relaxed recovery bought temporary rebounds that subsequently failed.** The
state selector for 2021–2022 used one healthy close to begin recovery and two
healthy closes plus positive twenty-session momentum for full early recovery.
Its March 24–April 13, 2022 difference episode averaged 90.33% Core exposure
while Sentinel remained at zero, costing 0.05081 incremental log wealth. The
state selector kept native severe-zero protection but lost money overriding the
subsequent recovery wait. That distinction matters: the failed component was
the attempted early return, not fractional share sizing or a different Core book.

**Replacement forecasts sometimes reversed the incumbent's useful protection.**
The price-only, five-session neural model selected for 2015–2016 had 25.9784%
validation CAGR versus Sentinel's 23.3557%, with slightly smaller validation
drawdown. In the next block it returned -1.3080% CAGR with 21.9895% MaxDD, versus
Sentinel's +1.0124% and 13.3751%. During August 26, 2015–February 19, 2016 it
changed 121 opens and stayed almost fully exposed while Sentinel was at zero.
The failure is a forecast/control error visible before costs are considered.

**Defensive replacements missed sustained gains as well.** The overall selector
used a trend/volatility rule for 2019–2020. During its May 13–December 21, 2020
difference episode it averaged 48.90% exposure while Sentinel remained at 100%,
losing 0.17379 incremental log wealth. Other learned/combined policies similarly
remained defensive through the recovery. The controller needs evidence that
distinguishes a dangerous decline from a volatile but profitable recovery;
additional states or trading activity do not provide that evidence by themselves.

**Turnover amplified the errors but did not cause most of them.** The overall
selector's incremental log wealth was -0.58833: gross timing -0.53341 and extra
cost -0.05492. Approximately 91% of its log-wealth shortfall arose before trading
costs. Sentinel switched 14 times; the selector switched 109 times. The strongest
family's shortfall was also predominantly gross timing, not modeled costs.

## Robustness and interpretation

None of the five selectors has higher CAGR with no worse MaxDD. None has
positive incremental wealth in three of five blocks; the combination selector
has one positive block, the others zero (ties do not count as wins). Removing
each selector's best difference episode leaves negative incremental wealth.

With costs doubled, Sentinel produces 16.2718% CAGR versus 8.7394% for the
overall selector and 14.4271% for the state selector. With both delayed by one
additional session, the figures are 16.6447%, 9.4692% and 15.2131%. A favorable
delay result for Sentinel is a sensitivity result, not a newly selected policy.

Five hundred exposure-timing shifts preserve each selector's occupancy and
recompute boundary turnover. The overall selector's CAGR is at the 56.2nd
percentile of its shifted controls; the state selector is at 94.8. This does not
make the latter a champion: it still loses to the incumbent. The 581-stream
maximum-statistic block-bootstrap diagnostic returns adjusted p=1 for all five
selectors' negative incremental means. It supplies no positive-improvement
evidence and cannot account for unknown historical research trials.

The evaluation history was inspected in previous research, and the incumbent
has its own historical selection provenance. These are chronological model
holdouts, not untouched research holdouts. The available features exclude raw
breadth/acceleration/leadership series absent from the retained daily export.
The batch therefore tests specific controller families using available signals;
it does not exhaust architectures, signals or parameter space.

The defensible next research question is whether additional causal information
can distinguish failed rebounds from durable recoveries, or distinguish harmful
volatility from profitable volatility. Another larger search over the same
available features has no positive foundation in this batch. Acquiring and
validating additional historical observations is separate work; no such data
or Core replay was created here.

## Reproduction and validation

Run commands and output meanings are in
[the research README](../research/structured_search/README.md). Evidence is at
`.codex-tmp/sentinel-structured-20261116/run-001/`. `report.html` contains nine
series, eighteen traces and **116 monthly rows**; its monthly selector compares
each researched policy with current Sentinel and SPY using cumulative CAGR,
multiple and MaxDD. The last row is partial August 2022. The report was checked
structurally; no browser visual QA is claimed.

Validation completed:

```text
python -B -m pytest tests/sentinel/test_structured_search.py \
  tests/sentinel/test_structured_search_mutations.py \
  tests/sentinel/test_exposure_oracle.py tests/sentinel/test_exposure_logic.py \
  -q -p no:cacheprovider
86 passed

python -B -m pytest tests/sentinel/test_structured_search_review.py \
  -q -p no:cacheprovider
4 passed
```

The first set includes eleven isolated injected faults; the review set detects
two additional identity-guard removals. The independent audit reconstructs all
2,880 validation trials, checks training boundaries/scalers for 1,030 fitted
model exports, checks 1,412,112 outer daily returns against raw ledgers, and
independently verifies 19,344 Decimal finalist returns and 1,044 monthly series
entries. Frozen selections and continuously stitched account ownership pass.

The main run exited zero. Its runtime prohibition recorded **zero calls** to
`sentinel.core.kernel.advance_session`. The separately read-only candidate
review also exited zero. The protected main replay remains stopped with exit
code 2 at its original data refusal; identity, checkpoint and complete committed
daily file are unchanged.

Evidence identities:

```text
Core binding
b21a537f35de5a8aeee2303a97949dde5fe0a925516cd065fc133d4b823942ad
Protected daily SHA256
652d53c2c2b7832e2a74257de3cee736c89034fda706534dfc375de6764a126a
Protocol SHA256
7bffecca016ab59a8ac934308de88f42f11935eb0b8082bcdaf0a66bf7aca859
All outer candidate actions SHA256
9e3fb4de48c9651034646c3e76f057625b7a49111d41478ed679c02b46530cc7
Report SHA256 (6,392,473 bytes)
1a52411ec85357343bcbfd7edbe7d8f3f66217ab11a991c42cab43c998c04ad9
Separate candidate-review source SHA256
6f85b4f06c4b64aca217562d799398fccb353baba5ada20083748265da76041d
```

Only research, tests and design/results documentation change. No production
controller, Wealth Core, execution layer, data publication, broker account or
PAPER installation changes.
