# P00: provisional recovery with an independent recovery watch

## Owner authorization and fixed comparison

On 2026-11-08 the owner authorized proceeding with existing Core and a new
research Sentinel mechanism after the read-only mechanism assessment. Keep
original P00 Core, its immutable holdings, input epoch, formation, accounting
and all recorded observations fixed. Compare exactly three controller paths:

1. `P00_FROZEN_SENTINEL`: original Sentinel, an exact saved-path control.
2. `P00_NO_EXTRA_RECOVERY_HOLD`: the previously admitted single-change control.
3. `P00_RECOVERY_WATCH_RW1`: that same no-extra-hold controller plus the single
   recovery-watch rule below. Keep Native, leadership and Owned55 unchanged.

This is one fixed mechanism experiment, not another parameter search. Original
twelve-arm and Control/VOL075 backtests remain stopped. No new Core transition,
production policy, PAPER/LIVE contact, broker action, installation or merge is
authorized. The watch reads published Core observations and its own state;
neither broker state nor realized or hypothetical funded exposure enters it.

## Evidence, earlier failures and limits

The P00 audit found that ordinary stress cleared on 2022-08-03 while Core was
21.38% below its high. The ordinary rearm/slow-base requirements then prevented
slow protection during a renewed decline. Retaining memory alone is inadequate:
on September 16 Core r20 was negative with broad damage, but r40 still included
the earlier rebound; the existing slow severity triple first qualified on
September 23, after most of the August 25 to September 26 decline. These are
inspected-history observations, not unseen predictive evidence.

The earlier absolute-drawdown governor G was rejected and stays rejected. RW1
instead measures deterioration from a recovery-local Core peak and requires
both negative r20 and broad damage. The September recovery-relapse screen also
rejected early recovery bridges, including failures after restored exposure and
overnight gaps. RW1 does not repair those old results or prevent losses on a gap
already held. Retain synthetic relapse, false alarm and overnight-gap evidence.

Constructive 2019/2020 recoveries are explicit counterexamples to a blanket
post-recovery cut. Report every watch episode, including those with no entry,
and every defensive window; do not report only 2022. This history has already
been inspected repeatedly. Later chronological blocks are historical checks,
not untouched out-of-sample evidence.

## Frozen RW1 lifecycle, before implementation

The standalone state has schema `research.p00-recovery-watch-rw1/1`, mode
NORMAL/PENDING/WATCH, optional positive peak, active-cap flag, consecutive
healthy count, and a strictly ordered session cursor. Native stress means any
of `ordinary`, `base_fast`, `fast`, or `slow` is true after the current Native
step. It does not mean the final exposure is below 100%.

Process each close in this order:

1. NORMAL becomes PENDING if Native stress is present. PENDING waits through
   stress. The first subsequent close with all four flags false starts WATCH
   and initializes its peak to current published Core NAV.
2. In WATCH ratchet peak to max(previous peak, current Core NAV), including
   closes with renewed Native defense or an active RW1 cap. Never reset peak
   merely because exposure is restored, Native stress returns, or RW1 releases.
3. If the cap is inactive, enter a 55% ceiling on one close jointly satisfying
   Core NAV / recovery peak - 1 <= -0.05, Core r20 < 0, damaged breadth >= 0.75,
   and green breadth <= 0.25. There is no r40, stress-age, acceleration or
   confirmation-delay gate. Entry resets the healthy count to zero.
4. An active cap releases after eight consecutive closes with Core r20 > 0,
   damage <= 0.63 and green >= 0.20. Any unhealthy close resets the count.
   Release leaves mode WATCH and preserves the peak, allowing another leg to
   trigger without a new global high or Native arming event.
5. Clear the watch and peak only when its cap is inactive, all Native stress
   flags are false and Core global drawdown > -0.06. This deliberately spans
   Native ordinary rearming at -15.5%; it is a separate recovery episode, not
   a modification of Native's latches. Clearing resets the healthy count.
6. Final target is min(unchanged no-extra-hold/leadership/Owned55 target,
   0.55 if RW1 cap is active else 1). RW1 can only reduce that target.

These constants reuse existing FAST loss magnitude (5%), SLOW breadth (75/25),
Owned55 ceiling and eight-healthy recovery, and Native fast rearm boundary (6%).
Applying them to a recovery-local episode is a new design choice, not an
estimated optimum. No parameter changes, extra profile or automatic follow-up
are selected after viewing results.

Require positive finite NAV, valid global drawdown and strictly increasing
sessions. All three breadth/momentum observations must be valid while WATCH;
unavailable observations before WATCH cannot manufacture recovery or entry.
Refuse invalid watch inputs or snapshots; never silently clear active protection
on invalid data. Serialize every field with a distinct policy schema and
validate state/peak/count relationships. Check restart equivalence at every
watch transition and every month boundary, including retained peaks and active
caps. Cross-policy watch snapshots must refuse.

## Accounting, controls and independent qualification

Reuse original completed P00 admission
`65637d23029e0817822c169e7d424e00cd75a01703cb22a6aeb1b3f69b390f83`,
checkpoint `352d3ad9c74d29d34faae0e07a1a592bc9b6921259a016298bd93e62c7188978`:
126 formation observations and 2,156 measured closes, 2018-01-02 to 2026-07-31.
Authenticate original encrypted evidence before parsing. Preserve all original
repairs, source epochs, price domains, BIL inputs and uncertainty qualifications.

Use hash-bound frozen parent source
`a67bb21df8df12f1e411bfc9a562eb62180df4e1fd6f9e94c1e845a9f0978fb5` and
the existing no-extra-hold AST compiler. Require Native AST equality and exact
leadership/Owned55 identity. The first two paths must reproduce their previously
admitted target hashes and every original baseline funded-account field;
compare their complete prior account journal commitments as well.

The worker executes actual frozen Native/CandidateA/Owned55 plus the standalone
watch. Independent equations produce the base paths and a separately written
watch state machine; compare every target and watch state. The independent
reviewer recomputes paths without reading worker states as inputs. Complete
canonical Account.advance paths for all three profiles use the existing exact
next-open semantics, formed entry, old exposure overnight and ten-basis-point
allocation-turnover costs. Independently verify every factor, NAV and monthly
continuation. No weighted-return proxy or alternate Core/account book.

All real-input financial decisions, canonical imports/calls, synthetic canonical
canaries and restores run only in credential-free, network-disabled hosted
containers with read-only sources. Local work is DATA/AST/inert DTO qualification
only, under canonical import fences. Preserve the existing container/capacity,
transport-root and UNKNOWN-stop guards. Require positive stopped worker and
independent reviewer, plus independently authenticated whole output, before
admitting performance. A failure requires a new source/request generation;
never rerun a stopped failure blindly.

Hosted synthetic falsifiers cover no pre-stress watch, pending stress, recovery
peak initialization/ratchet, each missing conjunction term, active cap under
Native zero, repeated relapse after release, eight healthy closes/reset, watch
termination, missing inputs, snapshot/cursor refusal and prefix causality. Replay
smooth constructive recovery and a renewed decline; an already held overnight
gap remains charged before the new decision can change exposure.

## Reporting and decision

Report full and annual CAGR/wealth, maximum drawdown with peak/trough/recovery
dates, longest underwater duration, turnover/exposure changes, 2018-2020,
2021-2022, 2023-2024 and 2025-July2026 blocks, all original defensive windows,
all watch episodes and changed targets versus no-extra-hold. Show gains/losses
around every cap separately, including constructive recovery opportunity cost.
Distinguish same-close decisions from next-open held exposure.

No profile is selected from later results: there is one candidate. Assess its
incremental benefit versus no-extra-hold and its protection/growth tradeoff
versus original. A lower CAGR than the improved no-extra-hold control is not
automatically failure if protection is worthwhile. Compare the already declared
20.01% CAGR / 27.04% drawdown frontier candidate as context; additional complexity
needs a benefit beyond a tradeoff already available. Report negative results
and prolonged recoveries explicitly. Any future promotion or truly untouched
validation is separate work.

Freeze the interpretation before observing RW1: a joint-improvement claim
requires terminal wealth at least original and maximum drawdown strictly
shallower than original, on the common full path. An incremental-protection
claim also requires drawdown shallower than no-extra-hold. Show both numerical
margins and each chronological block; neither claim establishes robustness.
If an already declared frontier path has at least the candidate's growth,
no deeper drawdown and no longer longest underwater spell, with one strict
advantage, report RW1 as dominated and retain the simpler existing candidate.
No post-result relaxation of these definitions or rescue tuning is selected.

## Verified base and delivery

Git fetch and connected GitHub PR542 independently verified current main
`2714afbb25fd169295358e035cefff59db2bf67d`. Clean research feature head
`5eab564cbf40d0bdb155b058a4572310a0046267` contains it and matches the remote
research head. Reuse that worktree and deliver through existing ready PR542,
target main, pushing only HEAD:refs/heads/codex/capital-risk-research. The new
source-bound request has a separate noncancelling workflow/concurrency identity;
old financial workflows and stopped Core runs are not restarted.
