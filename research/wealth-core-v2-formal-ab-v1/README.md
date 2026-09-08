# Wealth Core V2 — formal-harness A/B

This experiment is rebuilt from the certified formal Research Champion harness.

## Base

- Certified repository base: `3af356ab6d329e7bc6cdc015a49a6ca2d4e4b864`
- Pinned runtime authority: `887f479b15ad861313da666ad698034d3847121c`
- Canonical broad-PIT dataset SHA-256: `5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`
- Warm-up: 2006-01-03
- Measurement: 2006-07-31 through 2026-07-31
- Architecture: Research Champion / EX3, 25 physical Wealth Core slots, 4% nominal entry target.

No certified `backtester/`, production, Sentinel, Wealth Core, or Research Champion source is modified on this branch.

## Construction

`formal_ab.py` asks the certified formal harness for its final composed source after strict-PIT, canonical-data, financial-grade, terminal/capacity, and Research Champion transforms.

- **V1** uses that final formal economic source unchanged.
- **V2** applies one declared, reversible patch set to the final source.
- Reversing all declared V2 patches must reproduce the exact V1 source byte-for-byte.
- Audit code is insertion-only. Removing the inserted audit blocks must reproduce the exact corresponding economic source byte-for-byte.

There are no observer v2/v3/v4 compatibility layers.

## Exact V2 economic contract

At decision close:

```text
nominal_target = current_resolved_equity * entry_weight
per_share_decision = decision_close_price * (1 + transaction_cost)
target_shares = floor(nominal_target / per_share_decision)
required_cash = target_shares * per_share_decision
uncommitted_cash = current_cash - cash_reserved_for_existing_pending_entries
```

Admission occurs only when `target_shares >= 1` and `uncommitted_cash >= required_cash`. A successful admission atomically reserves the physical slot and the full decision-time cash budget.

At the next executable open:

```text
fillable_shares = min(
    target_shares,
    floor(reserved_cash / (execution_open_price * (1 + transaction_cost)))
)
```

Later unrelated cash cannot enlarge or rescue the order. A zero-share executable-open result cancels the admission and releases the slot and reservation. Missing/non-executable opens and frozen capacity deferrals preserve the pending reservation. Any unused reservation is released after resolution. There is no top-up.

All other formal Research Champion economics remain frozen.

## Acceptance gates

The workflow must prove all of the following before the A/B result is accepted:

1. Certified formal source paths are unchanged from the certified base.
2. V1 and V2 final sources compile in unbound and canonical-PIT generation modes.
3. V2 patch reverses exactly to V1.
4. Audit insertion strips exactly to the economic source.
5. Canonical dataset pointer and package verify to the certified hash/window.
6. V1 `summary.json` reproduces certified SHA-256 `7488908b6e3da6141560838e8a825009e4462a11de733681addd17ac0658267a`.
7. V1 and V2 both emit `canonical_input_session_hashes.csv`; the files must be byte-identical.
8. V1 and V2 summaries must bind the certified canonical dataset hash.
9. V2 identity must state exactly one changed economic domain: `wealth_core_entry_slot_funding`.

## Audit outputs

The audit observes state only and does not feed decisions:

- `wealth_core_order_blotter.csv`
- `wealth_core_position_lifecycle.csv`
- `wealth_core_daily_observer.csv`

Terminal corporate actions are lifecycle events, not fabricated SELL orders. C1 grace settlements and terminal conversions are explicitly distinguished.
