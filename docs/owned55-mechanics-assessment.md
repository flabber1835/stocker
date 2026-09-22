# Post-replay mechanical assessment

Research method recorded 2026-09-22 before the additional diagnostic calculations.
Base main is `ee23c894c97a2c4023654ce3a56a62728f5b061e`; the completed replay
and its reviewed audit are retained on PR #437. This assessment adds read-only
analysis to that research PR. No strategy parameters, production defaults,
market inputs or existing run artifacts change.

The question is fitness of the Core/controller interface, not maximum historical
return. The 2011, 2018 and 2026 observations and prior synthetic results are
already known; this is not an untouched holdout. We will measure the full
Owned55 observation trace, retain earlier negative experiments, and use public
primary research only as context for mechanism and validation choices.

## Diagnostic method

- Count exposure states, actual cause activity, binding recovery conditions,
  raw trigger gates and mathematically unreachable damage acceleration.
- Distinguish deliberate upper/lower exposure limits from a saturated sensor,
  and distinguish bounded stored counters from economic control saturation.
- Measure overlap between old causes and the independent owned cause; count
  only different final targets as extra decisions.
- Decompose the complete episode including the next-open recovery action. A
  recovery close is a signal, not execution. Include the next close in economic
  attribution so overnight ownership and release costs are conserved.
- Compare owned-book and recent-leaders recovery observations without claiming
  their return definitions or cohorts are identical.
- Reuse prior independently checked Core/cash, fee ablations and synthetic
  panels; do not regenerate golden results or run a parameter search.
- Rank recommendations by supported mechanical benefit, adverse evidence,
  uncertainty and a falsifiable acceptance procedure. No policy is promoted.

## Conclusion

The system has a coherent alpha engine and useful exposure control, but its
sensors and response rules are not yet a robust match for every book state.
There is no evidence here that a general arithmetic failure explains the
performance. There is strong evidence for a missing persistent-risk channel,
coarse damage measurement, and recovery rules that sometimes judge the wrong
population or remain restrictive after the owned book has recovered.

The most useful next change is to complete the owned-risk channel with a
cause-specific recovery contract and proportionate response. The prerequisite
is better diagnostics of owned dollar risk and exactly which cause is binding.
Neither shortening every timer nor making every detector more sensitive is
supported by the accumulated results. No historical optimal policy is claimed.

## What the evidence covers

The new assessment reads every full-history Owned55 comparison row. It reproduces
the production recovery output on all 5,176 transitions, checks every measured
fast/slow raw trigger against its predicates, and independently matches the
dated sequence to XNYS via exchange_calendars 4.13.2: 5,176 expected and observed
sessions, no gaps, duplicates or extras. Measurement uses 5,032 closes.

The earlier [mechanical fitness report](https://github.com/flabber1835/stocker/blob/b446e7e02f7257c17c4c57cd1c74eefcd1243303/docs/sentinel-mechanical-fitness.md)
supplies independently checked Core/cash and accounting ablations plus the 28
synthetic scenarios. Its source authority and limits remain in that report.
The stopped Slow15 result, the zero-ceiling owned experiment, and all adverse
cases are included below. No new historical policy search was performed.

| Same current Core stream | Multiple | CAGR | Maximum drawdown |
| --- | ---: | ---: | ---: |
| Always hold Core | 23.31x | 17.05% | -45.63% |
| Native shock/slow control only | 23.78x | 17.17% | -36.55% |
| Complete current Sentinel | 29.24x | 18.39% | -29.77% |
| Current plus Owned55 | 30.66x | 18.67% | -28.47% |

For context the separate research champion is 56.27x / 22.32%, and SPY is
8.44x / 11.26%. They are not targets to optimize toward. In particular the
research champion has a different owned book and input lineage. Its greater
return does not establish that the controlled current Core could have earned it.

Sentinel is contributing: the complete controller improves terminal wealth
about 25% over always-Core while reducing maximum drawdown by about 16 percentage
points. The leadership/recovery package also improves the observed result over
Native-only; removing that package would sacrifice useful protection. Wealth
Core invested an average 92.21% of its NAV in equities, held 18.27 positions on
average, and admitted 394 episodes over the original history. Broad failure to
deploy capital is not supported. The actual account's average intended stock
fraction was about 81.52%, because the controller scales a Core book that itself
contains cash. Those averages are distinct quantities.

## Signal dynamic range: adequate numbers, inadequate information in places

There is no evidence that ordinary floating-point range is clipping the
controller's returns. All 5,032 measured observations are finite. Core r20 spans
-26.53% to +31.16%, with a distinct value each day; r40 spans -26.45% to +45.41%.
The concerns are loss of information through labels, mathematical headroom,
moving denominators and measurements of relative speed instead of absolute risk.

### Damage acceleration has a hard loss of headroom

Damaged breadth is between zero and one. Consequently
`damage[t] - damage[t-5] <= 1 - damage[t-5]`. Above 70% prior damage, the
required 30-percentage-point increase is impossible even at 100% current damage.

This occurred on 611 measured closes. Among 129 closes meeting the existing
drawdown/damage/green definition of severe owned damage, the acceleration was
mathematically unreachable on 98. Other causes did sometimes provide protection:
44 of those 98 still had a full final target. On 24 fully exposed closes, damage
acceleration was the only failed fast condition and the fast cause was armed.
These counts distinguish a useless repeated signal while already protected from
a genuine missing entry opportunity. They do not establish that entering on
all 24 closes would improve investment returns.

Breadth itself reached 100% on 47 closes and green reached zero on 72. Once all
names are labelled damaged, additional deterioration cannot raise damage at all.
The raw NAV and return sensors still change; the requirement for simultaneous
acceleration prevents them from independently establishing fast protection.
The existing 2011 causal witness and the new full-history counts agree.

### Breadth resolution depends on the current book size

With 18, 19 or 20 holdings, changing one label moves breadth by 5.56, 5.26 or
5 percentage points. The nominal 88% threshold actually requires 16/18,
17/19 or 18/20 damaged positions. It is not an 88%-precision measurement.
With 16 holdings it requires 15/16, or 93.75%; with 17 it requires only 15/17,
or 88.24%. That non-smooth effective threshold is real arithmetic, not a float
rounding error. There were also 31 measured closes with fewer than ten holdings;
a three-name book has a 33.33-point label step. Full distributions are retained
in `mechanics.json`.

Peer escalation compounds the discrete behavior: each name sees itself and at
most three residual-correlated neighbors. Changing one peer's label can affect
several names' damage classifications. A 252-session peer relation and a
five-session change in binary breadth are different time scales. This gives
participation information, but should not be mistaken for a precise dollar-risk
meter. Changing holdings also changes the denominator and population; an
improving breadth reading after stops is partly reduced remaining risk and may
not represent price recovery of the same cohort.

Green and damage are disjoint in the current classifier, verified at every
measured close and implied by the predicates. Therefore damage >=88% already
implies green <=12%, satisfying the fast green <=20% gate automatically.
Likewise the slow damage >=75% condition implies green <=25%. Those green
entry clauses are redundant confirmation; recovery green remains informative.
Deleting redundant clauses would simplify explanation but produce no expected
return improvement. The design should not count them as independent evidence.

### Volatility acceleration is not a volatility-level sensor

The actual measurement is `SPY std5 / std20 - 1`, not Core volatility or absolute
market volatility. It ranged from -0.918 to +1.074; its 5th/95th percentiles were
-0.605/+0.596. There is adequate numerical range around its +0.04 threshold.
Because these windows are nested, its theoretical upper bound under the sample
variance convention is `sqrt(19/4)-1`, about 1.179. That bound does not appear to
be the practical limitation at the chosen threshold.

The important limitation is scale invariance. A production-function probe
multiplies every daily market return by ten. Absolute twenty-session volatility
rises tenfold, but the acceleration reading remains exactly 0.0897247358851685.
A prolonged high-volatility regime can also cease to look accelerated as its
denominator catches up. This signal usefully asks whether volatility is suddenly
increasing; it cannot alone answer whether the current amount of risk is high.
The other controller gates still respond to loss, so this probe is not a claim
that the entire strategy ignores absolute returns.

### Stored counter caps are intentional, not economic saturation

The 30-session base-duration counter was at its cap on 274 closes. Once the
predicate is `duration >=30`, values 30 and 300 are decision-equivalent under
the current rule. Capping stored counters does not silently stop a timer or
create integral windup. It does hide the true elapsed duration from an operator
unless a separate entry date or diagnostic clock is retained. Counter range
should not be enlarged in the expectation of earning more CAGR.

The continuous alpha ranking has a different role: it orders eligible names
by momentum relative to formation volatility, then smooths the top candidates
by recent ranks. There is no comparable hard upper score clamp in that path.
The retained complete comparison tape does not contain every daily eligible
candidate's score margin or every held name's dollar weight. It cannot establish
historical ranking robustness or concentrated-risk dynamic range. Those remain
specific instrumentation gaps, rather than reasons to claim the ranking is bad.

## Binding controls and the places exposure costs return

| Final close decision | Measured closes | Fraction |
| --- | ---: | ---: |
| Full Core multiplier | 4,267 | 84.80% |
| Zero | 601 | 11.94% |
| 55% | 164 | 3.26% |

These are close decisions. The earlier report counted held next-open allocations
and showed 4,268/601/163; the one-day difference is the final decision's timing,
not missing sessions. The upper unlevered limit is binding by design in ordinary
conditions. Zero is used episodically, not continuously. There is no evidence
that a permanent global limiter is strangling the strategy on most days.

Native was zero on 391 closes. Fast and slow were both active on 113 of those;
clearing one does not release the other. The final target remained zero on a
further 210 closes after Native was full, due to leadership recovery. The owned
book had positive r20 on 100 of those closes and met Native's complete health
predicate on 98. Conversely, the leaders were nonpositive over twenty sessions
on 134, and at or below the forty-session floor on 152; conditions overlap.
Only 35 had currently healthy leaders but insufficient accumulated confirmation.
Thus this is not simply an eight-day timer problem: the cohorts often disagree.

Minimum Native age alone blocked an otherwise sufficient healthy streak on six
fast and two slow closes. Those few days can be economically large around sharp
rebounds, but cutting every dwell time is too broad a remedy. The longest
leadership-only zero interval lasted 72 closes, not eight. Persistence is a
consecutive-evidence requirement, not a fixed-duration stay.

Owned r20 was positive while leaders r20 was nonpositive on 965 closes; the
reverse occurred on 291. These are different economic instruments: a persistent,
cash-containing dollar book versus an equal-weight, refreshed leadership sensor.
Their return magnitudes should not be treated as equivalent units of readiness.

A new controlled witness isolates a related non-monotonic rule. With the same
recovery state, leaders r20=+2%, leaders r40=-5%, and SPY r20=+2%, an owned r20
of +1% clears the cross-surface route; improving only owned r20 to +3% leaves
the account at zero. This follows the condition requiring both SPY and leaders
to perform at least as well as Core. It is a deliberate relative-concordance
rule, not an arithmetic error. It is a poor standalone definition of whether
the owned book is healthy, and should not be the only possible owned recovery
route. The ordinary persistence route can still release independently.

The most consequential observed opportunity costs remain delayed protection in
2011 and missed recovery in March/April 2026. In the latter next-open window,
Core gained 25.16% while the controlled account gained 1.97%. This is an adverse
episode, not attainable free CAGR: exiting less or recovering earlier can lose
more in rebound-then-relapse markets. During 2008-09, 2015-16 and early 2020,
restriction was useful. Full Sentinel also beats Native-only in this history.

Core cash, cooldowns and limited admissions are a second attenuation layer. They
are part of the alpha strategy, not execution bugs. A 100% Core multiplier is
not a promise of 100% equity ownership, and normalizing away Core's cash would
change the strategy. Within the retained scalar model, removing all overlay
transition fees moves the multiple only from 29.24x to 29.84x, about 0.12 annual
percentage points. Decision timing dominates that particular cost estimate;
real spreads, impact, missed opens and durable broker fills remain unmeasured.

## What all the alternative experiments now say

Slow15 improved several fixed synthetic persistent-decline cases, but its actual
historical prefix was unchanged through 2011 and ended worse when stopped on
2016-05-16: 3.7494x / 14.45% versus current 3.8134x / 14.65%. It did not solve
the intended historical blind spot. Its file still says RUNNING because the
worker was deliberately stopped; no continuation is inferred from that label.
There is no reason to promote it merely because the earlier synthetic panel
had no adverse terminal cases.

The prior zero-ceiling owned controller strongly improved synthetic leadership
rotation and gradual decline, but was worse in staggered-damage/rebound cases.
Across the four-phase panel it had eight higher, eight lower and eight unchanged
terminal outcomes, excluding duplicate split controls. A more sensitive fast
delta lost in all four staggered-damage cases, and faster leadership recovery
had small mixed effects. No zero-ceiling full-history result is available here.

Owned55 is a material but narrow improvement in the historical sample:

| Owned cause episode | Additional different close targets | Complete relative wealth effect |
| --- | ---: | ---: |
| 2008 | 0 | 0.00% |
| 2011 | 37 | +6.25% |
| 2018-19 | 27 | +1.13% |
| 2020 | 7 | -2.26% |
| 2021 | 2 | -0.17% |

The cause was active for 300 closes, but the old controller already commanded
zero on 204 and 55% on 23. Only 73 final targets changed. This is useful
independent coverage, with heavy masking by existing causes. The final wealth
improvement is 4.85%, CAGR improves about 0.28 percentage points, and maximum
drawdown improves about 1.31 points. The worst episode moves from 2011 to 2022;
it does not disappear. Excluding the motivating 2011 effect, the compounded
relative effect is **-1.32%**. This is descriptive episode exclusion, not a
holdout estimate, but prevents mistaking one repaired crisis for broad dominance.

**Reporting correction:** the initial `final-audit.json` attributed each owned
episode through the recovery signal close. That omitted the next open's old
ownership/transition effect. Including the execution close changes the 2020
episode from -2.87% to -2.26%; final NAV, CAGR and drawdown never change. The
new `mechanics.json` records both signal and execution dates. Its episode factors
multiply exactly to the observed final relative wealth. The initial artifact is
preserved as the signal-close analysis. A $100 synthetic accounting witness and
a killed omission mutation verify the corrected attribution boundary.

## Prioritized improvements

### 1. Expose the risk actually being controlled

Record, at each close, raw damage/green counts and denominator; dollar-weighted
damaged capital; continuous owned drawdown severity; Core invested fraction,
largest weights/effective position count; owned and leader return definitions;
absolute Core and SPY volatility; each cause's requested ceiling, actual duration
and exact recovery blocker. Keep a fixed-cohort diagnostic so label improvement
caused by selling names is distinguished from price improvement of survivors.

This adds observability without altering alpha decisions. It has the highest
confidence engineering benefit, but no immediate promised CAGR benefit. Keep
count breadth for participation; do not silently substitute weighted damage
under the old 88% threshold. Weighted counts alone still saturate when all
capital is damaged, so retain a separate continuous severity measurement.

### 2. Complete the owned-risk channel, including its recovery

Retain independent abrupt-shock and persistent-owned-impairment causes. Use a
partial response for the latter as a candidate, preserving independently active
zero causes. Evaluate its entry **and** release together: Owned55's adverse
2020 behavior is chiefly extra restriction during recovery, not useful extra
protection at the initial crash when current Sentinel was already at zero.

Define what resolves each cause using the asset that will actually be held.
An owned-health recovery route can resolve owned impairment without requiring
a refreshed leader cohort to outperform a recovering Core. A still-active
market/shock cause remains binding. Do not make a new all-time high the only
release condition; that can trap a changed book below an old peak indefinitely.
Do not globally erase leadership confirmation, whose existing aggregate benefit
is substantial. This is the best supported structural direction, not a finalized
new threshold set or approval to promote the existing Owned55 unchanged.

### 3. Match response size to information quality

A one-name threshold crossing is coarse evidence for changing the whole account
from 100% to zero. Separate detection from the exposure response: persistent
impairment can justify a smaller reduction, while a distinct severe/shock cause
can still justify zero. Any broader graduated response should be monotone in
owned severity, bounded, restartable and tested for turnover and relapse harm.
Smooth measurements before adding many actuator levels. A continuous exposure
formula with a noisy or saturated sensor is not automatically better.

Reuse of 55% makes a small experiment operationally simple, but does not prove
that 55% is optimal. Likewise, dividing damage acceleration by remaining
headroom is not a safe cure: its denominator vanishes at full damage and
amplifies a single changed label near saturation. Lowering the existing fast
delta is already contradicted by adverse synthetic cases.

### 4. Preserve useful alpha behavior and enforce finite risk tests

Keep permanent ownership, winner retention, corporate-action continuity,
cooldowns, canonical book accounting and the one-way Core-to-Sentinel boundary.
Do not add daily ranking exits or rebalance winners simply to resemble the
reference. No current result establishes that those would improve the system.

Before another twenty-year run, freeze one complete recovery challenger and a
small, coherent synthetic matrix: abrupt shock; slow decline and plateau;
rebound followed by relapse; leaders recovering without the owned book; owned
recovery without leaders; staggered stops and changing book size; concentrated
winners/losers; high stationary volatility without accelerating loss; repeated
shocks; and missing evidence/restart. Include the current controller and Owned55
as fixed controls. Do not optimize the generator after seeing results.

Score detection and execution latency, further loss after detection, missed
rebound, worst drawdown, relapse loss, turnover, concentration and budget
conservation. Acceptance must require correct cause independence, finite
reachable response to the defined persistent-impairment stimulus, next-open
ownership and invariance to bookkeeping events. A stronger owned recovery must
not by itself worsen an owned-risk decision; independent market causes may
still restrict exposure. Set acceptable false-exit and relapse-loss budgets
before choosing parameters. These are risk objectives, not values inferred
from the most profitable history. Historical replays then check an already
frozen candidate with repaired authoritative inputs; preserve every trial.

## Research context and limits

[Moreira and Muir](https://conference.nber.org/confer/2016/LTAMs16/Moreira_Muir.pdf)
provide evidence that managing exposure using risk level can help several factor
portfolios. That supports investigating absolute risk alongside acceleration;
it does not validate any Sentinel threshold or mandate leverage. In a broader
study, [Cederburg and coauthors](https://www.lehigh.edu/~xuy219/research/COWY.pdf)
find that volatility-managed portfolios do not systematically dominate and
highlight instability in implementable out-of-sample allocations. A new
volatility target should therefore be a tested alternative, not an automatic
replacement for the existing controller.

[Daniel and Moskowitz](https://www.kentdaniel.net/papers/published/jfe_16.pdf)
show that momentum crashes and market rebounds can coincide. Their long/short
factor results are not Wealth Core's long-only portfolio. They nevertheless
give a sound reason to include rotation and rebound/relapse tests rather than
assuming a strong SPY rebound means the existing owned book is safe.
[Bailey and coauthors](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf)
explain the danger of selecting among repeated backtests. This twenty-year tape
and its prominent episodes have already informed the hypotheses; neither many
daily rows nor a new synthetic seed makes them independent market experiments.
No probability of overfitting or expected future CAGR has been estimated.

Known classification issues (including SILV from 2018, IIVI and EXE), action
proxies and scalar execution assumptions limit absolute-return claims. The
2011 mathematical blind spot does not depend on those later classification
errors. No broker cash/fill finality, daily live slippage, NAS durability or
deployment qualification is established here. A successful replay is evidence
for the tested mechanics, not proof of the absence of all software bugs.

## Reproduction and validation

From this worktree, with the existing local Python 3.12 environment:

```powershell
$py = 'C:/GitHub/stocker/.codex-tmp/bounded-feed-venv/Scripts/python.exe'
$env:PYTHONPATH = "$PWD;$PWD/shared"
& $py -m research.owned55_replay.mechanics C:/GitHub/stocker/.codex-tmp/owned55-20y-run
& $py -m pytest research/owned55_replay/test_model.py research/owned55_replay/test_continue.py research/owned55_replay/test_mechanics.py -q -p no:cacheprovider --basetemp=C:/GitHub/stocker/.codex-tmp/owned55-mechanics-final --junitxml=audit/owned55-twenty-year/mechanics-tests.xml
& $py -m research.owned55_replay.mechanics_mutations
& $py -m compileall -q research/owned55_replay
& $py tools/validate_test_responsibility.py --base ee23c894c97a2c4023654ce3a56a62728f5b061e --output audit/owned55-twenty-year/mechanics-test-ownership.json
git diff --check
```

Results: syntax, diff whitespace and test-ownership checks pass. Twelve focused tests pass, including four new mechanical/accounting
witnesses. Both new diagnostic faults are killed: omitting release execution
and confusing absolute volatility with acceleration. The original seven policy
fault results remain retained. Raw triggers reconcile across 5,032 measured
closes and recovery across all 5,176 transitions; the calendar matches exactly. Counts,
quantiles, source trace hashes and every recovery-blocked observation are in
`audit/owned55-twenty-year/mechanics.json`. No new long replay, optimizer,
production code change, NAS access or broker call was required.

The first diagnostics invocation included a legacy research dependency path
whose `six.py` was unreadable. Removing that unnecessary path used the already
installed environment successfully; no dependency or run input changed.
