# Four fixed exit and recovery hypotheses

The owner authorized a separate test of exit and recovery logic after reviewing
the three-state hindsight oracle. Freeze four cases before inspecting their
results. Keep the fractional Core path, native severe signals, recovery
predicates, costs, next-open timing and action set 0/55/100 unchanged.

1. Baseline: recorded production Sentinel.
2. Earlier partial exit: change owned-impairment entry confirmation from five
   qualifying closes to one. Preserve the impairment predicate, eight healthy
   closes to release, and all native severe exits.
3. Recovery bridge: while native exposure is 100% and the recorded recovery
   stage is holding zero with FULL_RISK_HELD, permit 55%. Keep existing full
   recovery criteria for 100%; any renewed native severe zero still dominates.
4. Combined: both changes above.

This is a causal, fixed-hypothesis comparison, not an oracle-label fit or a
parameter sweep. Use only contemporaneously recorded native targets, recovery
targets/reasons, and owned-impairment/healthy predicates. Reconstruct the owned
confirmation latch from the common initial recorded state. Its baseline replay
must reproduce every recorded active flag, counter, reason and final target.
The experimental counter implementation is research-only; no production rule
or module is patched. Bind the canonical controller source files and confirm
the recorded predicates are strictly boolean. Prove prefix invariance and that
future-record changes cannot affect earlier decisions.

The compact champion's recovery state uses previous/effective **native**
exposure, not the final owned/executed exposure. Its native/recovery inputs are
therefore invariant under these final-exposure experiments. The owned latch
uses Core predicates independent of final exposure. This permits a fixed-input
decision replay without rerunning stock selection or inventing broker feedback.
Validate native/recovery/owned composition on every source row; refuse
unrecognized reasons, actions or source identities.

Use the authenticated April 16, 2019 snapshot retained by the oracle as the
diagnostic sample. Share the original baseline-close state and preserve the
first funded-open transition exactly. Decisions at a close affect only the
following open; never apply a same-day close signal to that day's return. For
arbitrary later selected windows, build the candidate state through the whole
available prefix before rebasing the chosen window, so boundaries do not erase
candidate history. Carry each candidate's own prior held exposure across the
window boundary. Do not silently force all candidates back to actual exposure.

Report CAGR, wealth multiple, daily-close maximum drawdown, longest time below
a prior peak, exposure changes, modeled overlay costs, and results of each
recorded defensive episode. Show baseline/variant exposure and drawdown paths,
monthly and yearly results, and improvement concentration across episodes.
Allocation turnover includes the original funded deployment, including the
purchase of the T-bill sleeve when the initial Core allocation is zero. Count
exposure switches separately; this initial funding is not an allocation change.
This inspected prefix is hypothesis-generation evidence. Keep the four rules
fixed for later fractional replay periods and future paper observation; do not
label this same-sample comparison out-of-sample validation or deploy a winner.

The main backtest's independent BEL data refusal is handled by a separate
source-backed recovery. These experiments neither modify it nor qualify PAPER.
Develop this extension on the existing PR #597 research branch. Validate only
the new research behavior and its directly used accounting/provenance code.

## Retained diagnostic results

The frozen cases were run on 3,200 closes from 2006-07-31 to 2019-04-16,
using source binding
`163f3a826449fe4b6e72a481814643f3875d4ce230bc36c03397447b70134651`
and checkpoint
`c68548da9c469f6d59df584434816d47754eba9c759b1d3708e7c65f1b2ec002`.
The final report is retained locally under
`.codex-tmp/fractional-exposure-oracle-evidence-20261115/logic-002/`.

| Case | CAGR | Multiple | MaxDD | Changes | Longest underwater |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline | 14.7286% | 5.7331 | 21.8318% | 18 | 322 sessions |
| Earlier partial exit | 14.2364% | 5.4282 | 20.7846% | 20 | 322 sessions |
| Recovery bridge | 13.6922% | 5.1086 | 22.4676% | 28 | 413 sessions |
| Combined | 13.2044% | 4.8369 | 22.4676% | 30 | 413 sessions |

The earlier exit changes 33 applied exposure sessions. Four earlier defensive
sessions in January 2008 and October/November 2016 help, but a separate March
2008 episode dominates the loss. March 10 meets the existing impairment
predicate for one close; March 11 no longer meets it. The one-close entry has
already activated, and the unchanged eight-healthy-close release keeps the
candidate at 55% for 25 sessions. Including the transition back to the common
exposure on April 16, baseline earns 24.3549% and the variant 15.7147% over
March 11-April 16. The five-close confirmation filters this transient alarm.
This is an interaction between entry confirmation and persistent recovery,
not evidence that every earlier risk reduction is harmful.

The recovery bridge changes 214 sessions and raises mean exposure from 80.49%
to 84.17%. It enters when the severe signal switches off, before the recovery
gate certifies full risk. Some rebounds reward this, but several fail. Over the
shared defensive windows, baseline versus bridge returns are +0.76% versus
-6.69% in August-November 2011, and +2.87% versus -2.63% in August 2015-March
2016. The nine separate bridge-entry stretches include both helpful and harmful
outcomes; the blanket bridge is not an improvement. The worst drawdown shifts
from the 2007-2008 episode to June 2008-June 2009.

Additive log-wealth attribution confirms the mechanism: earlier exit loses
0.0546450 log units relative to baseline, of which 0.0009002 is additional
overlay cost; the bridge loses 0.1153361, of which 0.0021991 is additional cost.
Most of each loss is exposure timing. Their changes do not overlap on this
sample; the combined log-wealth effect is the sum. No rule was retuned after
these results. Neither change improves CAGR; earlier exit offers a modest
drawdown reduction at a growth cost. Retain baseline pending later-period
validation. Any selective recovery hypothesis must be separately frozen and
validated rather than inferred from the hindsight winner.

Validation command:

```bash
python -B -m pytest tests/sentinel/test_exposure_logic.py \
  tests/sentinel/test_exposure_oracle.py -q -p no:cacheprovider
```

Result: **49 passed** in the pinned Python 3.12 image. In-memory removal of
the recognized-zero-reason and baseline-state guards, and shifting a decision
one session early, each makes its selected falsifier fail. The real replay
reproduces every baseline state, target and ordinary canonical accounting
transition. A reporting correction includes the original funded deployment in
turnover; the retained first and final runs have identical NAV, exposure,
drawdown, gross-return and cost paths for all four cases. The final paths JSON
has SHA256 `9070399b73e25f2860042031953f57dccc6feff71742e084cf8921f7cd9f1e39`.
The report generates successfully with embedded Plotly; no browser was available
for interactive visual inspection. Monthly and yearly output remain available.
