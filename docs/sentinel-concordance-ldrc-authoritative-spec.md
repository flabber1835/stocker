# Simplified Sentinel Concordance LD-RC — recovered authoritative semantics

**Status:** retained strategy source; not live activation authority.
**Recovery date:** 2026-08-19.
**Reason for this document:** the original corrected research harness was ephemeral. The implementation was reconstructed from the original experiment lineage and accepted only after reproducing multiple retained historical fingerprints exactly.

## What was recovered

The prior PR #199 implementation over-formalized recovery as a durable certificate. That is **not** the research strategy.

The recovered architecture is:

1. Native Sentinel risk-off is authoritative.
2. Native Sentinel may recover through 55% and 65% normally.
3. A native transition from 100% to below 100% starts a recovery episode.
4. The independent recent-leadership witness maintains a **live** healthy-session streak every session:

```text
healthy = recent_r20 > 0 AND recent_r40 > 0
streak = streak + 1 if healthy else 0
```

5. When native Sentinel later requests 100%, allow it only if the **current** streak is at least 7 or `SPY r20 > 0.11`. Otherwise hold the previous desired exposure. A strong SPY rebound does not clear the episode early while native Sentinel is still defensive.
6. Separately, while native Sentinel is effectively at 100%, the simplified divergence trigger is:

```text
WC drawdown <= -0.10
AND recent_r20 <= -0.08
AND SPY r20 >= 0.00
```

This latches a 55% ceiling. The latch clears when the same live seven-session recovery condition is satisfied or `SPY r20 > 0.11`. A successful clear is authoritative for that close: divergence entry is not evaluated again until the next decision session. This applies to both persistence and SPY V-rebound clears.
7. Every close-time decision is an intent for the **next executable open**. No same-session application is allowed.

## Recovered recent-leadership witness

The witness is a zero-capital opportunity-set sensor.

For each close `t`:

- Start from the same causally available eligible equity population as Wealth Core.
- Population size: `max(25, ceil(0.10 * eligible_count))`.
- Established leaders: descending raw 6-to-1 momentum `close[t-21] / close[t-126] - 1`.
- Recent leaders: same population size, descending latest 21-session price return `close[t] / close[t-21] - 1`.
- Deterministic tie-break: security identity ascending after score descending.
- Membership selected at close `t` earns the next close-to-close **price** return `t -> t+1`.
- The shadow is arithmetic equal-weight.
- A selected constituent with no valid next-session print keeps its fixed weight and contributes **0%** for that one-session return; it is not dropped and the remainder are not reweighted.
- No ACTIONS dividend cash is added to the shadow.
- `recent_r20` and `recent_r40` are exact trading-session returns of the compounded shadow NAV.

On a genuinely fresh deployment, the existing causal historical feature warmup also advances this zero-capital witness. It does not replay Wealth Core trades or manufacture controller, portfolio, episode, cooldown, pending-order, or ledger history. The first live decision therefore begins with the same bounded 20/40-session witness evidence as an uninterrupted causal replay when sufficient historical sessions exist.

Upstream eligibility must retain corrected Sharadar economics, including liquidity `SEP.close * SEP.volume` and the canonical Wealth Core historical eligibility semantics.

## Exact reconstruction fingerprints

The population construction reproduced both retained overlap observations exactly:

- 2008-12-23: `7 / 101 = 6.9306930693%`
- 2022-01-03: `8 / 96 = 8.3333333333%`

Using the corrected volume + dividend parent, hardened 30pp native Sentinel sensor, BIL defensive sleeve, 10bp one-way allocation-change cost and **close decision -> next-open application**, the recovered chain reproduces:

| Architecture | CAGR | Max DD | Daily Sharpe | Ending multiple |
|---|---:|---:|---:|---:|
| Recovery-only recent-leadership persistence | 22.41726% | -22.70931% | 1.173443 | 57.13324x |
| Full five-condition LD-RC | 22.59459% | -21.69582% | 1.202464 | 58.81154x |
| **Simplified three-signal LD-RC** | **22.6302156%** | **-21.6958215%** | **1.2138139** | **59.15429x** |

These are parity falsifiers, not optimization targets. Future implementations must match the session-by-session witness/state/allocation tape; similar headline CAGR is not sufficient.

## Why the previous PR #199 replay failed

Two reconstruction errors caused the lower ~21.94% result:

1. recovery was modeled as a durable armed/cleared certificate instead of a live current persistence condition evaluated at the 100% re-entry point; and
2. the close-time LD-RC decision was applied to the same session rather than at the next executable open in the validating replay.

The recovered source in `sentinel/controller/ldrc.py` and `sentinel/controller/recent_leadership.py` supersedes those semantics.

## Activation boundary

This recovery fixes source retention. It does **not** remove the remaining point-in-time causality/certification gates in #192/#193, and it does not activate LD-RC in paper/live trading.
