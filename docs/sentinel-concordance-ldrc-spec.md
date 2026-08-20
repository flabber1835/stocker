# Sentinel Concordance LD-RC — simplified reference specification

**Date:** 2026-08-19  
**Status:** frozen research specification; not yet production-certified  
**Purpose:** preserve the exact simplified LD-RC architecture so it can be independently reimplemented, tested, and promoted without relying on ephemeral research code.

## One-sentence explanation

Sentinel continues to handle broad-market crises normally. LD-RC adds one extra protection state for the case where **Wealth Core is hurting, independent stock leadership is also weak, but SPY is not weak**; in that case exposure is reduced modestly and remains reduced until independent leadership confirms recovery.

## Design principles

1. **Existing Sentinel systemic risk-off remains authoritative.** LD-RC must never delay, veto, or weaken an ordinary Sentinel reduction in risk.
2. **LD-RC is a sparse overlay, not a second alpha engine.** It changes only the scalar exposure applied to the Wealth Core book.
3. **The controlled book cannot certify its own recovery.** Once LD protection is latched, an independent recent-leadership witness must recover before full risk is restored, except for an unmistakably strong SPY V-rebound.
4. **Signals are close-time observations; allocation changes take effect at the next executable open.** No same-close execution is permitted.
5. **Do not optimize these thresholds further.** They are simple rounded research-reference values selected after a simplification-by-subtraction pass, not historical-score maximizers.

## Inputs

For each decision session `t`:

- `native_allocation_t`: Sentinel's ordinary desired stock allocation after its existing fast/slow crisis logic and staged recovery. Typical values are 0.00, 0.55, 0.65, or 1.00.
- `wc_nav_t`: Wealth Core shadow NAV at the close of `t`.
- `wc_peak_nav_t`: running peak of Wealth Core shadow NAV through `t`.
- `recent_leadership_nav_t`: NAV of the independent recent-leadership shadow through `t`.
- `spy_close_t`: SPY close/total-return observation used by the existing Sentinel research tape through `t`.
- persistent LD state: `ld_latched` and `recovery_streak`.

Derived observations:

```text
wc_drawdown = wc_nav_t / wc_peak_nav_t - 1
recent_r20  = recent_leadership_nav_t / recent_leadership_nav_(t-20) - 1
recent_r40  = recent_leadership_nav_t / recent_leadership_nav_(t-40) - 1
spy_r20     = spy_close_t / spy_close_(t-20) - 1
```

All horizons are trading/session horizons and must use only observations available by the close of the decision session.

## Independent recent-leadership shadow

The witness must remain independent from the controlled Wealth Core holdings.

Research reconstruction definition:

1. Start from the same causally available eligible equity population used for the session.
2. Rank securities by **latest 21-session return**.
3. Select a recent-leadership set sized to the corresponding leadership population.
4. Form an equal-weight shadow of that recent-leadership set and advance its NAV causally through time.
5. Compute `recent_r20` and `recent_r40` from that shadow NAV.

The important property is independence: the witness is an opportunity-set thermometer, not a statistic of the positions whose exposure it controls.

## Divergence-entry rule

The preferred simplified LD trigger has exactly three conceptual observations:

```text
Wealth Core is materially down
AND independent recent leadership is materially weak
AND SPY is not weak
```

Frozen representative numerical form:

```text
wc_drawdown <= -0.10
AND recent_r20 <= -0.08
AND spy_r20 >= 0.00
```

The rule is evaluated only as an additional protection while Sentinel would otherwise permit full risk.

If the conjunction becomes true while `native_allocation_t == 1.00`:

```text
ld_latched = True
recovery_streak = 0
LD cap = 0.55
```

The LD layer must never increase risk. Final desired allocation is always bounded by native Sentinel:

```text
final_allocation_t = min(native_allocation_t, ld_cap_if_latched_else_1.00)
```

Thus, if ordinary Sentinel wants 0% during a market crisis, the final allocation is 0%, not 55%.

## Recovery / unlatch rule

While `ld_latched` is true, ordinary disappearance of the entry trigger does **not** clear the state. This persistence is load-bearing: the divergence cap by itself performed worse than corrected Sentinel in adversarial testing.

Independent leadership recovery for a session is:

```text
recent_r20 > 0.00
AND recent_r40 > 0.00
```

Require this for **7 consecutive sessions**:

```text
if recent_r20 > 0 and recent_r40 > 0:
    recovery_streak += 1
else:
    recovery_streak = 0

if recovery_streak >= 7:
    ld_latched = False
    recovery_streak = 0
```

A strong V-rebound escape is retained so the independent witness cannot keep the strategy artificially defensive during an unmistakable broad-market snapback:

```text
spy_r20 > 0.11
```

If this condition is true while latched, the LD latch may clear immediately. Native Sentinel still owns the final allocation; clearing LD does not force 100% exposure if native Sentinel is still below 100%.

## State machine

Conceptually LD-RC has only two overlay states:

```text
NORMAL
  |
  | native Sentinel permits 100%
  | AND WC DD <= -10%
  | AND recent leadership r20 <= -8%
  | AND SPY r20 >= 0%
  v
LD_LATCHED  -- cap at 55%
  |
  | recent leadership r20 > 0 AND r40 > 0
  | for 7 consecutive sessions
  | OR SPY r20 > 11%
  v
NORMAL
```

At every point, ordinary Sentinel can independently demand a lower allocation and wins through `min(native, ld_cap)`.

## Reference Python

This is intentionally small and explicit. It is reference/sample code for the architecture, not yet the production implementation.

```python
from dataclasses import dataclass


@dataclass
class LDRCState:
    latched: bool = False
    recovery_streak: int = 0


@dataclass(frozen=True)
class LDRCConfig:
    wc_drawdown_trigger: float = -0.10
    recent_r20_trigger: float = -0.08
    spy_r20_floor: float = 0.00
    cap: float = 0.55
    recovery_sessions: int = 7
    spy_v_rebound: float = 0.11


def ldrc_step(
    *,
    native_allocation: float,
    wc_drawdown: float | None,
    recent_r20: float | None,
    recent_r40: float | None,
    spy_r20: float | None,
    state: LDRCState,
    cfg: LDRCConfig = LDRCConfig(),
) -> tuple[LDRCState, float]:
    """Return next LD-RC state and close-time desired allocation.

    The returned allocation is an intent for the next executable open.
    Native Sentinel risk-off is always authoritative because the overlay
    can only reduce allocation through min(native_allocation, cap).
    """

    # First, a latched state may clear only from independent recovery evidence
    # or an unmistakably strong SPY rebound.
    if state.latched:
        independent_recovery = (
            recent_r20 is not None
            and recent_r40 is not None
            and recent_r20 > 0.0
            and recent_r40 > 0.0
        )
        streak = state.recovery_streak + 1 if independent_recovery else 0

        v_rebound = spy_r20 is not None and spy_r20 > cfg.spy_v_rebound

        if streak >= cfg.recovery_sessions or v_rebound:
            next_state = LDRCState(latched=False, recovery_streak=0)
        else:
            next_state = LDRCState(latched=True, recovery_streak=streak)

    else:
        # LD entry is relevant only when ordinary Sentinel permits full risk.
        divergence = (
            native_allocation >= 1.0
            and wc_drawdown is not None
            and recent_r20 is not None
            and spy_r20 is not None
            and wc_drawdown <= cfg.wc_drawdown_trigger
            and recent_r20 <= cfg.recent_r20_trigger
            and spy_r20 >= cfg.spy_r20_floor
        )
        next_state = LDRCState(latched=divergence, recovery_streak=0)

    ld_ceiling = cfg.cap if next_state.latched else 1.0
    desired = min(float(native_allocation), ld_ceiling)
    return next_state, desired
```

## Timing semantics

For session `t`:

```text
market closes at t
    -> update Wealth Core shadow NAV and peak using data through t
    -> update independent recent-leadership shadow using data through t
    -> compute r20/r40/SPY observations through t
    -> run native Sentinel controller
    -> run LD-RC state transition
    -> persist state and desired allocation
next executable market open
    -> apply resulting allocation change
```

No value from `t+1` may affect the decision made after close `t`.

## Why the latch is essential

Adversarial testing showed that a divergence cap without the independent recovery latch is worse than corrected Sentinel:

- 65% cap alone: about **21.27% CAGR / -25.66% MDD**
- 55% cap alone: about **21.25% CAGR / -25.93% MDD**

The useful hypothesis is therefore not "sell when this conjunction fires." It is:

> detect rare strategy/broad-market divergence, reduce risk modestly, and require independent evidence before restoring full risk.

## Why three entry signals are the complexity floor

A two-signal form using only weak leadership + healthy SPY fired too often and reduced long-run CAGR to about **21.58%**. One direct observation that Wealth Core itself is actually under stress is necessary.

The original five-condition entry was more complicated than necessary. The simplification pass showed that meaningful economics survive with only:

1. Wealth Core drawdown;
2. independent leadership weakness;
3. SPY contrast.

Do not add damaged breadth, another factor model, a voting ensemble, ML regime classification, or position-level exceptions unless new out-of-sample evidence establishes a genuinely new failure mode.

## Research evidence for this simplified form

Using the fully corrected Sharadar volume + dividend research tape and hardened Sentinel fast trigger, the representative simplified three-signal LD-RC produced approximately:

- 20-year CAGR: **22.62%**
- max drawdown: **-21.70%**
- daily Sharpe: **~1.214**

Corrected non-Concordance Sentinel control:

- CAGR: **21.3433%**
- max drawdown: **-24.7500%**
- daily Sharpe: **~1.105**

A 270-case local neighborhood around the simplified architecture produced 202 cases (74.8%) that beat corrected Sentinel on both CAGR and MDD. The exact numerical thresholds are therefore not being justified as an isolated historical optimum.

## Production promotion constraints

This document freezes the research architecture, not a production claim. Before promotion:

- independently reimplement this spec from causal raw inputs;
- prove exact parity against a retained reference tape;
- run production-code restart/latch/next-open/missing-data adversarial tests;
- prove LD-RC cannot delay native Sentinel risk-off;
- complete the remaining causal-data review/reconstruction relevant to the historical corpus;
- accumulate genuinely unseen forward shadow sessions.

If production code ever disagrees with this specification, the disagreement must be explicit, reviewed, and versioned. Do not silently "improve" the rule.

## Related records

- `docs/sentinel-concordance-post-dividend-research-v2.md`
- `docs/sentinel-concordance-adversarial-holdout-validation.md`
- `docs/sentinel-concordance-simplification-pass.md`
- GitHub issue #189: Sentinel Concordance post-dividend research findings
