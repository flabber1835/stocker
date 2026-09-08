# Wealth Core slot-funding correction — implementation scope

Status: implementation guardrail. This branch corrects one foundational Wealth Core economic invariant and nothing else.

Base: `main` at `df4683b8bf1c80453b8f542f4e3ed441387ad3f5`.

Related forensic record: issue #335 and `research/median5-slot-forensics-v16/research/median5-slot-forensics-v16/SLOT_ECONOMICS_DECISION_RECORD.md`.

## Problem

The common Wealth Core admission kernel historically used cash-clipped decision sizing:

```python
target = equity * entry_weight
shares = floor(min(target, cash) / per_share)
```

Any positive whole-share amount could therefore reserve and occupy a complete physical portfolio slot. A microscopic cash remainder could acquire the same scarce slot status and breadth vote as a properly funded target position.

This behavior predates LDRC and was inherited by Champion, Caesar-20, and Median-5.

## Corrected invariant

A new episode may reserve a slot only when **uncommitted cash can fund the complete decision-time whole-share target order**.

For candidate price `p` on decision session `t`:

1. `nominal_target = resolved_equity * entry_weight`.
2. `per_share = p * (1 + transaction_cost_bps / 10_000)`.
3. `target_shares = floor(nominal_target / per_share)`.
4. `required_cash = target_shares * per_share`.
5. `reserved_cash = sum(cash reservations for already-pending entries)`.
6. `uncommitted_cash = state.cash - reserved_cash`.
7. Admission is allowed only when `target_shares >= 1` and `uncommitted_cash >= required_cash`.
8. Admission reserves the slot **and** `required_cash` atomically in persistent state.
9. A non-executable next session preserves both the pending order and its cash reservation.
10. At the next executable open, an upward gap may reduce share quantity, but the order may spend **only its reserved dollar budget**. No additional account cash is added to rescue it.
11. If the reserved budget cannot buy even one share at the executable open, cancel the entry and release both slot and cash reservation.
12. Unused reserved cash after a partial-at-open fill returns automatically to uncommitted cash.

## Economic interpretation

A slot means **one properly funded investment episode**, not “at least one share was affordable.”

A portfolio may legitimately have empty slots. If stopped/reviewed positions return less cash than a fresh target episode requires, cash accumulates until another properly funded episode can begin. The engine does not borrow and does not trim surviving winners to force nominal slot count back to the maximum.

## Explicit non-goals

- no minimum-fill percentage parameter;
- no performance-selected threshold;
- no winner trimming to finance entries;
- no leverage;
- no change to ranking, eligibility, review, stop, cooldown, issuer, terminal, dividend, split, or decision/fill timing semantics;
- no LDRC / EX3 / Sentinel controller retuning;
- no Caesar-20 or Median-5 economics;
- no claim that any prior downstream winner remains optimal after this correction.

## Required falsifiers

The implementation is not complete unless tests prove all of the following:

- microscopic cash cannot reserve a target slot when the whole-share target is materially larger;
- sufficient cash reserves both the slot and the exact whole-share target notional;
- simultaneous/pending entries cannot promise the same cash twice;
- restart serialization preserves reserved cash exactly;
- a restored reservation with no positive cash budget is refused rather than silently reinterpreted;
- aggregate reserved cash cannot exceed account cash;
- an upward gap clips shares within the already-reserved budget even when the account has additional uncommitted cash;
- an unaffordable-at-open order cancels and releases its slot/cash claim;
- a non-tradeable open preserves the slot/cash claim;
- initial construction cannot overcommit cash across multiple reservations;
- existing exit, dividend, split, terminal, stop, review, and cooldown behavior remains unchanged except for downstream consequences of correctly blocked admissions.

No historical CAGR result may be used to alter this invariant on this branch.
