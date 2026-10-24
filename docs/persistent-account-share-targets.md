# Persistent account share targets

Owner decision, 2026-10-22: do not rebalance an existing position merely because
account NAV and shadow NAV changed by different percentages. PBR.A stayed at
132 shadow shares and 55% controller exposure, but daily flooring moved the
account target from 72 to 71. That sale was unwanted execution turnover.

The production dual PAPER adapter now carries its previous durable account
target for each continuing Wealth Core episode. Episode identity is the stable
security ID, slot and original signal session; a pending entry and its resulting
episode have the same identity. Broker holdings never determine the target.
Partial fills, an expired DAY order and a restart leave the intended quantity
outstanding. New entries are sized normally; exits remain zero targets. A new
episode in a reused slot is a new entry. A change in effective Sentinel exposure
resizes the basket normally and establishes new account quantities. This rule
applies to the defensive sleeve too while the allocation is unchanged.

Accept price-driven weight drift between allocation decisions. Do not silently
sell an unchanged holding to restore a percentage. Retained positions can exceed
the nominal Core allocation after appreciation; that does not permit additional
spending above the allocation. Clamp new-entry allocation to zero when retained
Core value already consumes it. Keep account-wide long-only, cash-only,
buying-power, protected limit, reservation and UNKNOWN-outcome guards. Report
the nominal allocation and actual holdings separately. No margin is permitted.

Persist an immutable predecessor basis in version 2 of the existing dual sizing
authority. It names the previous account-bound plan, authority and final target
projection, and the carried quantities. Re-derive it from those retained records
at every sizing-proof boundary. Apply authenticated scalar corporate actions
between the previous projection and the new decision; do not mistake a split
for a sale, an entry, or NAV drift. Unsupported or ambiguous actions refuse.
Decision-to-open action projection remains responsible for the next boundary.
Within one existing writer/publication verification scope, reuse only the small
detached predecessor basis. Bind reuse to economic row versions and freshly read
predecessor plan/projection row versions. Do not decompress the full retained
shadow JSON before every broker read just to recover its parent plan ID.

Historical version 1 authorities and already prepared plans keep their exact
arithmetic. Installation does not rewrite a plan, cancel a working order, undo a
filled sale, or repurchase the sold PBR.A share. The next new plan seeds from the
current durable target (71 PBR.A), and later plans preserve it until an exit or
an allocation change. No schema migration, book change or broker-state feedback
into Wealth Core or Sentinel is involved. Backups remain disabled under the
owner's existing local PAPER instruction.

For this prospective owner-local PAPER update, stop all application writers only
after the increase window has closed and exact native resting-order ownership is
clean, with no uncertain command. Before stopping, the successor image must
re-derive the current historical authority and replay its final protected
projection identically. Require identical native execution configuration, the
same canonical Wealth Core source, and unchanged control generation, plan,
command identities and order terms. Start and verify shadow before resuming the
other workers. This narrowly permits the new policy at the next new plan without
rewriting or reactivating today's plan. Any refusal leaves the old plan intact;
do not relax authority, replay a trade or alter a clock. PostgreSQL is not
restarted and no backup or restore operation is part of installation.

The first installed successor was correctly fenced on recovery: standing PAPER
authority still named the old execution-inclusive strategy fingerprint. Pure
plan replay did not test this boundary. Preflight must also call the real
standing automation-authority check before starting workers or releasing a kill.

For this owner-authorized local PAPER change only, admit the exact strategy
fingerprint transition from `7f94cb127d4abac3001ffbe3de7d794775fbaae95a9406708eef990524f7c437`
to `caab7a1872fe4ec178aec659716a4bc70c0cd5ea79a88e33ffacd2ae0c7cf095`.
The former is independently verified from the installed predecessor and its
signed certificate; the latter commits the documented persistent-share code.
The controller rule, canonical Wealth Core package/configuration, universe,
market inputs and cash policy remain identical. This is local owner authority
for an execution-policy change, not a replacement or alteration of the signed
certificate. Keep the full source fingerprint visible. No wildcard semantic
compatibility, other strategy/configuration, live endpoint or normal-release
exception is authorized. The existing runtime, signature, account, controller,
publication, configuration and cash guards still run. Recover a fenced native
cycle and release its kill only through the supported operator commands.

Keep account-status observation independent of a daily execution cycle. The
existing local PAPER alert dispatcher polls the authenticated paper account at
most once a minute through the execution adapter, within an eight-second bound.
Bracket the observation with two typed account snapshots, require the bound
native account and USD currency, and recheck the durable binding and current
command facts before appending operational account evidence. Release database
transactions before network I/O. This existing append-only table is read only
by the operator panel; it supplies no trading authority, reconciliation, fill
completeness or financial ledger update.

When cash exceeds buying power, an account display may explain that difference
only with freshly read native open orders matching every current in-flight
journal command by account, deployment/epoch, client key, order ID, asset ID,
side, state, quantities and immutable terms. Require only known simple LIMIT/DAY
BUYs, exact remainders, no foreign or uncertain open orders, stable cash/buying
power around the read, and a total limit reservation matching the shortfall
within $1. Retain the native order facts in the same append-only account row.
The panel rechecks the current journal/binding and same-session market clock.
Missing, stale, partial, changed or inconsistent facts never waive the cash-only
display failure. Preserve the ten-minute freshness limit and all real blocked,
leveraged, negative or invalid account failures. Failed reads retain the old
observation without refreshing its clock. Normal-release account display and
all execution cash/reservation guards remain unchanged. The panel itself still
has no broker credentials or provider polling.

After supported local PAPER reactivation, distinguish a failed retired cycle
from a failure of the active generation. If the current healthy, authorized,
enabled generation has no owned/adopted cycle yet, and fresh native account
evidence is valid, retain the old terminal failure visibly as an amber history
warning while the next decision is pending. First check global mirror integrity;
a mismatch still fails. This is never CLEAN, SCHEDULED, VERIFIED, or evidence of
completed recovery. Current/adopted failures, disabled or killed policy, invalid
account evidence and normal release operation retain their existing failures.
The health reader counts known working orders as outstanding too: require that
this count equals the number of exact native orders covered by the reservation
proof. Any uncertain, foreign or uncovered outcome still refuses.

Verification covers the observed 72-to-71 and inverse rounding cases, new entry
to held-episode continuity, partial fills, restart/re-derivation, actual exits,
same-symbol new episodes, exposure changes, share-unit actions, tampered or
cross-account predecessor evidence, and allocation drift without new buying
power. Guard-removal falsifiers must fail. Use isolated targeted tests only;
do not invoke backup, restore or Wealth Core test campaigns.
