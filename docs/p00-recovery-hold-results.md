# P00: removal of the extra recovery hold

The owner-authorized [single comparison](p00-recovery-hold-experiment.md)
completed on 2026-11-08. Removing only CandidateA's post-Native zero-exposure
recovery hold improved both full-history growth and maximum drawdown on this
inspected P00 history. It also produced deeper temporary drawdowns in the five
affected recovery windows. This is research evidence, not a production policy
adoption or unseen validation.

## Paired result

Same immutable P00 Core, original input epoch, 126 formation observations and
2,156 measured closes, 2018-01-02 through 2026-07-31. Both funded paths begin
at the original $50,000 first measured closing anchor and retain exact
next-open accounting, old exposure overnight and canonical turnover costs.

| Measure | Original Sentinel | No extra recovery hold |
|---|---:|---:|
| CAGR | 19.955089% | 20.550927% |
| Maximum drawdown | -29.329093% | -28.975805% |
| Final funded wealth | $237,993.46 | $248,323.38 |
| Allocation changes | 19 | 21 |
| Cumulative allocation turnover | 14.0732673553 | 14.0732673553 |

Growth improves by 0.595838 percentage points per year; worst drawdown is
0.353288 points shallower; terminal wealth is $10,329.93 higher. The 43 changed
close targets are precisely the five original post-Native holds: 17 become
55% under the unchanged Owned55 cap, and 26 become full exposure. Native's
complete class, severe entry and recovery rules, healthy streaks, minimum
ages and snapshot schema are unchanged. The leadership and Owned55 rules
and every Core observation are unchanged. Formation targets are identical.

The saved Core-only reference remains 21.481763% CAGR / -29.726062% maximum
drawdown. The change recovers about 39% of the original Sentinel CAGR gap;
it does not close that gap or solve late protective signals.

## Yearly returns

These are period returns, not annualized partial-period CAGR. 2026 ends July 31.

| Year | Original Sentinel | No extra recovery hold |
|---|---:|---:|
| 2018 | -10.31% | -10.31% |
| 2019 | 27.30% | 30.67% |
| 2020 | 51.00% | 51.68% |
| 2021 | 16.29% | 16.29% |
| 2022 | -14.77% | -14.35% |
| 2023 | 34.20% | 34.20% |
| 2024 | 21.77% | 21.94% |
| 2025 | 2.72% | 3.28% |
| 2026 Jan-Jul | 65.96% | 65.96% |

## Preserve the episode tradeoff

Each window begins at the original defensive signal close and ends at the
close of its effective full re-entry session. The changed and original paths
use identical endpoints. These local drawdowns do not include losses already
incurred before the initial cut signal.

| Original defensive window | Original return | Changed return | Original local max DD | Changed local max DD |
|---|---:|---:|---:|---:|
| 2018-10-15 to 2019-02-05 | -4.17% | -1.64% | -6.22% | -7.20% |
| 2020-02-27 to 2020-04-29 | -3.84% | -3.40% | -3.84% | -4.50% |
| 2022-06-16 to 2022-08-11 | 0.11% | 0.61% | -0.25% | -3.14% |
| 2024-08-07 to 2024-10-11 | 3.19% | 3.34% | -0.72% | -1.24% |
| 2025-04-07 to 2025-05-15 | 5.56% | 6.14% | 0.00% | -2.87% |

The other three completed original defensive windows and the unfinished
July 2026 window have identical proportional results. Both returns and
drawdowns in every window were independently checked. Earlier re-entry buys
more of both the rebound and subsequent pullbacks; a better full-history
maximum drawdown does not mean every episode is safer.

## Verification and timing

Run [42545391756](https://github.com/flabber1835/stocker/actions/runs/42545391756),
job `128929153784`, experiment head
`7f0587214e902776f9d3cc1dfa1088554bb45838`, completed successfully on its first
generation. The independent reviewer also stopped with exit code zero and no
OOM. No canonical Core transition was executed. All original baseline targets
over formation and measurement, and every original measured funded-account
field, reproduced exactly.

Controller computation took 3.67 seconds and controller plus paired accounts
took 5.11 seconds. Container worker time was 9.16 seconds; independent reviewer
time was 4.17 seconds; original P00 parent authentication/source setup took
9.48 seconds. The paired job driver took 22.91 seconds after frozen-runtime
staging; queueing, capacity preparation, dependency installation, staging and
artifact transfer are additional workflow time.

Both profiles passed all 103 monthly accounting reports and serialized
continuations, independent vector-controller equations, independent rational
account-factor/NAV/metric checks and chained journals. All nine original
defensive-window reports agree with the independent reviewer. The 121 actual
hosted synthetic controller calls verified unchanged Native timing and resets,
immediate extra-hold release, leadership/Owned55 caps and CandidateA cross-policy
snapshot refusal. Local qualification remains the 26 targeted DATA/AST/DTO tests
documented in the experiment protocol.

Independent local DATA admission authenticated artifact `13642433891`, exactly
1,376,593 bytes, SHA256
`9a9f855c289945e4c9a134bdb765d9ecb289322bc33b360e42392e749a8c2856`.
The entire AES-GCM cipher was authenticated before plaintext parsing; all 17
manifest members, source/request/protocol bindings, actual worker/reviewer
container fences and positive stops verified. Every baseline target and account
field was compared again with the original committed P00 journal as DATA. No
local financial runtime was imported or executed.

## Interpretation and next research boundary

The expected modest growth recovery was observed. Full-history drawdown also
improved slightly, while local recovery protection weakened. Keep this
candidate for further Sentinel research, with the original baseline retained
alongside it; do not silently deploy or treat it as a newly certified strategy.
A later parameter grid needs its own fixed protocol, bounded class, comparison
objectives and chronological reporting. No grid was started. The original
twelve-arm campaign and the Control/VOL075 backtests remain stopped.
