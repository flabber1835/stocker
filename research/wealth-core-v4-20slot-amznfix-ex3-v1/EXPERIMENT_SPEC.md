# Wealth Core V4 + Sentinel EX3 full-PIT experiment

## Definition

Wealth Core V4 is the frozen Wealth Core V3 / Median-5 economics with the whole-share close-affordability fix included and a 20-position book.

Required economic configuration:

- Median-5 ranking hardening
- 20 slots
- 5% target entry weight
- 10 bp cash/admission buffer
- next-valid-open whole-share sizing
- fractional shares disabled
- one-session dividend lag
- close-time whole-share affordability gate: at least one whole share must be affordable above the 10 bp reserve before admission
- exact quantity remains determined only at the next valid open

The affordability gate is the AMZN fix. V4 must not reproduce the repeated zero-quantity AMZN admissions from the pre-fix V3 run.

No other strategy economics are changed from the fixed V3 harness at base commit `a262817beb6238786af92afea24c34be13a15420`.

## Sentinel

Run frozen Sentinel EX3 / Candidate-A in parallel from the same Wealth Core path (`A_nav`).

## Horizon

- warmup start: 2006-01-03
- measurement start: 2006-07-31
- measurement end: 2026-07-31
- expected measurement sessions: 5,032

## Evidence contract

The runner must fail closed unless it proves all of the following markers exactly once in the generated strategy source:

- `N_SLOTS = 20`
- `ENTRY_W = 0.05`
- Median-5 hardening
- 10 bp reserve
- `_one_share_close_cost=float(px)*(1+COST)`
- `WHOLE_SHARE_UNAFFORDABLE_AT_CLOSE`
- next-open whole-share quantity calculation
- frozen Candidate-A / EX3 controller path

The run uses the immutable canonical PIT package and the same frozen economic, Median-5, classifier, formal, and runtime authorities as the fixed V3 harness.

This is a measurement run only. No tuning or performance target is used.
