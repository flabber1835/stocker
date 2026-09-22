# Sentinel mechanical fitness: findings and improvement priorities

2026-09-22. Production reviewed at `ee23c894c97a2c4023654ce3a56a62728f5b061e`.
This is a mechanical diagnosis, not an economic certificate or an optimal-policy
claim. [Registration](economic-results-diagnosis.md) preceded the new experiments;
[commands, artifacts and validation](../audit/economic-diagnosis/README.md) accompany
the findings. No production policy, golden fixture, NAS or broker account changed.

## Verdict

**The engine is functioning, but the exposure policy is not robustly matched to
the book it controls.** The strongest evidence concerns detector reachability,
discrete exposure boundaries and recovery timing. It does not support replacing
Wealth Core, retuning its ranking to recover the reference return, or calling the
entire system broken. Nor does it support saying everything is optimally calibrated.

Independent accounting reproduced both retained historical paths to within
`1.36e-14` relative error over 5,032 measured closes. An additional 101 canonical
historical transitions reproduced their retained decisions and economics exactly.
The 28 new synthetic scenarios reproduced the unchanged production controller
at all 3,760 formation/scenario closes. The problematic decisions are consistent
with the present policy, rather than unexplained arithmetic differences uncovered
by this investigation. These checks do not establish an absence of all bugs.

## What is working and should be preserved

The following ablations all use the **current** Core return stream and retained
bill/cost conventions, measured July 31, 2006 to July 31, 2026. They describe a
provisional scalar-account replay, not a broker-filled production account.

| Exposure policy | Multiple | CAGR | Maximum drawdown |
| --- | ---: | ---: | ---: |
| Always hold current Core | 23.31x | 17.05% | -45.63% |
| Current Native only | 23.78x | 17.17% | -36.55% |
| Complete current Sentinel | 29.24x | 18.39% | -29.77% |

Native contributes substantial protection. The additional leadership/divergence/
recovery package improves this sample further; that combined ablation does not
isolate recovery alone. Removing these protections to catch one missed rebound
would discard useful behavior. Restriction during 2008-09 and early 2020 is
particularly valuable in the retained episode accounting.

Core invests an average 92.21% of shadow NAV in stocks and holds 18.27 episodes
on average. That is inconsistent with a general failure to deploy its capital.
Its one-time reviews, persistent winners, stops and cooldowns deliberately differ
from a daily refreshed leaders portfolio. Preserve that alpha mandate. Headcount
breadth and the leaders witness are useful distinct measurements, but neither is
the same thing as the dollar risk of actual holdings. Do not renormalize Core's
cash away or make execution outcomes feed back into its selections.

Removing all scalar overlay transition fees increases the current multiple only
from 29.24x to 29.84x. This identifies exposure decisions as the more consequential
research target within this accounting model; it does not validate live costs.

## Confirmed mechanical weaknesses

### M1 — High impact: the shock detector can become unreachable as damage rises

At the August 4, 2011 close, Core was down 13.42%; all 19 remaining positions were
damaged, green breadth was zero, short returns and market/volatility confirmation
passed. The only failed shock condition was the five-session damage increase:
26.32 percentage points versus a required 30. Sentinel stayed fully exposed.
On August 8, Core drawdown reached 20.62%, still without a Native exit.

This is a structural blind spot: when prior damage exceeds 70%, even 100% current
damage cannot satisfy a 30-point increase. A speed-of-deterioration gate cannot
also serve as universal protection against an already damaged book. Slow defense
does not automatically rescue it: crossing ordinary drawdown only starts a timer
and resets a loss anchor; it does not reduce exposure. Another loss below that
anchor and additional breadth/return conditions are required.

Code: [shock conjunction](../sentinel/controller/champion_frozen.py#L46),
[anchor reset](../sentinel/controller/champion_frozen.py#L78),
[slow conjunction](../sentinel/controller/champion_frozen.py#L86).
The observed-state test changes just the binding delta input and confirms that
the same transition then exits. This diagnoses the gate, not an optimal threshold.

### M2 — High impact: small signal differences can decide the entire account

On October 10, 2018, Core drawdown was 13.44%, but 16/19 damaged positions (84.21%)
missed the 88% damage requirement. A diagnostic perturbation of one additional
damaged position crosses the rule and switches Native from one to zero.

Conversely, on March 30, 2026, damage delta was 30.0654 percentage points, just
0.0654 points over the threshold. All gates passed; Native instructed a complete
exit. An observed-state sensitivity test with delta 29.99 points remains fully
exposed. Neither result is a numerical precision error. A hard decision boundary
amplifies small, economically plausible changes in composition and labels.

This is why merely lowering the fast threshold is not an established cure.
Confidence in the risk condition and the size of the response need separate
consideration. No new size rule has been implemented or validated here.

### M3 — High impact: a recovered owned book can remain blocked by another clock

The March 30 signal acts at the March 31 open; it cannot avoid that opening gap.
By April 7, Core had regained its prior peak, r20 was +8.80%, damaged breadth was
42.11%, and green breadth was 47.37%. Native had three healthy observations but
its minimum age still blocked release. It cleared on April 13. The separate
leadership recovery condition then held the final target at zero through April 16;
the April 17 release was executable on April 20.

Over the connected March 31-April 20 economic window, Core rose 25.16% and the
controlled account rose 1.97%. This quantifies an adverse recovery episode; it
does not prove that faster re-entry always wins. The recent-leaders witness was
still negative on April 7 even though the actual owned Core had recovered.

Code: [minimum Native age](../sentinel/controller/champion_frozen.py#L97),
[leadership persistence/concordance](../sentinel/controller/champion_frozen.py#L190).
The clock test holds the real observations fixed and confirms the age restriction
is binding. Recovery should be assessed against the cause of restriction and
the owned book, while preserving independent causes that are still active.

### M4 — Material: review timing changes the response to the same stress family

The new panel uses the same seven pre-existing market formulas, 252 warmup
sessions and 120 scenario sessions, with 40/80/120/160 formation sessions.
Each case has a production-formed book, six fixed policies and independent
$100,000 whole-share accounts, 10 bps costs and a zero-yield synthetic bill.
These are 28 scenarios and 168 account paths, not independent market samples.

In the synchronized-shock family the current policy releases on scenario days
109, 69 and 32 for the first three formation lengths; at length 160 it remains
restricted through the 120-session horizon. Core's reviews, persistent ownership
and the controller's health tests interact. Formation also shifts calendar and
price-wave phase, so these differences are not an isolated estimate of book age.

In leadership rotation, current Sentinel never reduces exposure in any of the
four cases. Current worst drawdowns span approximately 26-30%; fresh leaders can
be strong while owned capital keeps losing. Core's one-time review is not a
general market-exposure controller. See [Core review ownership](../shared/stock_strategy_shared/wealth_core/engine.py#L414).

## What the fixed alternatives actually achieved

Counts below exclude the duplicate split control: 24 cases including four healthy
controls. They are descriptive counts, not probabilities or a ranking by expected
return. A better terminal value can coexist with a worse drawdown.

| Frozen alternative | Higher / lower / unchanged terminal NAV | Observed tradeoff |
| --- | ---: | --- |
| Fast damage delta 30 to 15 points | 0 / 4 / 20 | All four staggered-damage cases lose $1,213-$6,553 more; worst DD sometimes worsens |
| Slow timer 30 to 15 sessions | 7 / 0 / 17 | Rotation gains $1,072-$6,530; DD improves 1.24-7.44 points; still misses some persistent damage |
| Leadership recovery 8 to 4 sessions | 2 / 1 / 21 | Small mixed effects, -$68 to +$585; usually another condition is binding |
| All three parameter changes | 9 / 5 / 10 | Inherits the more-sensitive-fast-trigger losses |
| PR #432 owned impairment, five bad/eight healthy, zero ceiling | 8 / 8 / 8 | Strong sustained-loss protection, material recovery cost |

Owned impairment improves rotation in all four phases: $11,966-$17,361 more
ending wealth per $100,000 and 11.93-17.38 percentage points less drawdown.
It also improves all four gradual-decline cases. But it loses $2,191-$5,917 in
the four staggered-damage cases and delays some transient-shock recoveries.
At phase 120, for example, staggered-damage terminal value falls from $86,563
to $80,864 with a slightly worse maximum drawdown. In two staggered cases its
restriction remains active at the end of the horizon. These costs rule out
declaring the new zero-ceiling policy universally superior.

Split checks preserve signals, decisions and account value before trades.
Afterward, smaller share denominations legitimately change attainable whole-share
lots: final account differences are $0-$7.06 across phases, not fabricated alpha.
The original 80-session results remain exactly reproduced, including adverse cases.

## Recommended order of improvement

1. **Best small parameter candidate: independently evaluate the 15-session slow
   timer.** It is already frozen in PR #433, improves the intended persistent-loss
   cases across phases, and has no terminal loss in this limited panel. That is
   enough to prioritize it, not enough to change the default. Its principal
   limitation is unchanged: a new anchor, severity and breadth conjunction still
   gate entry. Do not bundle it with the unsupported fast-threshold reduction.
2. **Best architectural direction: retain a separate persistent owned-risk
   cause, but evaluate its response size and recovery together.** PR #432 proves
   the channel can work independently of damage acceleration and leaders. Its
   zero ceiling is costly after damage has already occurred. A concrete next
   challenger is to reuse the existing 0.55 exposure level for this cause while
   leaving shock/slow zero ceilings independent. This partial-ceiling variation
   has NOT been tested here and is not a deployment recommendation. It preserves
   Core's selections and the one-way membrane.
3. **Address recovery at the binding layer.** Define a cause-specific owned-book
   recovery route and test it against rebound-then-relapse cases. A sustained
   recovery of the actual book should be able to resolve an owned-risk cause;
   a still-active independent market/shock cause should continue to restrict it.
   Simply halving leadership persistence cannot release a Native restriction.
   Do not erase all persistence or bypass the old state with a new identity.
4. **Make these decisions explainable at runtime.** Retain the binding gates,
   headcount and dollar-weighted damage, Core cash, owned versus leaders returns,
   elapsed cause ages and recovery blockers. This is a small observability
   improvement with no need to change alpha selection. Dollar-weighted damage
   should first be a diagnostic, not an untested replacement trigger.

The finite next experiment is those two isolated policy candidates plus one
cause-specific recovery candidate, frozen before testing on additional stress
families: rebound/relapse, high volatility without loss, concentrated winners,
repeated shocks, staggered ages, and partial/empty books. Score response latency,
post-signal losses, avoidable missed recovery, turnover and worst-case harm.
Then run a corrected-input, identity-bound historical holdout. Do not choose
thresholds by whichever re-creates 56.27x. No further unlimited parameter sweep
is needed to act on the mechanical diagnosis.

## Research context and practical limits

Moreira and Muir find benefits from reducing risk when volatility is high across
several factor portfolios. That motivates distinguishing a *risk level* from its
acceleration; it does not validate Sentinel's particular thresholds, long-only
book, or a leveraged inverse-volatility replacement.
[Primary paper](https://www.nber.org/papers/w22208).

Bailey and coauthors show why selection across backtests can overfit and propose
a framework to assess that risk. Here no PBO value was estimated: freezing a
small panel and publishing adverse cases limits research discretion but does
not itself demonstrate out-of-sample superiority.
[Primary paper](https://www.davidhbailey.com/dhbpapers/backtest-prob.pdf).

The historical source is mixed across prior reviewed fixes, uses supplemental
actions and some provisional terminal proxies, and has known archive defects:
SILV issuer/sector from August 21, 2018, IIVI preferred/common classification from
August 2020, and Chesapeake/EXE identity/sector. A corrective replay must start
before the earliest affected input (at least before August 21, 2018 for this
known set), not merely before August 2020. The 2011 example and generated markets
do not depend on those later errors. Later observations diagnose the mechanics
of the retained tape, not a claim that its data are economically authoritative.

The scalar historical ablations do not exercise complete daily broker execution.
The synthetic accounts exercise production projection and deterministic local
fills, not durable broker transport, native fill/cash finality, real slippage or
NAS recovery. Certification gates remain open. Numerical reproducibility,
policy suitability, and deployed economic correctness are distinct claims.

## Reference comparison retained as supporting evidence only

The reference remains 56.27x / 22.32% CAGR. Tape-substitution diagnostics assign
about 89% of the log-wealth gap to exposure timing, with an interaction term;
off-diagonal combinations are not executable strategies or unique causal
estimates. This guided selection of the three observation windows. Recovering
the reference return is explicitly not the acceptance criterion for the
improvements above.
