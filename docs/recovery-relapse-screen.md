# Recovery bridge: entered-risk screen and monotone release challenger

## Registration before implementation and results

2026-09-22. This research follows PR #438. Verified base is
`ee23c894c97a2c4023654ce3a56a62728f5b061e` by `git fetch origin main`.
Delivery is a new feature-branch PR against main. Production configuration,
Wealth Core, source history, prior artifacts, NAS and brokers remain untouched.
Required architecture documents were read in the preceding experiment; the
unchanged base and relevant execution/compact champion contracts were checked
again for this specific change. No broad review or parameter sweep is planned.

Freeze exactly one additional policy: **sign-confirmed bridge**. Start with
PR #438's recovery bridge, including Owned55. In its underlying CandidateA
cross-surface recovery predicate change only `leaders_r20 >= core_r20` to
`leaders_r20 > 0`, and `spy_r20 >= core_r20` to `spy_r20 > 0`. Retain positive
Core r20, eight consecutive positive leaders observations during Native recovery,
all finite checks, full leadership persistence, native FAST/SLOW independence,
the divergence cap, owned impairment and bridge thresholds. Thus improved Core
r20 cannot by itself disqualify this release from an identical prior state.
This fixes a local monotonicity defect in the research challenger. It does not
prove globally ordered exposure for different multi-day state trajectories or
that signs alone are sufficiently strong economic recovery evidence.

The old relative comparison was intentionally stringent. Removing it may
release full exposure too early, especially when the owned book recovers much
faster than the market. This is an explicit risk tradeoff to test, not a claim
that an arithmetic error caused the historical returns. Policy identity binds
the transformed source; old-policy checkpoints cannot be restored into it.

## Finite synthetic panel

Use the two already retained useful prefixes from PR #438: 40-session formation
with `owned_recovery`, and 120-session formation with `leaders_recovery`.
Keep the canonical 252-session warmup, sixty-name universe and 120 scenario
sessions. Four controls/challengers share the same canonical Core: current,
Owned55, old bridge and sign-confirmed bridge. Accounts follow prior-close
snapshots at the next open, with whole shares, $100,000 and 10 bp costs,
exactly as documented in #438. This is still not a full broker replay.

For each prefix run four paths (eight total). The unchanged prefix is a retained
economic/control oracle for the first three variants. In each other path,
observe the **old** bridge's first incremental 55% close decision, let it execute
at the following open, and apply stress at the *next* open. The shock date is
therefore fixed by a past control decision, never by future return or by the
new candidate's response. All variants receive identical prices. A stress path
without actual old-bridge stock ownership before stress fails coverage.

| Path | Frozen stress on top of the retained price formula |
|---|---|
| Control | No change |
| Relapse | All equities multiply by .97 each day for ten sessions; SPY by .995. Apply the additional move at the open, retain the base intraday factor. |
| Overnight gap | All equities multiply by .80 at the stress open; SPY by .94. Retain base intraday factors. |
| Changing holdings | First half (sorted permanent IDs) of the previous-close Core holdings multiply by .65 at stress open; SPY by .97. No additional shocks afterward. The canonical Core alone decides subsequent stops, replacement and reviews. |

Adjust raw open, raw close and signal close consistently; carry the changed
price levels forward. Do not alter future signals, labels, exposure or cash by
hand. Whole-bar scaling puts the additional loss overnight rather than dividing
it between open and close. Record actual bridge ownership, cash/stock fraction,
each cause, response latency and Core membership before/after stress. Restart
Core/controllers/accounts around entry, fill, gap and recovery transitions.

## Fixed acceptance and decision

Keep #438's research budgets: reject historical continuation if any stressed
candidate loses more than $2,000 terminal value versus Owned55, worsens maximum
drawdown by more than two percentage points, or adds more than $250 fees.
Apply the same screen separately to the old and new bridge; retain every loss.
Report gap attribution and maximum interim shortfall separately. These are
screening budgets, not a guarantee of bounded loss or production risk approval.
In particular a 20% gap with substantial prior stock exposure can exceed them;
that is exactly the risk being tested, not grounds to reduce the shock or
loosen the budget afterward.

Require exact parent-control parity, next-open ownership, correct independent
overnight/intraday/cash accounting, prior-artifact preservation and restart
identity. Add an independently enumerated fixed-state monotonicity test,
native-zero and missing-input falsifiers, and mutants that restore either
relative comparator or let the gap move only the close. No calibration changes
are allowed after results. If either bridge fails, report rejection and do not
start a long replay of the failed policy. If the repaired candidate passes all
coverage and economic gates, the authorized next step is its frozen 20-year
comparison; do not infer production promotion or economic certification.

## Outcome: reject both candidates under the frozen budgets

Registration commit: `d09c7394`, before implementation and results. All eight
paths completed. Both bridge variants fail all six entered-stress cases; the
two unstressed controls improve as before. The twenty-year continuation is
therefore **not started**. No threshold, shock or budget was adjusted to rescue
either candidate. Production remains the current controller.

Terminal differences and extra drawdown below are versus Owned55, starting at
$100,000. Extra drawdown is deterioration in percentage points, not relative
percent. Fees stayed within the $250 incremental-fee budget throughout.

| Formation / stress | Old bridge terminal difference | Sign bridge terminal difference | Old bridge extra drawdown | Sign bridge extra drawdown |
|---|---:|---:|---:|---:|
| 40 / no stress | +$2,221 | +$2,221 | 0.00 pp | 0.00 pp |
| 40 / relapse | -$3,556 | -$3,556 | 3.07 pp | 3.07 pp |
| 40 / overnight gap | -$8,756 | -$8,756 | 8.12 pp | 8.12 pp |
| 40 / changed holdings | -$7,621 | -$7,621 | 7.14 pp | 7.14 pp |
| 120 / no stress | +$2,108 | +$4,330 | 0.00 pp | 0.00 pp |
| 120 / relapse | -$2,259 | -$2,501 | 2.04 pp | **10.39 pp** |
| 120 / overnight gap | -$4,874 | **+$990** | 4.28 pp | **7.81 pp** |
| 120 / changed holdings | -$4,045 | -$5,163 | 2.89 pp | 5.34 pp |

The last gap result is particularly useful: a positive terminal difference
would conceal materially worse interim risk. It fails the drawdown budget
despite ending ahead. The experiment was adversarial by design and conditioned
on earlier entry. It establishes possible loss and rejects these fixed risk
budgets; it does not estimate event frequency, expected CAGR, or prove that the
existing controller is globally optimal.

## What the mechanics show

**The comparator inconsistency is removed in the research policy.** The exact
former witness now returns full exposure for both +1% and +3% Core r20, with
leaders/SPY at +2%, from the same prior state. An independent truth table covers
192 combinations of prior state and other inputs, each with six ordered Core
returns (1,152 transitions). Native zero, divergence caps, missing/nonfinite
inputs and persistence remain enforced. Removing an economic constraint is
nevertheless a design tradeoff, not proof that the old arithmetic was broken.

**Early entry creates genuine overnight risk.** In the 40-session gap case,
the bridge has bought stocks at day 41's open before the extra 20% loss at day
42's open. Its additional shock loss is $8,629.24, borne by *previously owned*
shares. Current/Owned55 are still defensive at that instant. Closing evidence
and subsequent liquidation cannot erase this loss. In the rebuilding-book gap,
the old bridge loses $4,590.38 and the sign bridge $8,384.62 at the event open.
This is causal account ownership, not same-close execution or a valuation bug.

**Full release closes the recovery episode too definitively.** In the
120-session relapse, at day 32 the old bridge allows 55% and the sign rule
allows 100%. Both execute at day 33's open; relapse starts on day 34. Core r20
turns negative on day 36, so the old bridge withdraws at day 37's open. The
sign-confirmed full release already cleared its recovery episode: it remains
at 100% through day 44 even as r20 deteriorates to roughly -10%, damage reaches
100% and green reaches zero. The independent owned-impairment channel finally
caps it at 55% on day 45's close, effective day 46. Native is still full in this
interval. This explains the extra 10.39 pp drawdown; it is not a timing defect
in the new account model.

**Book rebuilding changes the effective exposure.** In that relapse the Core
stock fraction grows from about 51% on day 32 to 93% on day 41 as admissions
continue. A fixed 100% Core allocation therefore almost doubles the live stock
fraction during deteriorating prices. The controller is not choosing holdings;
it must assess the changing book that Core actually owns. The half-book shock
does exercise real changes: ten pre-stress holdings disappear in the first
formation and five in the second over the next twenty sessions, through
canonical stops/replacement rather than manual edits.

## Dynamic range and the next design decision

This experiment provides more precise evidence than saying the signals have
"enough range". In the rebuilding relapse, returns deteriorate while damage
remains zero through day 38. Then count damage moves through about 65%, 78%
and 100% on days 39–41. Those are reachable measurements, but coarse and lagged;
at 100% further deterioration is invisible to that breadth measure. Meanwhile
green drops from 100% to about 87%, 25%, 18%, 6% and zero. The problem includes
both sensor semantics and the controller state that is allowed to use them.
Increasing numeric precision or lowering a single threshold does not establish
a safe cure.

The existing leadership hold is **load-bearing protection** on these false
recoveries. The result argues against simply weakening it to obtain earlier
upside. Retain current production behavior. If research continues, the next
explicit design decision should be whether a recovery remains provisional
after admission, with a revocable owned-risk permission and bounded exposure
while the book rebuilds. Separately choose an acceptable gap-loss budget: no
close-based health signal can guarantee avoidance of an overnight gap. Neither
choice is implemented or optimized here; both require a new frozen experiment
and honest adverse-loss criteria.

## Validation and limitations

- All **3,840 account-days** reconcile independently from regenerated price
  paths, prior holdings, signed trades, fees, overnight P&L and intraday P&L.
- Two retained controls reproduce all 720 prior account-days exactly for
  current, Owned55 and the old bridge, including decisions and balances.
- 960 scenario closes preserve canonical current-controller parity and Native
  state parity in the changed policy. 108 Core restart pairs and 432 each
  controller/account restart pairs pass at fixed cuts and actual transitions.
- 23 focused tests pass. Five policy/price/identity mutants are killed, and a
  separate same-close execution corruption is rejected by the retained-trace
  auditor. Syntax, staged whitespace and repository ownership checks pass.
- Every stress hits actual preexisting bridge stock ownership. Detailed price,
  position, cause and cash traces are retained; no original result is repinned.

These are 60-security deterministic market paths and snapshot-following whole-
share accounts with zero-yield synthetic bills, not probability estimates,
authoritative historical-data results, complete execution/reconciliation tests
or deployment qualification. This experiment changes no production code.
Exact commands, immutable dependencies and evidence are in
`audit/recovery-relapse-screen/README.md`.
