# Wealth Core V1 slot-mechanics experiments

This is an isolated follow-up to `research/wealth-core-v2-current-v1-ab`.

## Scope

- Wealth Core only.
- Corrected current V1 economic lineage.
- Exact canonical full-PIT dataset.
- 2006-07-31 through 2026-07-31 measurement window.
- 25 slots, 4% intended entry weight.
- One-session dividend settlement.
- Outcome authority is `shadow_equity` only.
- No Sentinel/full-system result is used to select, rank, accept, or reject an experiment.

The inherited production-equivalent executable still contains downstream controller code for compatibility, but it has no feedback path into Wealth Core. This experiment harness ignores every downstream NAV/allocation field.

## Frozen hypotheses

1. `jit-full-funding`: require a full intended position at the close decision, but do not reserve cash. Next-open execution remains V1-style. This separates V2's full-funding rule from persistent cash reservation.
2. `micro-tail-reject`: preserve V1 partial entries except reject entries whose available entry capital is below 1% of the intended 4% entry. This tests whether only the microscopic funding tail is harmful.
3. `opportunity-micro-reclaim`: preserve V1 entries. When all slots are occupied and a fully fundable new candidate is blocked by slot capacity, recycle a current holding worth less than 1% of the intended entry capital (less than 0.04% of portfolio equity).
4. `opportunity-partial-reclaim`: preserve V1 entries. Under the same blocked-candidate condition, recycle the incumbent with the lowest original entry-funding fraction, provided it was underfunded.
5. `cash-recovery-reclaim`: preserve V1 entries. Once free cash is again sufficient for a normal intended entry and all slots remain occupied, recycle the most underfunded-at-entry incumbent even without a contemporaneous candidate trigger.

Reclamation exits execute at the normal next open with normal transaction cost. The sold security retains its normal security cooldown; only the vacated slot is made immediately reusable. This avoids same-security churn while testing slot capacity itself.

## Control gates

Every matrix job independently rebuilds V1 and refuses to run unless:

- generated V1 source SHA-256 is `bbd6783d0cd0e5d1662a0146190962e5845cc4b6bdb8feb50d0c7788f90a6077`;
- normalized V1 AST SHA-256 is `435d42ac56f160a665588a997335a923c25110404972e262aa6e47058b3befde`;
- canonical PIT dataset hash is `5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`;
- dividend lag remains exactly one session;
- the replay contains all 5,032 measurement sessions.

The five variants run as a five-way GitHub Actions matrix with `max-parallel: 5`.
