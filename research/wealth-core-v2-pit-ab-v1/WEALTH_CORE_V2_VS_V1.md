# Wealth Core V2 vs V1 — exact economic difference

Status: research contract. This document defines the intended one-domain economic change under test. It is not a performance-selected rule.

## V1

At the decision close, Wealth Core V1 sizes a new entry as:

```python
target = min(current_resolved_equity * entry_weight, current_cash)
shares = floor(target / (decision_close_price * (1 + transaction_cost)))
```

If at least one share is affordable, the candidate may reserve a physical portfolio slot.

Consequences of V1:

- available cash is allowed to shrink a nominal 4% target into any smaller whole-share position;
- a one-share or otherwise microscopic position can consume exactly the same physical slot as a fully funded target position;
- a pending entry reserves the slot but does not reserve a dedicated cash budget;
- at the next executable open, the order is clipped against whatever account cash exists at that later time;
- cash arriving after the decision from unrelated sales/dividends may therefore finance the queued entry;
- an upward gap may reduce the fill to any affordable positive share count;
- there is no later top-up to restore the intended entry weight.

## V2

At the decision close, Wealth Core V2 first computes the complete intended whole-share target independently of available cash:

```python
nominal_target = current_resolved_equity * entry_weight
per_share_decision = decision_close_price * (1 + transaction_cost)
target_shares = floor(nominal_target / per_share_decision)
required_cash = target_shares * per_share_decision
uncommitted_cash = current_cash - cash_reserved_for_existing_pending_entries
```

A new entry may reserve a physical slot only if:

```python
target_shares >= 1
and
uncommitted_cash >= required_cash
```

If that condition is false, no slot is reserved and no buy order is created. The candidate may compete again on a later session under the normal ranking/admission rules.

If the condition is true, V2 atomically reserves both:

```text
1. the physical slot
2. the complete decision-time required_cash budget
```

The reserved dollars remain part of portfolio cash/equity until execution, but they are unavailable to finance any other pending admission.

At the next executable open:

```python
fillable_shares = min(
    target_shares,
    floor(reserved_cash / (execution_open_price * (1 + transaction_cost)))
)
```

Therefore:

- an upward overnight gap may reduce shares only within the already reserved dollar budget;
- later unrelated cash cannot enlarge or rescue the queued order;
- if `fillable_shares == 0`, the admission is cancelled and both the slot and reserved cash are released;
- if no executable open exists, the pending order, slot reservation, and cash reservation persist;
- unused reserved cash after a gap-reduced fill immediately becomes uncommitted cash again;
- there is no later top-up.

## Economic interpretation

V1 treats a slot as occupied when any positive whole-share position can be afforded.

V2 treats a slot as one properly funded investment episode. A slot may remain vacant when the account does not yet have enough uncommitted cash to fund the complete decision-time whole-share target.

For the 25-slot Research Champion baseline, `entry_weight = 0.04`. For a 20-slot architecture, the equivalent intended target is `0.05`. The V2 rule is the same in either case.

## What V2 does NOT change

V2 does not change:

- broad point-in-time universe construction;
- security eligibility or security-type classification;
- ranking or durable-score economics;
- top-decile selection;
- issuer conflict rules;
- one-admission-per-session pacing after initialization;
- review age or review logic;
- trailing-stop logic;
- slot cooldown or security cooldown;
- split, dividend, terminal-event, or corporate-action handling except where a pending entry must release/preserve its explicit reserved cash consistently;
- decision-close / next-open timing;
- transaction-cost rate;
- Sentinel/native risk rules;
- EX3/LDRC controller parameters;
- winner trimming;
- leverage;
- minimum-fill percentage thresholds;
- any later rebalancing or top-up behavior.

## Core invariant

**V1:** `cash can shrink the intended entry until at least one share fits.`

**V2:** `a slot can be claimed only by a fully funded decision-time whole-share target; execution may gap-clip only inside that pre-reserved budget.`

That is the entire intended economic difference between Wealth Core V1 and Wealth Core V2.