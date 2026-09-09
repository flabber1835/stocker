# Canonical 10 bp / next-open execution harness

## Decision

There is now one active research implementation of the 10 bp + next-open whole-share execution contract:

`research/median5-open-sizing-10bp-ex3-v1/canonical_execution_harness.py`

Contract version:

`wealth-core.open-time-whole-shares-10bp/2`

Future Wealth Core experiments that use this execution model must apply their stock-selection / portfolio-construction overlay first, then apply this canonical execution transform. They must not copy or independently reimplement the execution seams.

## Canonical contract

### Decision close

The close binds only:

- selected security;
- intended dollar target / target weight;
- slot reservation and decision provenance.

The close does **not** bind share quantity.

A 10 bp cash cushion is retained for admission. For whole-share execution, a candidate may be admitted only when cash above that cushion can fund at least one share at the known close price including modeled transaction cost:

`cash_above_10bp_reserve >= close_price * (1 + COST)`

If no cash remains above the reserve:

`q0_reason = CASH_SCARCITY`

If positive cash remains but it cannot fund one whole share:

`q0_reason = WHOLE_SHARE_UNAFFORDABLE_AT_CLOSE`

The admission loop then continues down the frozen candidate order.

### Next valid open

The 10 bp admission cushion is released into the execution funding pool. Quantity is determined from actual opening price and actual available cash:

`execution_budget = min(intended_close_target, actual_cash_before_buy)`

`shares = floor(execution_budget / (open_price * (1 + COST)))`

The next-open zero-quantity guard remains necessary because an extreme overnight gap or a change in available cash can still make an admitted security unaffordable.

## Why the affordability gate exists

Full-PIT run `34299991647` exposed five zero-share open events. They were one repeated AMZN incident from 2015-12-04 through 2015-12-10. The 20-slot Median-5 book had 19 holdings and only $283.521942 cash, while AMZN traded above $650. The old close rule admitted AMZN because approximately $33-$37 remained above the 10 bp reserve, even though one share was already impossible to fund.

The exact event-level diagnosis is preserved in:

`EXECUTION_BLOCK_INVESTIGATION.md`

## Harness audit

### Historical open-sizing harness

`research/wealth-core-v1-open-sizing-10bp-v1/run_open_sizing.py`

Original evidence head:

`3dc74a8e54fdfe6e8368a8db3be0ecd127ee4689`

This implementation proved the value of sizing at the open, but its whole-share close admission rule required only positive cash above the reserve. It therefore predates the one-share affordability correction.

It is historical evidence, not current execution authority. Its old workflow is retired from economic execution; the original commit remains the immutable provenance reference for its completed results.

### Older buffer-only harnesses

The pre-open-sizing 10 bp buffer harnesses computed an integer share quantity at the close and already skipped candidates when `q < 1`. Therefore they did not contain this particular "positive cash but less than one share" admission hole. They remain historical experiments and are not the active next-open execution implementation.

### Median-5 experiment runner

`run_experiment.py` no longer imports the historical open-sizing runner. It imports only the canonical execution harness in this directory. Median-5 remains a separate Wealth Core overlay; EX3 remains a separately measured exposure-controller path.

## Governance

For future experiments using this execution model:

1. Pin the economic/base source and PIT authorities.
2. Apply the requested Wealth Core selection/configuration overlay.
3. Apply `apply_open_time_whole_share_10bp()` from the canonical harness exactly once.
4. Fail closed if canonical markers are missing or duplicated.
5. Preserve `close-decisions.csv`, `open-sizing-events.csv`, `open-sizing-telemetry.json`, transactions, daily NAV, and source hashes.
6. Do not create another execution-harness copy for a strategy variant.

The current full-PIT workflow is manual-dispatch only. No experiment is authorized by this consolidation work.
