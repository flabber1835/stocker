# Twenty-year comparison: partial owned-book impairment

Owner-authorized 2026-09-22. Registered before implementation and results.
Verified main: `ee23c894c97a2c4023654ce3a56a62728f5b061e`; isolated feature branch
`codex/owned55-twenty-year`, Git/gh PR-only delivery targeting main. No self-merge.

## Question and frozen intervention

The August 2011 observation proves that the fast detector's five-session damage
acceleration can become mathematically unreachable after damage is already
widespread. Shortening the existing slow timer from 30 to 15 sessions does not
repair that defect because the remaining breadth gates can stay false until both
timers have elapsed.

Evaluate one challenger derived from PR #432 at commit
`7250ce3d65cc38a103989d460fe3c557a38343c8`. Preserve its independently
versioned owned-book state machine and every entry/recovery threshold:

- enter after five consecutive closes with Core drawdown <= -10%, damaged
  breadth >= 88%, and green breadth <= 20%;
- recover after eight consecutive closes with owned Core r20 > 0, damaged
  breadth <= 63%, and green breadth >= 20%;
- missing/nonqualifying evidence resets the relevant streak and cannot clear an
  active cause;
- preserve the old champion as an independent cause.

Change only the owned cause's active exposure ceiling from zero to **0.55**.
The final target is `min(current champion target, owned ceiling)`. Existing fast
and slow causes can therefore still require zero exposure. Do not add a timeout,
second escalation clock, leadership-based release, or any other parameter.
This is the finite partial-ceiling challenger proposed in
`docs/sentinel-mechanical-fitness.md`, not a production-default change.

## Comparable replay

Run one fresh canonical production Wealth Core stream from January 3, 2006 with
$100,000 and the same frozen broad-universe PIT archive, classification overlay,
supplemental action evidence, and SPY/BIL factors used by the prior replay.
Measure both accounts from the July 31, 2006 close through July 31, 2026.

The control uses the embedded current production controller. A research adapter
must reproduce its target and native state exactly at every close. The challenger
wraps that same current transition with the frozen owned state machine. Wealth
Core cannot observe either account or target. Both accounts use the production
scalar accountant independently: the prior close's decision acts at the next
open, the old allocation bears the overnight return, and 10 bps is charged on
changed allocation. Verify each transition with independent Decimal arithmetic.

The stopped Slow15 experiment and its golden artifacts remain immutable. It is
not a seed for this controller identity. This replay starts both controller
memories and both accounts from genesis; checkpoints bind all source, input,
policy, cursor, and economic state. A restart must refuse changed identity or
inputs. Stop on production/data refusal rather than inventing action evidence.

## Acceptance and interpretation

Before the long run, require focused tests for exact PR #432 rule inheritance,
the sole 0.55 delta, five-bad/eight-healthy boundaries, independent old zero
causes, next-open ownership, and cross-identity/cursor/state refusal. Kill
deliberate guard mutations. During the run, retain complete observation,
decision, target, cause, and economic rows plus periodic restart checks.

At completion require every expected archive session exactly once, independent
CAGR/multiple/drawdown recomputation, exact control parity, account continuity
across all segments, and episode attribution including 2011 and adverse rebound
costs. Report whether the challenger actually becomes reachable before the old
controller in 2011; do not assume it does. Do not select or revise constants
after viewing the result.

Known archive classification mistakes, supplemental action proxies, and scalar
execution assumptions persist. This is provisional economic research, not NAS,
broker, provider-finality, production-promotion, or economic-certification
evidence.
