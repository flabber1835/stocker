# What the hindsight signal study established

## Finding

The saved 25% target is primarily a brief-loss-avoidance oracle. The observable
signals identify some turbulent periods, but the tested approximations still
confuse continued losses with rebounds. Adding the recovered leadership and
available breadth observations did not produce a consistent, economically useful
improvement in the short exit probes. This is evidence about these fixed probes,
not proof that Sentinel is optimal or that the dataset has no further information.

No new trading controller was fitted for deployment. Wealth Core was not advanced,
and the protected replay remains stopped at its original data refusal. The
research reuses its authenticated fractional history through 2022-08-09.

## What the ideal actions look like

Anchor: the previously completed closest-decision 25–30% CAGR search, with maximum
drawdown no worse than recorded Sentinel. Full retained interval:
2006-07-31–2022-08-09, 4,035 closes and 4,034 return sessions.

| Recorded path | CAGR | Multiple | MaxDD |
| --- | ---: | ---: | ---: |
| Sentinel | 16.4034% | 11.4051 | 22.4010% |
| Closest target oracle | 25.0010% | 35.7304 | 20.6137% |

The oracle changes 22 decisions: twenty 100-to-zero exits and two zero-to-100
entries. There are 21 episodes: twenty last one decision, one lasts two. Only
six changed decisions lie within five sessions of an actual Sentinel switch.
All 269 recovery-wait decisions remain unchanged. Ten of the twenty ideal exits
occur while the recorded owned-health flag is healthy; only two occur while it
is impaired. These facts correct a recovery-first interpretation of this
particular target. Other profitable hindsight paths can exist; the exact chosen
dates are not uniquely necessary just because 22 changes are necessary.

Independent Decimal replay reproduces the saved actual and target paths. Their
incremental log wealth decomposes as follows:

| Component | Incremental log wealth | Share of gross improvement |
| --- | ---: | ---: |
| Intraday moves | +0.7778646925 | 65.92% |
| Overnight moves | +0.4020973043 | 34.08% |
| Unchanged-allocation convention residual | 0 | 0% |
| Extra modeled trading costs | -0.0380190127 | — |
| Net | +1.1419429842 | — |

The overnight after the decision is already owned by the old position. The
oracle's overnight advantage is earned while it holds the altered position,
including the night before it rejoins Sentinel. This is not a same-close exit
that escapes a next-open gap. Episode accounting includes that rejoin day.

## What was observable before those dates

The strongest common descriptor of the twenty ideal exit dates is elevated
Core volatility: eleven are in the top decile of trailing 20-session volatility
among fully invested decision dates. The median percentile is 94.4%. Ten also
have top-decile downside variation. These are retrospective descriptive ranks;
the models never receive full-history ranks.

Momentum and leadership are mixed. Five-session Core momentum is in its bottom
decile on six ideal exits and its top decile on four. Five-session leadership
return is in its bottom decile on seven and its top decile on six. Leadership
relative to Core has four exits in each extreme decile. There is no single
uniform "leadership broke, therefore exit tomorrow" pattern in this target.

Raw damaged breadth is recovered on nine of the twenty ideal exit dates, and
its one-session change on eight. Median damage is 47.37%; the median one-session
increase is 5.13 percentage points. Sparse coverage prevents treating this small
profile as a complete rule. Missing values were not inferred from later holdings.

## Retained observations recovered without Core execution

Examined 404 content-addressed checkpoints. Of these, 394 match the retained
canonical state and exact daily prefix; two differ in canonical state and eight
are outside the retained interval. Multiple eligible checkpoints can preserve
the same date. Conflicting histories would fail the extraction.

| Observation | Dates available |
| --- | ---: |
| Leadership witness NAV, preserved trailing histories | 4,035 |
| Stop events within recorded controller windows | 4,035 |
| Damaged breadth, including preserved six-value windows | 2,040 |
| Exact checkpoint-close observations, green breadth and holding statistics | 391 |
| Complete existing/anatomy/leadership feature vectors after warmup | 3,972 |
| Complete breadth tier after warmup and one-day change requirement | 1,737 |

Every historical value retains its observation date and the checkpoint that
preserved it. The checkpoint's terminal observation is never assigned backward.
Recovered leadership 20/40-session returns, Core 5/10/20/40-session returns and
stop counts agree exactly with 385 saved close observations after warmup, for
2,695 comparisons. Zero imputation and forward filling are prohibited.

The prior controller search lacked these raw observations in its daily export.
This study recovered them from checkpoints instead of creating another Core path.

## What the dataset can approximate in these probes

Sparse target changes are never used as training labels. Dense local labels ask
whether an exit to zero while Sentinel wants full exposure, or an entry to full
exposure while Sentinel wants zero, would improve relative wealth by at least
1% after costs. Each override lasts 1, 5 or 20 sessions, then rejoins Sentinel at
the next open, including the rejoin overnight. The 55% outcome is also retained
in the local hindsight surface. These local outcomes have no global drawdown
constraint and are not a replacement 25% oracle.

Fixed logistic regression and depth-two trees train on earlier completed labels
and freeze for five chronological blocks starting 2013/2015/2017/2019/2021. No
hyperparameters are selected. Scalers and alert thresholds use training data
only. Added feature tiers are compared against the existing tier on identical
training and evaluation dates. There are 352 fitted model exports; absent models
are explicitly recorded for insufficient samples/classes or no evaluation dates.

The most direct approximation is the one-session exit probe:

| Logistic probe | Evaluation dates | AUC | Precision at frozen alert threshold | Alerts | Mean relative event gain |
| --- | ---: | ---: | ---: | ---: | ---: |
| Existing 44 features | 1,908 | 0.622 | 23.98% | 171 | -0.345% |
| Plus gap/intraday anatomy and native memory | 1,908 | 0.580 | 20.41% | 196 | -0.338% |
| Plus leadership | 1,908 | 0.583 | 17.92% | 212 | -0.370% |
| Existing features on breadth-eligible dates | 818 | 0.558 | See full report | See full report | -0.436% |
| Plus all features including breadth | 818 | 0.559 | 13.70% | 73 | -0.604% |

For the existing-feature probe, only 9.54% of evaluation dates are positive
local exit opportunities, versus 23.98% of its alerts. It captures ten of fifteen
ideal exit decisions inside the evaluation period. But 130 of 171 alerts fail
the 1% threshold; 97 actually lose relative wealth. The 74 profitable alerts
average +1.734%, while the 97 losing alerts average -1.931%. Alerts form 56
overlapping clusters. Four of five blocks have negative mean flagged gain.

This is the mechanical distinction: recognizing high variation can help rank
bad-day risk while still causing too many exits before upward moves. Better
classification or capturing more oracle dates does not imply better CAGR.
Binary event precision also ignores the magnitude of each missed rebound.

Breadth's one-session pooled AUC increases only 0.0012 against its date-matched
existing-feature control, with mixed block effects and worse mean flagged gain.
A five-session breadth tree has slightly higher AUC than its matched control
(0.581 versus 0.567), but mean flagged gain worsens (-0.452% versus -0.288%).
It is therefore not evidence of a useful replacement exit rule.

There is one modest recovery lead: the five-session entry logistic probe with
anatomy/native-memory features flags 26 events, with 53.85% precision and +1.159%
mean local gain. The matched existing-feature probe is 26.97% / -0.690%. However,
the 26 alerts form only seven overlapping clusters, eighteen occur in 2022,
and there are no alerts in 2019–2020. Recall is only 13.21%. This is a hypothesis
for further testing, not an established broad recovery improvement. The most
attractive sparse breadth-entry result has only nine alerts and is similarly
insufficient. All horizons, both models, unavailable fits and block scores remain
in the report; these descriptions do not select a new winner.

## What follows from the findings

The present evidence supports a signal problem more specific than "detect risk":
distinguish continued selling from rebound opportunity within already volatile
conditions, and account for the sizes of both outcomes. A useful next experiment
would estimate avoided downside and forfeited upside separately, then demand a
positive net benefit after costs. A weak direction estimate may justify studying
55% exposure; its value must be assessed rather than assumed from the oracle,
which made no 55% changes in this closest-target solution.

The retained source bundle's observation header includes raw open/close, signal
close, reported/raw-compatible volume, corporate actions and dated security
identities. It can support a separately declared experiment on broad-market
selling participation, unusual volume and return co-movement without advancing
Wealth Core. This is a field inventory, not a completed signal test or proof of
volume quality. The canonical bar contract does not contain high/low fields;
intraday ranges should not be assumed available from that interface. Full daily
held-stock cross-sectional observations were not recovered here and should not
be manufactured by assigning checkpoint holdings to intervening dates.

The retained bundle declares `strict_pit_certified=false`. Earlier research also
inspected these historical periods. Chronological model evaluation prevents
direct fitting leakage, but it does not turn the history into untouched research
evidence or cure source-era limitations. No live performance claim is made.

## Evidence and validation

Local evidence: `.codex-tmp/sentinel-signal-study-20261116/observations-001/` and
`run-001/`. The latter contains the offline report, exact dated features, local
labels, oracle profiles/episodes, frozen models, individual predictions, block
metrics, independent audits and the post-run interpretation. Launch receipts
record read-only mounts, no network, half a CPU, 1 GiB and pinned Python 3.12.

- `python -B -m pytest -q -p no:cacheprovider tests/sentinel/test_signal_study.py tests/sentinel/test_signal_study_mutations.py`:
  30 passed, including twelve deliberate guard/causality/accounting faults.
- Extraction, bounded study and separate review exited zero.
- Independent raw-ledger Decimal reconstruction verifies 1,629 action windows,
  including oracle dates and fold boundaries; maximum relative-gain error
  `1.14e-15`.
- Exported models reproduce all 78,026 evaluation predictions. All 352 training
  means/scales and training-derived thresholds are verified, with 150 matched
  baseline/augmented model pairs using identical dates.
- Both runtime Core guards record zero canonical transitions. The protected
  daily bytes/hash and checkpoint remain unchanged; container exit remains
  `exited 2`, not OOM. No replay repair or restart occurred.
- AST parsing covers all twelve Python source/test files. The offline HTML
  passes structural checks for 84 probe rows, six traces and all 21 oracle
  episodes; browser visual QA is not claimed. Report size is 4,867,378 bytes,
  SHA256 `4761f667f52158f8a07bfd01e0487df1a13a77b6ef39815630b763900dde9080`.

Identity receipts:

```text
source binding  b21a537f35de5a8aeee2303a97949dde5fe0a925516cd065fc133d4b823942ad
daily SHA256    652d53c2c2b7832e2a74257de3cee736c89034fda706534dfc375de6764a126a
daily bytes     17667916
checkpoint      9e6ac9a367ae36ff287ba625659f6fadd517e0283f763f04c73276cfd7fc0ebf
observations    9d69e6df938dfb4affe77d09f0ced6692ed9fe2f5cfc106216aa4f1230b34c66
probe protocol  20659b6dfc544d522282c4ea003dc90c0ac5cbbe0c7d5e6931af36d98e5216e8
```

All reported event gains are overlapping conditional diagnostics. They cannot
be summed into portfolio returns, CAGR or an achievable drawdown result.
