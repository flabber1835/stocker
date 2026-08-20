# Simplified Sentinel Concordance LD-RC — authoritative strategy semantics

**Status:** authoritative source-of-truth semantics for implementation; activation remains disabled pending causal/certification gates.

## Correction to the earlier mini-spec

The historical mini-spec at commit `f29f67951b11150e2ef26147652549a0092dad61` is **incomplete**. It retained the three-signal divergence latch but omitted the separate independent recovery gate that was part of the research architecture producing the ~22.6% / ~-21.7% result.

That omission is material. The retained research record at commit `2809eef7948ef1a98452dce677ec3f920405cdbe` explicitly defines the architecture as:

1. native Sentinel risk-off remains authoritative;
2. native Sentinel staged recovery may proceed through 55% and 65%;
3. ordinary restoration to 100% requires independent recent-leadership recovery evidence;
4. a strategy-specific divergence while fully risk-on can latch a tighter 55% cap;
5. the same independent recovery evidence clears both protections.

The simplification pass at commit `b0a700cf82ae58af8e3bbdcc91ff053b0341d9e2` simplified **divergence entry**, not the pre-existing full-risk recovery gate.

`sentinel/controller/ldrc.py` is the executable authority for these semantics. Any prose or future port that disagrees with that module and its tests is not the Simplified LD-RC strategy.

## Corrected parent economics

Historical parity must use the corrected research parent:

- liquidity: `SEP.close * SEP.volume` (equivalently raw close times raw-compatible volume);
- raw marking/execution: `SEP.closeunadj`;
- historical raw-share dividend cash: `ACTIONS.value * SEP.closeunadj / SEP.close`;
- same-session split before dividend;
- hardened fast-crisis damaged-breadth acceleration threshold: 30 percentage points;
- close decision -> next executable open;
- BIL defensive sleeve and retained overlay cost convention in research replay.

The corrected+hardened parent falsifier remains approximately 21.3433% CAGR / -24.7500% max drawdown / 1.1047 daily Sharpe over 2006-07-31..2026-07-31.

## Independent recovery authority

A session is independently healthy only when:

```text
recent_r20 > 0
AND recent_r40 > 0
```

Require seven consecutive sessions, or allow the explicit strong-market escape:

```text
SPY r20 > 0.11
```

The `> 0.11` comparison is strict.

Whenever native Sentinel is below 100%, the full-risk gate is armed. Native Sentinel may continue through 55% and 65%, but a later native 100% target is capped at 65% until independent recovery clears the gate.

Missing recovery evidence fails the session and resets the consecutive counter. A retry of an already-applied session must not age the counter again.

## Simplified three-signal divergence latch

While native Sentinel permits exactly 100%:

```text
WC drawdown <= -0.10
AND recent_r20 <= -0.08
AND SPY r20 >= 0.00
```

The boundaries are inclusive. If true:

```text
divergence_latched = true
full_risk_blocked = true
recovery_streak = 0
divergence ceiling = 0.55
```

The latch persists after the entry conjunction disappears. It clears only under the same independent recovery authority above.

## Composition

The two protections are separate and intentionally have different ceilings:

```text
recovery ceiling   = 0.65 while full_risk_blocked else 1.00
divergence ceiling = 0.55 while divergence_latched else 1.00

final_allocation = min(
    native_allocation,
    recovery_ceiling,
    divergence_ceiling,
)
```

Consequences:

- native 0% always remains 0%;
- native 55% remains 55%;
- native 65% may proceed during ordinary recovery;
- an uncertified native 100% target is held at 65%;
- a divergence-latched native 100% target is held at 55%;
- LD-RC can never increase native Sentinel exposure.

## Durable state

Strategy state version 2 contains:

```text
full_risk_blocked
divergence_latched
recovery_streak
last_session
```

The schema is strict. Unknown/missing fields refuse rather than defaulting to a less-protective state. Session advancement is strictly monotonic to prevent crash/retry double-aging.

## Research lineage and headline falsifier

The complete research architecture plus simplified divergence entry was reported at approximately:

- 20-year CAGR: ~22.62%
- max drawdown: ~-21.70%
- daily Sharpe: ~1.214

These numbers are falsifiers, not optimization targets. If a causal replay after #192/#193 changes them, investigate/report the change rather than tuning thresholds back to the old score.

## Activation boundary

This source can be merged and retained while disabled. It must not become live/paper allocation authority until the remaining point-in-time causal-data work, exact parent/witness/state-tape parity, restart/catch-up integration, strategy identity rotation, and recertification are complete.

The goal of landing this file now is narrower and important: **the strategy definition itself must never again depend on ephemeral scratch code or an incomplete summary.**
