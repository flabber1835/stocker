# Wealth Core V1 — $100k cash-buffer sweep insights

## Authority

- Branch: `research/wealth-core-v1-buffer-sweep-v1`
- Trigger head: `9eddb48871b0681b79a8b9eff7f725fcd05454b0`
- Workflow run: `34291013480`
- Base evidence head: `38eb1a0dd3ac9a37c4466198c420bd00747e6a13`
- Canonical PIT dataset SHA-256: `5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`
- 0 bp reproduced the frozen V1 daily and summary hashes exactly.
- 10 bp reproduced the prior primary 10 bp performance and execution counts.
- Dividend lag remained one session in every arm.
- Every buy quantity was an integer, no fractional-share buys occurred, no reserve violations occurred, and minimum cash stayed non-negative.

## Direct answers

**Is 10 bp enough?** No. It still has 1 planned entry fully blocked at the next open.

**What remains unfunded at 10 bp?** There are 1 complete next-open failures and 19 clipped fills. Of 20 next-open shortfall events, 18 would still have clipped using the close-time uncommitted cash at the next-open price; 3 involved a positive gap greater than 2.5%.

**At what buffer does next-open execution failure disappear?** 0 bp.

**At what buffer does gap clipping substantially saturate?** 5 bp under the preregistered count-based saturation rule. The exact marginal changes are preserved in `comparison.csv` and `SWEEP_RESULT.json`.

**Does the 10 bp CAGR improvement persist monotonically?** The six-arm CAGR curve is non-monotonic. Performance is treated as path-dependent and is not the buffer-selection criterion.

**Is there a mechanically sensible execution buffer independent of historical return optimization?** 5 bp is the smallest tested level satisfying both the zero-block and gap-saturation criteria; this is an execution-mechanics result, not a return-optimization recommendation.

## Sweep table

| Buffer | CAGR | Max DD | Sharpe | End equity | Entries | q=0 close skips | Open blocks | Gap clips | <1% entries | One-share |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| 0 bp | 14.546038% | -49.011422% | 0.764994 | $1,397,317.86 | 523 | 632 | 0 | 27 | 40 | 28 |
| 5 bp | 14.587081% | -48.446695% | 0.783190 | $1,407,365.49 | 495 | 745 | 5 | 15 | 23 | 17 |
| 10 bp | 15.488288% | -49.042739% | 0.805082 | $1,646,091.83 | 519 | 1004 | 1 | 19 | 33 | 23 |
| 15 bp | 15.133040% | -48.906095% | 0.805463 | $1,547,726.18 | 502 | 2338 | 1 | 21 | 33 | 22 |
| 20 bp | 14.798918% | -49.066841% | 0.780282 | $1,460,326.63 | 512 | 1048 | 2 | 21 | 22 | 15 |
| 25 bp | 15.218146% | -46.178206% | 0.808817 | $1,570,910.83 | 509 | 1209 | 3 | 26 | 29 | 18 |

## Close-time opportunity loss

The q=0 count is separated into actual uncommitted-cash scarcity and whole-share target granularity. This prevents high share prices relative to the 4% target from being mislabeled as cash scarcity.

| Buffer | All q=0 skips | Cash-scarcity q=0 | Target-granularity q=0 | Marginal all-q=0 vs prior +5bp |
|---:|---:|---:|---:|---:|
| 0 bp | 632 | 632 | 0 |  |
| 5 bp | 745 | 745 | 0 | 113 |
| 10 bp | 1004 | 1004 | 0 | 259 |
| 15 bp | 2338 | 2338 | 0 | 1334 |
| 20 bp | 1048 | 1048 | 0 | -1290 |
| 25 bp | 1209 | 1209 | 0 | 161 |

## Overnight-gap attribution

For every clipped or fully blocked next-open order, `gap-clipping-events.csv` records the close plan, next-open price, reserve, actual cash, uncommitted cash, quantities, notionals, and whether the close-to-open price change alone would have caused the shortfall using the close-time uncommitted cash.

| Buffer | Open shortfall events | Gap-alone sufficient | Positive-gap events | Gap >2.5% |
|---:|---:|---:|---:|---:|
| 0 bp | 27 | 27 | 27 | 3 |
| 5 bp | 20 | 15 | 20 | 2 |
| 10 bp | 20 | 18 | 20 | 3 |
| 15 bp | 22 | 20 | 22 | 4 |
| 20 bp | 23 | 20 | 23 | 4 |
| 25 bp | 29 | 23 | 28 | 3 |

## Path dependence

Each nonzero arm is a self-financing counterfactual. Buffer changes can alter admissions, slot occupancy, later exits, and the full holding path. The path-divergence fields in `comparison.csv` and `SWEEP_RESULT.json` quantify the first divergence date, differing buy decisions, entry dates, admissions, exits, final holdings, and cumulative days with different holdings.

## Research conclusion

The execution conclusion is based on next-open failures, clipped fills, reserve integrity, and the close-time q=0 cost curve. CAGR is reported separately as a path outcome. All six arms are retained regardless of performance.

**Certification status:** PASS for a follow-up production-design discussion. This does not authorize a production change.
