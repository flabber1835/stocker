# Persistent owned-book impairment: versioned Sentinel challenger

Owner-authorized design correction, 2026-09-21. Base:
`da7b64a9429c9c73fb7efac90c8d4a5decb39e13`. Separate branch and PR;
research evidence is PR #431 at `0070f4109257d6b42078ed081fe5ded347cf221f`.
This specification is recorded before implementing or running the challenger.

## Contract and scope

Sentinel must be able to restrict exposure after persistent severe damage to
the actual owned Core book even when damage is already widespread, volatility
is not accelerating, and newly ranked leadership is strong. Preserve the
existing shock/slow Native and Candidate A behavior as independent causes.
Wealth Core's holdings, signal domains, cash, review, stops and cooldowns remain
owned by the canonical engine. No broker or realized-account inputs enter a
controller decision.

Add strategy `sentinel-compact-champion-owned-v1` as an explicit selectable
profile through the production identity resolver and kernel. Keep the existing
production default and frozen champion available; this PR implements the
versioned correction for validation, not a silent deployment/authority switch.
Its rule digest includes the old champion digest and the entire new rule.
Source identity includes the new implementation. Adoption needs a fresh
identity-bound formation/replay and normal signed authority; never relabel an
old checkpoint or initialize missing memory in an already-running new profile.

## Complete state machine

Evaluate once at each canonical session close, after the old champion:

- Entry: Core drawdown <= -10%, held damaged breadth >= 88%, and green breadth
  <= 20%, for **five consecutive observations**. No breadth delta, market
  return, short-return or volatility condition is required. These severity
  thresholds come from the existing shock definition; five is an explicit
  trial response deadline, not a statistically calibrated optimal duration.
- On the fifth qualifying close latch owned impairment. Its exposure ceiling
  is zero. Final target is `min(existing champion target, owned ceiling)`.
  Other causes advance normally and can continue restricting exposure.
- Recovery: while latched, require **eight consecutive** observations of
  Core r20 > 0, damaged breadth <= 63%, and green breadth >= 20%. Release only
  on the eighth. These use current *owned Core*, not the leadership witness.
  Core drawdown need not reach its old peak. Eight is the existing recovery
  persistence scale, used as a trial setting, not proof of market suitability.
- Nonqualifying or unavailable observations reset the relevant consecutive
  streak. Missing evidence cannot clear an existing latch. An empty book has
  zero damaged/green breadth: it cannot trigger entry or count as recovery.
  Core can rebuild independently while the account remains restricted; later
  healthy ownership can release the latch. Cash is never renormalized to stocks.
- No independent timeout, speculative early re-entry or extra cooldown. After
  release a fresh run of five bad observations can enter again. This permits
  a new regime of losses to be protected without requiring an old peak recovery.
- Snapshot stores schema, active latch, bounded entry/recovery counters and
  last session. Duplicate/out-of-order sessions, malformed state, missing state
  for the new identity, or state carried under another identity must refuse.

This fixes the specified detector blind spot, not all possible drawdowns. A
close decision is actionable only subsequently and cannot avoid prior/gap loss.

## Integration

The added state is a discriminated optional field in canonical SessionState:
mandatory only for the new profile; omitted for older profiles so their state
encoding stays stable. Canonical JSON, state hashing, warmup, kernel catch-up
and restore own it. The kernel publishes the old champion target, new cause
evidence and final target. Execution consumes the final target through its
existing boundary. No new broker path or account-mutation service is added.

## Predeclared validation

Reuse PR #431's generated markets unchanged: healthy, shock, staggered damage,
gradual decline, temporary correction, rotation and split-neutral control.
Use 252 feature-warmup sessions, 80 production formation sessions and 120
scenario sessions, $100,000 starting capital. Both identities form their books
from their own fresh canonical states; never seed or relabel a book. Compare
Core ownership/accounting exactly between identities while controller memory
and final targets may differ. Test restart during entry, restriction and
recovery; missing observations; false runs of four bad/seven healthy sessions;
re-arming; and corruption/identity rejection. Kill deliberate guard mutations.

For a bounded economic comparison, simulate an independent account at each
scenario open using the **previous close's** controller scalar and the Core
ownership/cash resulting from that open's previously decided fills. Feed raw
open marks into production whole-share projection; sell first, buy only within
cash including 10 bps transaction costs. The defensive holding is a synthetic
constant-price bill (zero yield), deliberately not a historical rate estimate.
Close marks value the account without another trade. Current close signals must
not affect same-open sizing; falsify that with altered closes at fixed opens.
Both accounts use identical inputs, fills/cost conventions and capital. Record
terminal wealth, worst drawdown, fees/turnover, first reductions and recoveries.
These account mechanics exercise projection but not durable broker transport,
real slippage, dividends, missing bars or provider finality. Report them as
synthetic sensitivity evidence, never historical expected returns or CAGR.

The independent accounts begin with $100,000 at the scenario-origin close,
project the already-formed Core there (paying the same initial costs), and carry
that ownership into the first scenario open. This ensures a day-zero overnight
shock is not accidentally avoided by starting the account empty after the gap.

No optimizing/revising thresholds after viewing returns, dropping failed
scenarios, changing golden artifacts or claiming certification. Retain adverse
tradeoffs. Promotion and real-data/NAS qualification remain separate.

## Implemented result

The new profile is wired into `sentinel.strategy.controller_for_identity`,
`SessionState.fresh/from_dict/to_dict`, the canonical session kernel, and its
source identity. Select it for an isolated evaluation with
`sentinel.strategy.owned_impairment_strategy()`. `production_strategy()` still
selects the existing champion. The default is deliberately not promoted on
these mixed synthetic results. Merging the implementation alone does not
enable the new policy for an existing account.

The universal implementation/source digest still changes when this code is
merged, including for the retained default profile. Existing source-bound
checkpoints and authority must follow the normal rebuild/requalification path;
unchanged default policy is not permission to hot-relabel old runtime state.

`sentinel/controller/owned_impairment.py` owns the rule, strict typed snapshot
and transition. The kernel applies its ceiling after the existing champion;
the final decision and top-level reason retain the owned cause. The complete
snapshot must have the same session cursor as its canonical envelope. Missing,
coerced, contradictory and cursor-detached state refuse rather than resetting
the protection. The final target continues through existing execution-plan
projection; pinned rollout/authority behavior has not been changed.

### Synthetic account results

All rows cover the same 120 generated scenario sessions, $100,000 per account,
whole shares, 10 bps per trade, and a zero-yield synthetic defensive bill.
These are final marked account values, with no forced terminal liquidation.
The earlier research's Core shadow drawdowns are different measures.

| Scenario | Current final NAV | New final NAV | Difference | Current max DD | New max DD |
| --- | ---: | ---: | ---: | ---: | ---: |
| Healthy | $111,311.54 | $111,311.54 | $0.00 | -1.82% | -1.82% |
| Synchronized shock | $86,153.21 | $85,250.05 | -$903.15 | -17.57% | -17.56% |
| Staggered damage | $84,209.31 | $82,018.17 | -$2,191.14 | -21.58% | -20.82% |
| Gradual decline | $89,560.79 | $90,018.86 | +$458.07 | -12.93% | -12.01% |
| Temporary correction | $94,351.03 | $94,351.03 | $0.00 | -15.25% | -15.25% |
| Leadership rotation | $77,174.44 | $89,140.30 | +$11,965.86 | -25.89% | -13.96% |
| Healthy plus split | $111,311.54 | $111,311.54 | $0.00 | -1.82% | -1.82% |

The owned channel enters staggered damage on day 19, gradual decline on day 31
and rotation on day 19; the old champion never reduces in those three paths.
Decisions apply at the next open. The new channel releases on days 71, 103 and
70 respectively. No return objective selected those timings or their constants.

In rotation the rule addresses a large loss to owned capital while new
leadership remains strong. In staggered damage, much of the loss has happened
before the fifth severe close; subsequent recovery is missed while the new
channel remains active. Extra transaction costs and delayed recovery lower
terminal wealth despite a slightly shallower worst drawdown. In the synchronized
shock the original detector already enters on day zero, so the added channel
provides almost no extra drawdown protection and delays release from day 69 to
74. In the temporary correction both complete controllers return on day 15;
the extra cause does not change the final target path there.

This closes the demonstrated persistent-impairment entry gap under the stated
contract. It does **not** establish a universally better controller or improved
historical CAGR. The asymmetric costs are a reason to retain separate identity
and explicit adoption, not to tune the five/eight-session settings until these
scenarios all look favorable.

### Verification and unresolved work

See [exact commands and artifacts](../audit/owned-impairment/README.md).
Twenty-five new-controller/account checks and 52 focused compatibility
regressions pass. Four mutations are killed, including bypass of the new
ceiling in the full production-kernel test. Both strategies independently form
the same book; all 840 paired scenario transitions have identical Core state,
ledger and controller observations. There are 112 successful selected
production-state restart comparisons. Neutral split observations and decisions
match their control. The final rerun preserves every initial economic summary.

The production tests also include a separate generated declining book in the
protected champion CI suite. That fixture can activate the old 0.55 leadership
ceiling; its corrected assertion distinguishes that existing partial restriction
from the new zero ceiling instead of assuming the old strategy remains at one.
During implementation the corruption test caught Pydantic's Literal coercion of
`True` to schema 1; a pre-coercion exact-type check fixes it. A Windows pytest
scratch-directory permission error was resolved with explicit local scratch
paths. No production threshold was revised to resolve these test failures.

Still unestablished: calibration across review-age phases, broad market
distributions, real gaps/slippage, provider finality, actual defensive returns,
durable broker execution, held-out historical performance and NAS qualification.
One deterministic family is not a market distribution, and an earlier exit
cannot guarantee a maximum loss. Existing certification gates remain open.
