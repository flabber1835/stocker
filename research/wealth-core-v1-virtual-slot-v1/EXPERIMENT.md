# Wealth Core V1 — micro-to-virtual-slot experiment

## Objective

Test whether Wealth Core V1 can eliminate microscopic **real security positions** while preserving the economic behavior that appears to make V1 successful.

This experiment is **pure Wealth Core only**. Sentinel outcomes are excluded from selection, scoring, and interpretation.

## Frozen control

Use the current corrected V1 lineage exactly as certified:

- V1 generated source SHA256: `bbd6783d0cd0e5d1662a0146190962e5845cc4b6bdb8feb50d0c7788f90a6077`
- normalized AST SHA256: `435d42ac56f160a665588a997335a923c25110404972e262aa6e47058b3befde`
- canonical PIT dataset: `5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993`
- measurement window: 2006-07-31 through 2026-07-31
- dividend lag: one session
- V1 pure Wealth Core CAGR: 15.24665012369839%

## Frozen microscopic definition

Reuse the definition fixed before the earlier micro-tail experiment:

`available decision capital / intended Wealth Core entry capital < 1%`

A next-open gap/affordability clip that would make the actual fill less than 1% of the original intended entry capital is also promoted to virtual status. Therefore no microscopic **real execution** is permitted.

## Primary mechanism

A microscopic admission does not create a brokerage holding. Instead it creates an explicit non-invested **capacity slot**:

- the slot consumes one of Wealth Core's 25 physical slots;
- it retains the candidate identity only as causal shadow state;
- stop, review, split, terminal-event, cooldown and release timing follow the same V1 lifecycle;
- it earns no dividends and no security price return;
- it is excluded from `research_selected_positions` and reported separately as `research_capacity_slots`;
- real holdings and capacity slots are separately counted.

This tests the hypothesis that V1's useful behavior is dynamic/sticky capacity suppression, not the P&L of microscopic holdings themselves.

## Two precommitted variants

### `virtual-slot-escrow`

The hypothetical gross execution capital is moved from free cash to locked cash while the capacity slot is alive. Locked cash remains part of Wealth Core equity but cannot fund new admissions. This preserves V1-like cash scarcity without owning the security.

### `virtual-slot-free-cash`

The capacity slot follows the same candidate lifecycle, but no cash is locked. All cash remains immediately available. This isolates slot occupancy from cash scarcity.

## Interpretation

- If escrow closely reproduces V1, the microscopic security P&L is unnecessary and the implementation can be replaced by explicit capacity state.
- If free-cash materially underperforms escrow, V1's useful mechanism includes both sticky slot occupancy and temporary cash scarcity.
- If both materially underperform V1, the microscopic security's mark-to-market/dividend path or another coupled state effect remains economically relevant.

No threshold sweep or parameter tuning is authorized from these results. The 1% boundary is frozen from the prior experiment family.
