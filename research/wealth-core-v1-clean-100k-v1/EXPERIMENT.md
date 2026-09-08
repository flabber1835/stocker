# Wealth Core V1 Clean $100k — preregistration

## Objective

Determine whether the exact Wealth Core V1 decision/slot path at a $100,000 starting capital can be executed without microscopic real holdings.

## Frozen authority

All economics are Wealth Core only. Sentinel is excluded.

The $100k V1 authority is GitHub Actions run `34267327656`, artifact `10073578819`:

- initial capital: `$100,000`
- measurement: `2006-07-31` through `2026-07-31`, 5,032 sessions
- canonical PIT dataset SHA-256: `5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`
- generated source SHA-256: `32cd228010e09b5be42271cd6d0c38831fe7fbc74e725f592949146c48104e0f`
- daily SHA-256: `8a2e4f948720674a56737ee6291df0aff12e02a74d74b1ec5f0c75f9929adee6`
- summary SHA-256: `929ed3baacd1bb66e8174d7a6822e362e5c90da75355177d33bab3ac9f201878`
- CAGR: `14.54603836086088%`

## Intervention

The decision ledger remains exact $100k Wealth Core V1.

At the next-open execution boundary only:

- compute actual executed funding fraction exactly as the frozen $100k diagnostic does;
- if the real fill is `<1%` of intended entry capital, do **not** execute it in the clean ledger;
- the V1 decision ledger still owns and causally tracks the slot/security exactly as V1, including splits, dividends, exits, reviews and terminal events;
- non-micro trades execute in the clean ledger with the exact V1 quantity and timing;
- skipped micro capital remains clean cash;
- a skipped micro security contributes zero mark-to-market, dividend, terminal cash or exit proceeds to the clean ledger.

The `<1%` boundary is frozen from the prior micro-tail research. It will not be tuned after observing this result.

## Hard gates

1. Reconstruct the exact authoritative $100k V1 source and reproduce its frozen source/daily/summary hashes.
2. The instrumented clean replay must retain every original $100k V1 daily cell exactly; only `clean_*` telemetry columns may differ/be added.
3. The original V1 summary must remain byte-identical.
4. Clean real micro entries must equal zero.
5. Clean ledger must be self-financing: every non-micro V1 order must be affordable with clean cash. Any affordability breach is a failed experiment, not silently borrowed capital.
6. Same canonical PIT dataset, session horizon, source/runtime/classifier pins and one-session dividend lag.
7. No Sentinel metrics or behavior may influence the result.

## Interpretation

If the clean ledger is self-financing and remains close to V1 economics, microscopic holdings are implementation artifacts and the useful mechanism is V1 slot/capacity state.

If the clean ledger is not self-financing or economics differ materially, do not tune the threshold. Diagnose the causal contribution of the omitted micro holdings and preregister a separate intervention.
