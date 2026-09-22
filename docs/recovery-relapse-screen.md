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
