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

## Current trading run and moving broker snapshots

The October 23 opening exposed two missing composed states. Keep the existing
future-only PlanPreview reader and notification eligibility unchanged. Add a
separate SELECT-only display of the bound current generation's latest effective
trading session, with the immutable preparation account snapshot as the intent
baseline. Show that dated plan before, during and after its run, including
per-command submitted quantities, confirmed cumulative fills, average price,
order terms and original progress timestamps. Never recompute an original trade
delta from holdings already changed by its fills. Show pending/working, partial,
filled, cancelled, rejected and uncertain outcomes explicitly. A SUCCEEDED cycle
does not fabricate fills or complete pending post-close financial verification.
Hide expired current-session evidence from subsequent trading dates; a new future
plan can lead while today's completed run remains available below it.

An INCONSISTENT broker snapshot remains unverified. It may be shown as amber
"Reconciling fills" only during an original, live, account/control/fence-bound
execution callback, with no uncertain or cancellation-pending commands, exact
current-plan working-order identities/terms, and positions inside the bounds
explained by that plan's owned commands from its recorded baseline. Unexpected
orders, unexplained positions, identity/term drift, missing evidence, foreign
activity and UNKNOWN outcomes remain red. The display wait expires at the
earlier of the callback's original deadline and 120 seconds after the cycle's
first retained inconsistent observation. Browser refreshes cannot renew either
clock. A clean complete observation exits this wait normally. This changes
display classification only; execution completeness and reconciliation guards
remain unchanged. Use the same evidence in HTML and panel JSON.

Qualify the composed pre-open -> executing -> partial/moving observation ->
reconciling -> succeeded display sequence, including the retained October 23
snapshot, plus negative controls and removal falsifiers for every new admission
gate. Keep notification and browser-negative-authority regressions. A local
application handoff may also use an already SUCCEEDED current-session run after
proving zero in-flight/unknown commands, no working native orders, identical
control, book, plan, journal, fills, policy, source and push-subscription state.
PostgreSQL and backup services remain untouched.

The live phone-width check also exposed a refused corpus pin in the cheap
market-data status reader. Retry only the typed `CorpusLockUnavailable` refusal
inside one fixed two-second page-read budget, rolling back the refused read and
reacquiring the authenticated publication on each attempt. Bound each statement
by the remaining original budget. Do not cache a successful frontier, retain an
old PASS, renew evidence times, retry integrity/time-out failures, or change feed
publication locks. Persistent contention remains an unreadable/red source fact.
Qualify both temporary and exhausted contention and unchanged negative verdicts.
