# Plan-first PAPER dashboard

Owner selection, 2026-10-22: implement mockup A. The primary mobile view is a
compact operational health card, the saved next trading plan, recorded paper
account totals, and the twenty canonical Wealth Core slots with cooldowns.
The existing operational rows, explanations, notifications, source diagnostics
and raw evidence remain available inside a collapsed System details section.
Use the existing dark plum and restrained gold Caesar's Palace identity without
decorative stage clutter. Keep the page usable at 320 CSS pixels and keyboard
accessible. No financial actions are introduced.

## Display evidence and ownership

The health card retains the existing server operational verdict, required-current
checks, failure reasons, source errors, original evidence clocks, JSON/machine
health and browser negative-authority withdrawal rules. A green card means
operational readiness, not completed trades. Failures remain visibly named at
the top even when System details is collapsed. Retained pages and stale browser
documents label all overview values last known; no new green styling is earned
by moving a value into an overview.

The plan is the existing typed saved PlanPreview with its original observation,
creation and execution times. Show actionable changes first, with all targets
available on expansion. No current broker holdings or fills are inferred from a
saved target. Read any previous per-security order outcome only from durable
account-bound execution/notification evidence with exact command or native order
identity, side, quantity, filled quantity, state and evidence time. Distinguish
expired/unfilled, partially filled, rejected, cancelled, working and uncertain;
unknown facts are unavailable. Do not turn an old outcome into an automatic
retry or claim a reason why a broker order failed without evidence.

Account equity/cash and BIL value come only from existing durable paper-account
observations with an explicit observation time. Omit unavailable allocation
figures rather than substitute shadow NAV, zeroes or a fabricated live read.
The dashboard remains SELECT-only and receives no broker credentials. A saved
cash balance is not a funding authorization.

Slots come from the authenticated canonical retained book already admitted for
holdings display. Preserve actual slot identity, ownership and pending strategy
operations. Display model stock tickers separately from proposed PAPER actions;
the model's quantities are not paper share counts. Cooldown is measured from
the canonical session/empty-slot counters and canonical configured duration, in
trading sessions. Do not invent a new strategy calendar or reconstruct a book.
Show all twenty slots when that book has twenty, distinguish occupied, cooling,
reserved and ready states, and never infer empty slots from missing input.
Malformed or unavailable projections stay visibly unavailable. This is display
projection only: no strategy, controller, sizing, order, journal, source or
execution-window changes.

## Qualification and local delivery

Cover the authenticated slot projection, remaining cooldown arithmetic, account
identity and arithmetic, exact native-order outcome provenance, malformed and
missing evidence, compact layout, escaping, and original freshness boundaries.
Keep the existing panel health, retained-refresh, browser resume and notification
checks. Inspect the actual mobile page before delivery. Install the exact tested
local image through the existing quiescent future-plan application handoff;
preserve the plan, generation, book, database, journal and order terms. No backups,
archives, restore work, PostgreSQL restart or backtest activity is authorized.
