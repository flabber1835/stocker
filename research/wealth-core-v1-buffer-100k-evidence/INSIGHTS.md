# Wealth Core V1 — $100k integer-share 10 bp cash-buffer evidence

## Purpose

This evidence bundle records the research sequence that started with the $100k Wealth Core V1 micro-position diagnosis and led to the 10 basis-point NAV cash-buffer replay.

Economic scope is **Wealth Core V1 only**. Sentinel metrics were not used. Fractional shares were not used. Stock-selection, ranking, exits, execution-cost assumptions, PIT inputs, security-type overlays, and one-session dividend timing remained frozen except for the explicitly tested cash-reserve rule.

Measurement window: **2006-07-31 through 2026-07-31**, 5,032 sessions. Initial capital: **$100,000**.

Canonical PIT dataset SHA-256:
`5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`

## Baseline authority

The exact $100k V1 authority is:

- run: `34267327656`
- artifact: `10073578819`
- source SHA-256: `32cd228010e09b5be42271cd6d0c38831fe7fbc74e725f592949146c48104e0f`
- daily SHA-256: `8a2e4f948720674a56737ee6291df0aff12e02a74d74b1ec5f0c75f9929adee6`
- summary SHA-256: `929ed3baacd1bb66e8174d7a6822e362e5c90da75355177d33bab3ac9f201878`

Baseline $100k V1 metrics:

| Metric | V1 |
|---|---:|
| CAGR | 14.546038% |
| Max drawdown | -49.011422% |
| Sharpe, daily 252 | 0.764994 |
| Ending equity | $1,397,317.86 |
| Entries | 523 |
| Gap-clipped entries | 27 |
| Cash-limited close decisions | 119 |
| Entries below 1% of intended capital | 40 |
| One-share entries | 28 |
| q=0 candidate skips | 632 |

## Preceding no-micro exact-path diagnostic

Run `34272674885`, artifact `10076643420`, tested deletion of sub-1% fills while preserving the exact V1 decision path.

The shadow return path was almost economically identical to V1:

- V1 CAGR: **14.546038%**
- exact-path no-micro shadow CAGR: **14.545072%**
- delta: **-0.0009668 percentage points**, approximately **-0.0967 bp/year**
- ending-equity delta: **-$235.87** over 20 years
- 40 baseline micro entries were virtualized
- omitted gross capital across those entries: **$1,991.08**

The diagnostic was formally invalid as an executable portfolio because the clean ledger was not self-financing. It encountered seven affordability breaches. The later V1 order quantities were still determined from the original V1 cash ledger, which retained proceeds from micro holdings that had been removed from the clean ledger.

### Seven financing breach events

| Date | Cash shortfall |
|---|---:|
| 2015-01-22 | $4.01 |
| 2020-02-20 | $1.95 |
| 2021-04-09 | $0.82 |
| 2021-04-29 | $60.55 |
| 2021-05-26 | $8.76 |
| 2022-02-23 | $34.86 |
| 2025-12-16 | $7.38 |

Event-level shortfall statistics:

- average: **$16.91**
- median: **$7.38**
- maximum: **$60.55**
- sum of the seven event deficits: **$118.34**

The sum is descriptive only; it is not a required-capital measure because deficits occur at different times.

## 10 bp integer-share buffer test

Primary run: **`34283531740`**

Branch head used by the run: `32b16cf9addd7fe8122b02d06c4d3643c86a74a9`

Artifact: **`10079799925`**

Artifact SHA-256: `79de96a433acf364488b79badbf2b46fa9e2a8fb90416c8c9b85af11bcfd4aac`

Generated buffered source SHA-256:
`44a9914be859eb7f76ca747aaa66a41e19a557a2095da0a707ea99575898c4e0`

Status: **PASS**.

The rule reserves **0.10% of current NAV** at both sizing boundaries:

1. At the close, the candidate order is sized only from cash above `0.001 * close_equity`.
2. At the next open, affordability is recalculated using cash above `0.001 * open_equity`.
3. Share quantity remains an integer.
4. A next-open gap can reduce the order or block it completely, but the reserve itself cannot be spent by the buy.

The generated replay recorded a minimum post-buy cash excess over the required reserve of **$0.01266**, so the reserve was maintained throughout executed buys.

### Primary result

| Metric | V1 baseline | 10 bp buffer | Delta |
|---|---:|---:|---:|
| CAGR | 14.546038% | **15.488288%** | **+0.942249 pp / +94.225 bp/yr** |
| Max drawdown | -49.011422% | -49.042739% | -0.031317 pp |
| Sharpe, daily 252 | 0.764994 | **0.805082** | +0.040089 |
| Ending equity | $1,397,317.86 | **$1,646,091.83** | **+$248,773.97** |

Buffered ending equity is **17.804% higher** than V1 ending equity over this path.

### Entry behavior

| Telemetry | V1 baseline | 10 bp buffer |
|---|---:|---:|
| Entries | 523 | 519 |
| Gap-clipped entries | 27 | 19 |
| Entries below 1% | 40 | 33 |
| One-share entries | 28 | 23 |
| Cash-limited close decisions | 119 | 124 |
| q=0 candidate skips | 632 | 1,004 |
| Average entry fraction | 84.953% | 84.535% |
| Minimum entry fraction | 0.040253% | 0.018563% |

Additional buffered telemetry:

- planned entries completely blocked at the open by the reserve/affordability check: **1**
- entries below 5% of intended capital: **50**
- entries below 10%: **53**
- entries below 25%: **60**
- entries below 50%: **71**
- entries below 99%: **231**
- maximum entry fraction: **122.333%**
- fractional-share buys: **false**
- all recorded buy quantities are integers: **true**

## Interpretation

### Overnight gaps are a real driver, but not the only driver

The V1 execution sequence determines a candidate and whole-share quantity at the close, then executes at the next session's open subject to available cash. A positive close-to-open gap can therefore make the planned share count unaffordable and clip the fill. V1 recorded 27 such gap-clipped fills.

The micro-position phenomenon is broader than overnight gaps. V1 also recorded 119 decisions already constrained by free cash at the close. The 40 sub-1% entries therefore cannot all be attributed to next-open gaps.

The 10 bp reserve gives execution explicit room for close-to-open price uncertainty. On a $100,000 account the initial reserve is $100. Relative to a normal 4% intended new position ($4,000), that is approximately 2.5% of the intended position value. The reserve scales with NAV.

### The buffer improved micro/gap behavior, but did not eliminate it

Sub-1% entries fell from 40 to 33, gap-clipped entries fell from 27 to 19, and one-share entries fell from 28 to 23. Micro positions still exist because the reserve does not create additional investable cash; it deliberately withholds some cash and the strategy can still reach periods with limited uncommitted capital.

### The large CAGR improvement is path-dependent and requires attribution

The 10 bp rule changed actual admissions and therefore changed the future portfolio path. It produced 1,004 q=0 candidate skips versus 632 in V1, four fewer completed entries, and one next-open entry that was fully blocked. Those differences can change which securities occupy slots and which future candidates are admitted.

For that reason, the +94.225 bp/year CAGR result must **not** be interpreted as the mechanical return on holding 10 bp of extra cash. The reserve itself is too small to explain that magnitude directly. The result is evidence that the reserve changes the sequence of holdings in a favorable way on this historical path. Attribution is required before any production conclusion.

This run is a valid self-financing counterfactual under its stated rule. It is not exact-path equivalent to V1 and does not establish that a 10 bp reserve is universally superior.

## Transaction ledger

The primary artifact contains `transactions.csv` with exactly these columns:

- `Transaction date`
- `Buy or sell`
- `Ticker`
- `Ticker name`
- `Amount of shares`

Ledger counts:

- rows: **961**
- buys: **519**
- sells: **442**

`Ticker name` is blank because the replay path carries ticker identity but not company-name text. The raw ticker and share quantities are preserved exactly. The ledger SHA-256 is:

`3cffc04199190c1b0a4e6c90db4396dd347de0173b33dbec4e78fe84357dd687`

## Evidence handling

The capture workflow preserves the original Actions ZIP files as raw immutable evidence and also expands them into this research directory. `SHA256SUMS.txt` is generated over the captured evidence files.

The primary artifact contains:

- `RESULT.json`
- `buffer-daily.csv`
- `buffer-generated.py`
- `buffer-summary.json`
- `transactions.csv`
- Python compiled bytecode generated by the runner
- `buffer-100k-fast.log`
- `package-integrity.json`
- `final-corpus-validation.json`

The earlier no-micro artifact is also captured because its seven affordability failures are the factual basis for the buffer hypothesis.

## Cross-check status

A redundant combined baseline+buffer run, `34282958960`, was still in progress when this memo was authored. It is supporting evidence only and is not required for the primary PASS above. Do not label the result independently reproduced until that run finishes successfully and matches the primary output.

## Research conclusion

The evidence supports three separate statements:

1. **Micro positions contributed essentially no return on the frozen exact V1 path**, but simply deleting them broke self-financing because their cash flows had financed later exact-path purchases.
2. **Close-to-open gaps are one important source of tiny fills**, while close-time cash scarcity is another.
3. **A 10 bp NAV reserve with integer shares is self-financing, reduces micro and gap-clipped fills, and materially changed the historical holding path.** The resulting 15.488% CAGR is interesting but requires path attribution before any production decision.
