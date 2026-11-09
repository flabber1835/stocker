# P00 Sentinel: results of the fixed 144-profile grid

The owner-authorized [grid](p00-sentinel-grid.md) completed with all 144
configurations and 144 distinct exposure paths independently verified. Core
was unchanged. The grid found small improvements around recovery timing, but
no materially lower-drawdown configuration that retained the controls' growth.
Do not adopt a new production default from this inspected-history search.

## Candidates locked on 2018-2022

Selection used only 2018-01-02 through 2022-12-30. The two primary candidates
were locked before later-period reporting. Protection minimized training
drawdown while retaining at least both controls' training wealth; growth
maximized training wealth within both controls' training drawdown ceilings.
The original-drawdown-budget leader uses the looser original control ceiling.

| Configuration | Training CAGR | Training max DD | Full-history CAGR | Full-history max DD |
|---|---:|---:|---:|---:|
| Original Sentinel | 11.3301% | -29.3291% | 19.9551% | -29.3291% |
| Previous no-extra-hold candidate | 12.1274% | -28.9758% | 20.5509% | -28.9758% |
| Primary protection candidate | 12.2600% | -28.4861% | 20.5373% | -28.4861% |
| Primary growth candidate | 12.2977% | -28.7740% | 20.6233% | -28.7740% |
| Original-drawdown-budget growth leader | 12.7801% | -29.0978% | 20.9165% | -29.0978% |

Full history is 2018-01-02 through 2026-07-31, with 2,156 measured closes,
the original $50,000 closing anchor, all costs and exact next-open accounting.
Both controls exactly reproduced their previously admitted complete account
record commitments and targets, not just their ending statistics.

| Configuration / ID | Extra hold | Fast healthy closes | Slow healthy closes | Owned entry closes | Owned damaged breadth | Owned ceiling |
|---|---|---:|---:|---:|---:|---:|
| Original / `P00_FROZEN_SENTINEL` | on | 3 | 6 | 5 | 0.88 | 0.55 |
| Previous candidate / `P00_NO_EXTRA_RECOVERY_HOLD` | off | 3 | 6 | 5 | 0.88 | 0.55 |
| Protection / `GRID_17ccbc7fcaf9b88c2aec` | on | 2 | 3 | 5 | 0.88 | 0.55 |
| Growth / `GRID_c2b81411bb38223e5220` | off | 2 | 6 | 5 | 0.88 | 0.55 |
| Original-budget leader / `GRID_5a4ee7ac74bdaa893bc2` | on | 2 | 3 | 5 | 0.88 | 0.25 |

The primary growth candidate adds only 0.0723 percentage points of full-history
CAGR and reduces worst drawdown by 0.2018 points versus the previous simple
hold-removal candidate. The protection candidate reduces drawdown by 0.4897
points while giving up 0.0136 points of CAGR. Both primary candidates retain
the original owned-entry confirmation, damage threshold and exposure ceiling.

The original-budget leader offers more growth at slightly deeper drawdown than
the no-extra-hold control. It was selected under a different, explicitly looser
training risk constraint; it is not the primary growth candidate.

## Later-period evidence

These are block returns and local maximum drawdowns, not annualized returns.
The periods were already inspected before this search; they are chronological
historical checks, not unseen validation.

| Configuration | 2023-2024 return | 2023-2024 max DD | 2025-Jul 2026 return | 2025-Jul 2026 max DD |
|---|---:|---:|---:|---:|
| Original | 63.4100% | -15.5557% | 70.4763% | -21.5619% |
| Previous no-extra-hold candidate | 63.6372% | -15.4383% | 71.4128% | -21.5619% |
| Primary protection candidate | 63.4100% | -15.5557% | 70.4763% | -21.5619% |
| Primary growth candidate | 65.2290% | -15.3236% | 69.3495% | -21.5619% |
| Original-budget growth leader | 64.0424% | -15.2289% | 70.4763% | -21.5619% |

The primary growth candidate improves the 2023-2024 block but underperforms the
previous simple candidate in the latest block. Its 2025 return is 2.0404%,
versus 3.2836% for the previous candidate; 2026 Jan-Jul is identical at 65.9632%.
The primary protection candidate also gives up the previous candidate's later
growth improvements. None of these locked candidates improves the latest
block's 21.56% worst drawdown.

The grid produced no candidate at either the 50% or 75% training drawdown
budget: targets were 14.6645% and 21.9968% magnitude. The shallowest training
drawdown anywhere in the class was 23.8011%, without imposing a growth floor.
The shallowest full-history drawdown was 26.2617%, paired with 17.4708% CAGR
(`GRID_99ac73b36fd505da50c3`); that is descriptive class coverage, not a candidate
reselected from later-period outcomes. The complete class spans 10.8201%-20.9165%
full-history CAGR and 26.2617%-33.1101% drawdown magnitude.

## Protection tradeoffs on the declared frontier

The primary protection objective required preserving the better no-extra-hold
control's training wealth. That is a stricter objective than preserving original
Sentinel growth. Do not interpret the primary picks or the shallowest-drawdown
row above as the only available tradeoffs. Two profiles already on the
predeclared training frontier deserve explicit reporting:

| Profile | Full CAGR | Full maximum drawdown | Peak to recovery sessions |
|---|---:|---:|---:|
| Original Sentinel | 19.9551% | -29.3291% | 642 |
| GRID_8c4c9f4b11e7404f1ba1 | 20.0093% | -27.0442% | 641 |
| GRID_50fa11b9e59806cedd0b | 19.8301% | -26.3807% | 716 |

This is a correction to the emphasis of the earlier summary, not a new
later-period winner selection. The first profile preserves original growth
with a 2.2849-point drawdown reduction; the second trades modest growth for
more protection but prolongs recovery. "Nothing improved" and "protection
requires growth to fall to 17.47%" both overstate the negative result.
The separately authorized [RW1 experiment](p00-recovery-watch-results.md) is
dominated by the first of these prior candidates and was rejected.

## Matched parameter comparisons

Each comparison changes one axis while holding the other five axes fixed.
The counts below are overlapping configurations on one history, not independent
samples or statistical significance. Drawdown reduction is positive when the
alternative's full-history maximum drawdown is shallower.

| One changed axis | Matched pairs | Median CAGR change, pp | Median DD reduction, pp | Both improved |
|---|---:|---:|---:|---:|
| Extra hold on to off | 72 | +0.3373 | +0.3463 | 56/72 |
| Fast healthy closes 3 to 2 | 72 | +0.1612 | +0.4162 | 62/72 |
| Slow healthy closes 6 to 3 | 72 | +0.1884 | approximately 0 | 0/72 |
| Owned entry confirmation 5 to 1 | 48 | -3.5121 | +1.0247 | 0/48 |
| Owned entry confirmation 5 to 3 | 48 | -0.1052 | +0.2019 | 0/48 |
| Owned entry damage 0.88 to 0.75 | 72 | -1.2635 | +1.2974 | 0/72 |
| Owned ceiling 0.55 to 0.25 | 48 | -0.3752 | -2.0912 | 0/48 |
| Owned ceiling 0.55 to 0.75 | 48 | +0.1126 | +0.2254 | 16/48 |

Earlier owned entry reduced full-history CAGR in all 48 comparisons at one
confirmation and all 48 at three confirmations. Lowering its damage threshold
reduced CAGR in all 72 comparisons. Lowering its exposure ceiling to 25%
deepened full-history maximum drawdown in all 48 comparisons, even though it
reduced exposure while impaired. Missed gains and subsequent recovery matter
to the path of future drawdowns.

Faster Native recovery helped many full-history comparisons, but the latest
block supplied no growth improvements from reducing fast confirmation 3 to 2.
Slow confirmation 6 to 3 improved CAGR in 36 configurations and worsened it
in 36, without materially changing full-history maximum drawdown. That
interaction argues against assuming every shorter wait improves growth.

## What was verified

Successful [run42548611766](https://github.com/flabber1835/stocker/actions/runs/42548611766),
job `128938946159`, experiment head
`dc309b8074e6e164798f96d333a57f37e8f0c429`. The full workflow took about four
minutes. Driver time after frozen-runtime staging was 197.73 seconds: parent
authentication/source setup 6.31s, worker 147.94s, reviewer 42.91s. Both worker
and reviewer stopped positively, exit zero, without OOM. The fixed class was
not expanded or retuned after inspecting performance.

The worker/reviewer checked 328,608 complete controller decisions against
independent vector equations, 3,680 dated canonical account factors, 310,320
value steps, and 53,900 direct canonical account records on 25 fully recorded
paths. All 144 full-history, chronological block and yearly metrics, training
locks, exact training Pareto frontier, monthly journal prefixes and aligned
original defensive-window reports passed independent review. The 3,456 actual
hosted synthetic calls verified parameterized counters and snapshot bounds,
retained minimum ages and leadership cap, owned entry/exposure/recovery,
same-profile restore and cross-profile snapshot refusal.

Local qualification: 40 targeted DATA/AST/DTO tests passed in 4.27s; source-bound
request/import probe; six Python AST parses; workflow isolation; staged
whitespace; 1,457 committed driver/protocol/workflow byte bindings. Eleven reused
controller/account/factor/value/reviewer function ASTs are unchanged.

Exact targeted pytest command and its import fence are documented in the
[grid protocol](p00-sentinel-grid.md#local-qualification). No local canonical
financial runtime was imported or executed. There were zero new Core
transitions; the original stopped-run status file is unchanged.

Artifact `13643514985`: 17,601,639 bytes, SHA256
`27a625232e9aaa5b7eb9d5942bdcae23797a300c4e71135d94f6bd1e5f51b710`.
Independent local DATA admission authenticated the entire AES-GCM cipher
before parsing and all 46 manifest members, exact request/registry/protocol
bindings, archived container fences, journal commitments and positive stops.
The first local reader attempt correctly refused its copied, incorrect expected
worker filename; its authenticated output was preserved, the reader expectation
was corrected to the actual grid entrypoint, and complete admission then passed.
No hosted calculation was rerun.

## Recommendation

Keep Core fixed and retain the simple no-extra-hold version as a research
reference alongside the original controller. The new candidates describe a
small historical frontier, not a compelling new default. Avoid another sweep
of these same settings. The next useful diagnostic is to identify why the
remaining large drawdown survives the bounded class, especially the sustained
2021-2022 decline and the loss already incurred before protection in 2025.
Changing recovery speed alone did not solve Sentinel's drawdown objective.
No production policy was adopted; the original campaign and Control/VOL075
backtests remain stopped.
