# Plan-first PAPER dashboard

Owner selection, 2026-10-22: implement mockup A. The primary mobile view is a
compact operational health card, the saved next trading plan, recorded paper
account totals, and the twenty canonical Wealth Core slots with cooldowns.
The existing operational rows, explanations, notifications, source diagnostics
and raw evidence remain available inside a collapsed System details section.
Use the existing dark plum and restrained gold Caesar's Palace identity without
decorative stage clutter. Keep the page usable at 320 CSS pixels and keyboard
accessible. No financial actions are introduced.

## Full-width existing brand graphic

Owner selection, 2026-10-30, before implementation: enlarge the existing
Caesar's Palace graphic to the full available header width, preserving its
aspect ratio. Remove the separate visible Caesar's Palace heading and
Sentinel/PAPER subtitle because the graphic already contains the brand name.
Keep an accessible image description, the document title, operational labels,
and every other dashboard section and layout unchanged. Reuse the existing
asset; do not generate another image or introduce horizontal overflow.

## Display evidence and ownership

### System health and visible background work

Owner selection, 2026-10-30, before implementation: the main colour answers
whether the system is doing its expected work, not whether a trading plan has
already been saved. Green means healthy normal work or scheduled waiting;
amber means degraded operation, an unexpected delay or a condition needing
review; red retains failed or unreadable required checks. Show the actual
stage, such as acquiring closing data, publishing data or preparing strategy
verification, beside the colour. Keep plan readiness explicit and separate.

Admit green for normal pending work only from the existing bounded, automatic
recovery proofs and current producer ownership, never merely a WAITING/RUNNING
string or an unexpired retry. Unknown warning classes stay amber. Existing
failures, unreadable sources, missing ownership, expired clocks and unresolved
notifications keep their negative priority. Do not change row verdicts,
financial verification, native scheduling, execution permission or installation
gates. Preserve the existing machine `overall`, `operational` and `color`
contracts; expose the separate dashboard health interpretation explicitly in
JSON and in the visible legend. Green health does not certify financial values
or grant permission to trade.

Put the next plan's current preparation above today's completed history. Reuse
the bounded operational-job metadata read: validate its immutable request/hash,
current closing-session target and publication predecessor, and require its
registered owner, live lease and original deadline before describing active
acquisition. Use existing exact atomic-publication proofs for publishing; an old
committed lease alone cannot prove that an atomic writer stopped. Parked retry
states describe waiting, not downloading. Show recorded stage-local counters
and original last-progress/retry times, without an invented percentage, total
or ETA. No corpus scans, provider requests, observer work or writes belong in
this HTTP projection. Retained pages must withdraw the healthy/live-work claim
at its original evidence boundary and cannot renew it by refreshing the page.
Keep the existing general presentation budget. Shorten it for the particular
normal-work proofs used to earn green, rather than turning every unrelated
short operational lease into a new polling deadline. An idle-leader proof still
uses its own lease boundary. A short proof may withdraw the display before a
refresh succeeds, but must not force a one-second HTTP polling loop; use a
bounded refresh cadence with the existing negative-only expiry timer.

Decision, 2026-10-30, before implementation: browser refreshes must not replace
the document while its tab is hidden. A background replacement loses the prior
foreground lifecycle and can turn a normal app return into an immediate stale
red. Do not start a hidden refresh or install a response completed after the tab
became hidden; retain the original document, observation clocks and controller.
On foreground return, use the existing single-read, finite last-known resume.
An initially hidden document that first becomes visible after its original
expiry also enters that resume; a fresh initially hidden document needs no extra
read before its ordinary refresh is due. If that ordinary timer elapsed while
hidden, perform that deferred read on first visibility rather than waiting for
proof expiry. Resume may withdraw green into amber only, never renew a financial proof,
hide a known failure, override offline state or restart its original 15-second
deadline. Preserve the minimum five-second polling cadence and the independent
negative-authority expiry timer.

Decision, 2026-10-31, before implementation: current proof lifetime and HTTP
availability are separate clocks. A measured five-second polling delay plus a
six-second request can exceed an original nine-second leader-bound document.
Withdraw green, live preparation and current financial styling at that original
proof boundary. While the already-owned refresh or its bounded transport retry
is still within fifteen seconds of the document's first visible request, show
explicitly last-known amber instead of reporting an operational failure. Anchor
that transport deadline once; retries, focus and visibility events cannot renew
it. An independent deadline must withdraw this allowance even if a network
promise never settles. No pre-expiry owned refresh means no ordinary allowance.
Preserve the five-second polling floor, every server observation clock and all
financial/execution gates. Only a complete fresh server document earns green.

Distinguish an availability-expired view from a known negative result. A first
foreground resume after a hidden transport failure can use the existing finite
resume window; repeated lifecycle events cannot extend it. An unconfirmed focus
event borrows an existing ordinary request's deadline rather than buying another
window. Without a remembered return or an already owned request/resume clock,
focus only withdraws expired display authority and keeps the ordinary read due.
A recorded page hide or visibility transition establishes foreground
return. Handle pagehide, visible focus and non-persisted pageshow consistently;
a fresh initial page needs no extra request. Known server failures, offline
state, malformed evidence and invalid clocks remain red immediately. A response
body transport error is availability failure until HTML validation begins.
Expired resume remains red until a fresh server answer; clearing availability
styling must not clear a hard negative or revive an exhausted resume.
Latch an observed resume deadline so a later wall-clock rollback cannot revive
it. A clock earlier than an already started request or resume is invalid clock
evidence and remains a hard negative, including on a later lifecycle event.
The negative age timer may withdraw a very short proof before ordinary polling
is due, but it cannot bring that ordinary request forward. Preserve the first
scheduled five-second-or-longer read even for subsecond remaining proof. An
explicit foreground resume retains its existing immediate single-read exception.
Retain the recorded page-hidden state until an actual visible lifecycle event,
so a delayed age callback cannot begin a resume while iOS still reports the old
visibility value. A trusted persisted pageshow also establishes a return.

Completed publication metadata remains a dated data fact, not proof that a plan
is still being prepared. If an admitted future saved plan exists, describe the
publication without a pending-plan claim. Stop using a completed publication as
next-plan preparation at its own effective-session exchange open, even if a new
metadata read has a fresh observation time. Reuse the deterministic XNYS calendar;
an unavailable session boundary withdraws this display fact rather than inventing
another market clock. This does not change plan admission or any trading gate.

Decision, 2026-10-30, before implementation: a typed, authenticated
`SCHEDULED_WITH_HISTORY` record is a historical audit warning, not by itself a
current operational incident. The human health card may be green only while
the exact admitted future saved plan and its original schedule boundary agree,
the policy is enabled and kill-released, the current account, source, authority,
leader, canonical portfolio, runtime, backups and notifications are healthy,
and the current represented broker/reconciliation evidence is usable. The typed
history state already requires the exact native scheduled-readiness proof;
broker RUNNING text alone does not establish this eligibility. Require the
original bounded WAITING_OPEN cycle and open-step proofs; missing, unknown,
blocked, retrying, stale, expired or contradictory current facts prevent this treatment.
Use only the already-projected typed evidence; do not start an observer or read
another database source from the presentation.

Keep the financial row's WARN severity, PAPER-not-verified qualification,
historical detail, original validity and machine aggregates unchanged. Describe
it as a historical paper audit inside System details, without an actionable
front-page attention item while every current proof is healthy. Its original
expiry or a current incident remains actionable. No acknowledgement, manual
review marker, new authority or transport permission is created. Bound green
by the original current proof deadlines it uses, including the live leader,
and retain the existing browser withdrawal and minimum refresh cadence.
Green means healthy autonomous future scheduling under the native execution
safeguards. It does not assert that every holding is unrestricted, that an old
corporate-action discrepancy is resolved, or that future orders will fill.
Execution still performs its fresh account, source, restriction and reconciliation
checks. A restriction represented by a current failed, blocked or retrying fact
retains its negative priority; no missing positive clean/restriction receipt is
invented to complete this read-only presentation.

Decision, 2026-10-30, before implementation: the same complete current scheduling
predicate also admits the existing owned, finite PAPER `CHECK IN PROGRESS`
observation as healthy expected work. Require its required-current WARN,
automatic non-operator `FINANCIAL_VERIFICATION` evidence, matching original
validity/deadline and live bound, plus the same saved future plan, healthy current
facts and bounded WAITING_OPEN cycle/open steps. A previous failed or unknown
result is not checking evidence and keeps its negative priority. Missing/dead
ownership, another warning class or exhausted original clocks cannot borrow this
state. Label this workflow `Checking paper account` ahead of old PUBLISHED-job
copy, without claiming a current financial PASS. Preserve all financial/machine
WARNs and the original PAPER and leader deadlines; introduce no observer,
acknowledgement, authority or renewed lifetime. Only an actual historical audit
flag receives the historical-audit label.
The original browser budget also ends at the saved future plan's execution
start, even when a checking or leader deadline extends beyond that boundary.

The detailed checks retain the existing server operational verdict, required-current
checks, failure reasons, source errors, original evidence clocks, JSON/machine
readiness and browser negative-authority withdrawal rules. A green health card
means normal current operation; plan readiness and completed trades remain
separate facts. Failures remain visibly named at
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

## Completed run after an intraday software update

Decision: 2026-10-30, before implementation. The owner requested a local
presentation patch. Activation can change control generation and supersede the
saved plan after today's run has already succeeded. Keep the current-generation
trading-run reader and future-only PlanPreview eligibility unchanged. Their
absence must not imply that the completed original plan was lost.

Only when the current-run reader returns no row without an error, read a
separate `completed_trading_run` display record. Require exactly one older-
generation SUCCEEDED cycle for today's New York session, a real non-future
completion after its execution time, no current failure code, a retained clean
reconciliation, and the same currently owned deployment, broker, account and
takeover epoch. A superseded original plan is eligible only for this historical
display. Recheck its immutable plan fingerprint, original sizing/account
authority and bounded recorded commands through the existing projections.
Foreign, ambiguous, unfinished or malformed evidence remains unavailable;
current-run errors and negative operational facts cannot be replaced by history.

Reuse the typed TradingRun payload under the separate row key in HTML and JSON.
Prefer the strict current run when present. Clearly label the fallback as a
recorded completed run, retain its original clocks, order outcomes and session
expiry, and say that the next plan is pending. It grants no execution authority,
does not claim fills from SUCCEEDED, and does not complete post-close financial
verification. Missing or failed historical evidence cannot manufacture success.

Qualify the real generation-change/supersession query and rendered fallback,
account/takeover/session/completion/ambiguity refusals, exact original intent,
current-error precedence, original expiry, and unchanged future eligibility.
Execute guard-removal falsifiers. Apply only the qualified HTTP presentation
image using the existing narrow local presentation contract in
[current dashboard evidence](current-dashboard-evidence.md). Preserve the signed
financial runtime, verifier subject, five other application roles, PostgreSQL,
control generation, authority, history and backup ownership. No installation,
financial activation, plan replay or backup/restore operation is introduced.
