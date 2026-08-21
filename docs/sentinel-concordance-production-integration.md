# Sentinel Concordance production integration

Status: implementation design; paper/live activation remains prohibited until the gates below pass.

## Authority

The strategy source is `docs/sentinel-concordance-ldrc-authoritative-spec.md`
from PR #199. Where issue #194 or earlier prose differs from that recovered
source, PR #199 wins. The recovered implementation is not permission to tune
thresholds.

## Composition

```text
canonical Sharadar publication
  +-> Wealth Core shadow -----------------------------+
  +-> Wealth Core eligible-candidate audit seam       |
  |       +-> recent-leadership zero-capital witness  |
  +-> canonical SPY sensor                            |
                                                       v
                              hardened native Sentinel parent (30pp)
                                                       |
                                                native allocation
                                                       |
                                  Simplified Concordance LD-RC overlay
                                                       |
                                                 final allocation
                                                       |
                                      existing projection / execution
```

Wealth Core remains the only security-selection engine. The witness receives
zero capital and has no broker path.

## Native parent

The Concordance research fingerprint was measured on the hardened 30 percentage
point fast damaged-breadth acceleration threshold. Frozen Sentinel 1.1 retains
its 40pp threshold and its existing digest unchanged. Concordance derives a new,
versioned controller configuration from the verified Sentinel 1.1 source,
overrides only `fast_entry.min_damaged_breadth_delta5` to `0.30`, and computes a
new digest from the source digest plus that explicit override.

An old Sentinel 1.1 certificate can therefore never authorize Concordance.

## Wealth Core audit seam

`LiveSessionPlan` exposes three **ephemeral, non-serialized** facts for the
witness:

- eligible candidate rows carrying canonical raw 6-to-1 momentum and 21-session return;
- the exact eligible-population count emitted by Wealth Core;
- current split-adjusted, dividend-unadjusted signal closes from the same Feed.

They are deliberately omitted from `LiveSessionPlan.to_dict()`, decision hashes,
and durable Wealth Core state. This prevents a recurrence of the historical
candidate-retention memory blow-up and prevents the sensor from changing Wealth
Core economics merely by observing them.

The signal close, not raw close, is used for witness close-to-close price
returns. This makes splits economically neutral while still excluding dividends.

## Witness durable state

The bounded restart image stores only:

- prior recent-leadership membership;
- the split-adjusted signal close at which each prior member was selected;
- the last 41 witness NAVs and corresponding sessions;
- the last processed session.

At close `t` the order is load-bearing:

1. prior membership earns `t-1 -> t` close-to-close price return;
2. missing `t` print contributes exactly 0% at its fixed weight;
3. witness NAV is advanced and r20/r40 are computed;
4. the current eligible population is ranked;
5. current recent membership is stored for `t -> t+1`.

Fresh activation reuses the feature-only historical warmup stream to perform
those five witness steps causally. Only the zero-capital witness state is
advanced. Wealth Core episodes, peaks, ages, cooldowns, pending actions,
controller state, LD-RC state and the ledger remain fresh. Session-effective
metadata is required for every historical witness close; a current snapshot may
not be projected backward merely to make the witness ready.

A duplicate/out-of-order session refuses. Eligible-count disagreement between
Wealth Core and the audit rows refuses instead of silently composing different
universes.

## Production state

The Sentinel production envelope is versioned forward to v4. Existing
non-Concordance v2/v3 state migrates with `recent_leadership=null` and
`ldrc=null`; behavior is unchanged. A strategy identity that names the
Concordance overlay requires both strict states to be present. Hidden overlay
state under a non-Concordance identity is refused.

The one-session production sequence is:

```text
Wealth Core -> breadth -> SPY -> native controller -> witness -> LD-RC
```

The durable `last_decision.target_core_exposure` is the final LD-RC-composed
exposure. Native exposure and the full LD-RC decision remain separately visible
in evidence. `final <= native` is asserted.

`effective_native_allocation` for close `t` is the previous LD-RC state's
`previous_native_allocation`: the native parent intent that became effective at
the prior executable open. Broker fills do not rewrite strategy state.

When an existing divergence latch clears by persistence or SPY V-rebound, that
clear is authoritative for close `t`. Divergence entry is skipped for the rest
of that `ldrc_step`; simultaneous entry evidence may latch again only at a
subsequent close.

## Execution timing

A decision at close `t` is persisted for the next executable session. Existing
catch-up may advance historical Wealth Core/native/witness/LD-RC state, but it
must never replay obsolete historical broker orders. Only the current surviving
plan may execute.

## Rollout authority

`PINNED_1_00` is an explicit legacy rollout override that can force 100% exposure.
It is incompatible with a Concordance strategy identity because it could erase a
55% LD-RC ceiling or bypass a recovery gate. Execution-plan construction must
refuse `PINNED_1_00` whenever the durable identity names the Concordance overlay.
Existing non-Concordance rollout behavior is unchanged.

## Activation gates

Implementation complete is not paper activation. Paper automation remains
blocked until all of the following are true:

1. PR #199 source is retained on main without semantic alteration.
2. Hardened 30pp parent has zero session-level allocation mismatches against its retained reference tape.
3. Recent-leadership membership/NAV/r20/r40 has zero session-level mismatches.
4. LD-RC episode/latch/streak/final allocation has zero session-level mismatches.
5. Close-decision -> next-open application parity is proven.
6. #192/#193 decision-relevant PIT/issuer/category/sector requirements are resolved or proven irrelevant.
7. Restart, duplicate-session, catch-up, stale/missing-evidence, and outage tests pass.
8. Strategy identity/certificate is rotated and explicitly authorizes the new parent + witness + overlay source hashes.
9. Fresh recertification reports universe/path changes, transitions, CAGR, max drawdown, Sharpe, and ending wealth.

Historical headline metrics are falsifiers only; they are not optimization
objectives.
