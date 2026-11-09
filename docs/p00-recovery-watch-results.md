# P00 recovery watch RW1: reject the fixed candidate

## Outcome

The owner-authorized [fixed experiment](p00-recovery-watch-experiment.md) is
complete and independently admitted. Existing P00 Core and all original
observations remained fixed. RW1 fails the predeclared joint growth/protection
criterion and is dominated by an already declared grid frontier candidate.
Do not adopt it, retune it after these results, or restart stopped Core runs.

| Same recorded history, 2018-01-02 to 2026-07-31 | CAGR | Maximum drawdown | Final wealth | Peak to recovery, sessions |
|---|---:|---:|---:|---:|
| Original Sentinel | 19.9551% | -29.3291% | $237,993.46 | 642 |
| Previous no-extra-hold control | 20.5509% | -28.9758% | $248,323.38 | 640 |
| No-extra-hold plus RW1 | 18.6462% | -27.9483% | $216,622.88 | 756 |
| Previously declared GRID_8c4c9f4b11e7404f1ba1 | 20.0093% | -27.0442% | $238,917.29 | 641 |

The final row is context from the already admitted grid, not a fourth path
recomputed or selected by this experiment. It was on the predeclared training
frontier. Its recorded direct journal independently establishes the duration.

Relative to no-extra-hold, RW1 gives up 1.9048 percentage points/year and
$31,700.50 of terminal wealth (12.77%), for 1.0275 points less maximum drawdown.
Its worst episode recovers on 2024-02-15 instead of 2023-08-30, 116 sessions
later. All three new paths retain the same 2021-02-12 peak and 2022-09-26 trough.
The joint-growth floor versus original is also missed. The prior frontier path
has higher growth, shallower drawdown and shorter recovery; it strictly
dominates RW1 under the frozen comparison.

Peak-to-recovery counts include the recovery close. Consecutive underwater
closes are respectively 641, 639, 755 and 640; do not mix these definitions.
The history has been inspected repeatedly and is not unseen validation.

## Why the intended protection failed economically

RW1 did detect the September 2022 deterioration on September 16, effective
September 19. From the signal close to September 26, no-extra-hold lost 4.83%
and RW1 lost 3.34%, saving 1.49 percentage points. From that trough to the
October 26 release close, no-extra-hold gained 11.94% and RW1 gained 6.56%.
The missed rebound was 5.39 points. Eight consecutive healthy observations
completed only on October 26; increased exposure could act on the following
open. Over the full cap interval, the control gained 6.53% and RW1 gained 3.00%.

Memory also became stale. The watched peak last updated on 2022-06-07 and
remained in place until 2023-06-02. January, March and May 2023 entries were
14.11%, 12.17% and 6.57% below that same old peak. They did not require a fresh
five-percent decline from a new local rebound high. This follows the explicitly
frozen peak-retention rule; it is a failed design choice, not a demonstrated
implementation error. The persistent cap and delayed releases reduced
participation in subsequent recoveries.

| Cap signal through release close | Changed target closes | No-extra-hold return | RW1 return | Relative wealth effect |
|---|---:|---:|---:|---:|
| 2021-05-25 to 2021-08-17 | 30 | +5.2237% | +5.3156% | +0.0873% |
| 2022-04-29 to 2022-06-02 | 23 | +7.1993% | +3.8261% | -3.1466% |
| 2022-06-14 to 2022-08-08 | 7 | -5.1730% | -2.7760% | +2.5278% |
| 2022-09-16 to 2022-10-26 | 28 | +6.5328% | +2.9969% | -3.3191% |
| 2023-01-04 to 2023-02-09 | 25 | +6.0899% | +3.4105% | -2.5256% |
| 2023-03-17 to 2023-04-05 | 13 | +8.2526% | +4.7312% | -3.2530% |
| 2023-05-03 to 2023-06-06 | 23 | +8.7948% | +4.7688% | -3.7005% |

Relative wealth effects are paired endpoint wealth-multiple ratios, not
additive CAGR contributions. These common windows include the following-close
effect of the entry and end at the release close; the exposure increase and its
turnover cost occur at the next open. Whole-account results include every cost.
Five of seven intervals cost relative wealth; the 2021 benefit was nearly flat.

The complete trace contains six watch episodes, including one instantaneous
zero-entry watch, and seven cap intervals. Caps were signaled on 207 closes,
but changed the no-extra-hold target on only 149; overlap with other protection
explains the difference. Allocation changes rise from 21 to 31 and cumulative
turnover from 14.0733 to 17.6733. All episodes and unchanged windows are retained.

## Chronological evidence

| Period | No-extra-hold return | RW1 return | No-extra-hold maximum DD | RW1 maximum DD |
|---|---:|---:|---:|---:|
| 2018-2020 | +77.7636% | +77.7636% | -23.6481% | -23.6481% |
| 2021-2022 | -0.3954% | -4.2083% | -28.9758% | -27.9483% |
| 2023-2024 | +63.6372% | +48.4295% | -15.4383% | -15.4383% |
| 2025-July2026 | +71.4128% | +71.4128% | -21.5619% | -21.5619% |

2019/2020 recoveries remain unchanged, as the inspected conjunction suggested.
That did not generalize to all constructive recoveries. In 2023 the annual
return falls from 34.1991% to 21.7273%, while the two-year maximum drawdown is
unchanged. In 2022 the annual return falls from -14.3466% to -17.6973%.
The rule adds no protection during 2025's initial decline. It solves neither
the growth cost of prolonged defense nor the first-leg warning problem.

This rejects the specific RW1 mechanism. It does not establish that all
recovery monitoring is ineffective, that Core is optimal, or that an LLM would
improve decisions. No replacement rule or model training was started.

## Qualification and delivery evidence

Successful [run42553094129](https://github.com/flabber1835/stocker/actions/runs/42553094129),
job `128952781308`, source head
`65853da0f5dfffff0b9e1964d86d5d5196ebbddd`, request SHA256
`8508bd846b10a3d64797a0bdc20c00e9669a6d9731625330a2ebdf44ee193b23`.
Verified main `2714afbb25fd169295358e035cefff59db2bf67d` is incorporated.
The workflow completed in about two minutes; after staging, setup 7.08s,
worker 11.31s and reviewer 6.19s, total launcher 24.68s.

Both actual credential-free/network-disabled containers stopped positively,
exit zero without OOM. Independent review checked 6,846 controller decisions,
2,282 watch states, 6,468 complete canonical account records, daily factors/NAV,
103 monthly reports per account, 357 serialized controller continuations,
32 watch-transition restores, every reported block/year/drawdown-duration and
every original defensive/watch/cap episode. Both controls reproduce their prior
complete target hashes and complete account journal commitments; original
baseline account fields also reproduce exactly.

Hosted qualification exercised 248 synthetic calls, seven actual negative
policy mutants, causal prefixes, strict snapshots, constructive/choppy
recoveries and gap timing. The actual recorded-gap Account canary proves a
current-close cut cannot erase an already held overnight loss. The reviewer
independently validated its record and repeated the constructor canaries.

77 targeted DATA/AST/DTO tests passed in 17.79s under an additional
process-global canonical import fence. Both Native-preservation and target-scope
guard bypasses make their corresponding negative checks fail. Three new Python
modules parse; workflow isolation, staged whitespace and 1,461 committed
driver/protocol/workflow byte bindings passed.

Exact pytest arguments, using
`C:/GitHub/stocker/.codex-tmp/bounded-feed-venv/Scripts/python.exe -B`, with
`research/capital_risk` inserted into sys.path and the canonical MetaPathFinder
installed before importing pytest:

```text
-q -p no:cacheprovider --tb=short
--basetemp=C:/GitHub/stocker/.codex-tmp/p00-recovery-watch-tests-3
research/capital_risk/forecast_tests/test_p00_recovery_watch.py
```

Artifact `13646655592`: 2,116,367 bytes, ZIP SHA256
`22bd154c991667832e7ddf26386db8df30234642218ef5bb22e7c4e3472576da`.
Independent local DATA admission authenticated the entire AES-GCM cipher before
parsing, all 23 manifest members, exact request/protocol/runtime identities,
container fences, journals and positive stops. Both previous complete control
records were compared again locally as DATA. No financial runtime or new
financial decision executed locally. A local reader setup error was corrected
before authentication; no hosted run was repeated.

Delivery remains ready PR542 targeting main. No production, PAPER/LIVE or
deployment change was adopted, and no merge occurred. The original campaign
and stopped Control/VOL075 jobs remain stopped; their stop-status file is
unchanged. The inherited factual-suffix workflow separately failed with zero
jobs ([run42553092702](https://github.com/flabber1835/stocker/actions/runs/42553092702));
it did not execute an old backtest and is not a failed RW1 economic review.
