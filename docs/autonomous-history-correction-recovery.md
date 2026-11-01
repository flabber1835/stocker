# Autonomous recovery from retained cash corrections

Decision: 2026-10-31, before implementation. This is an execution recovery
change for the existing PAPER system. It grants no LIVE authority and does not
change Wealth Core, the controller, the canonical action compiler or the book.

## Observed failure

The retained October 20 DELL record contains no DELL action. Publication 11
later includes a USD 0.63 ordinary cash dividend for the same session and
permanent security. The retained archive correctly preserves both the original
record and the new correction evidence. Its generic `historycorrection` marker
currently becomes a share-transport restriction. A newly discovered automation
cycle then waits for fully clean reconciliation before preparing any plan.

This is new cash knowledge, not proof of economic equivalence or payment.
Matching current broker shares cannot establish dividend entitlement or resolve
the correction. The existing [late cash policy](late-cash-distributions.md)
remains authoritative for canonical forward recognition; the existing PAPER
entitlement and performance-quarantine rules remain authoritative for broker
reporting.

## Positive cash-addition classification

An execution-only reader may classify `CASH_ONLY_ADDITION` only from the exact
authenticated held publication and its retained action coverage. Authenticate
the original sparse record, coverage links and current correction marker; bind
the classification to their hashes, publication versions, permanent identity,
effective session and classifier version. Missing, malformed, contradictory or
superseded evidence supplies no classification.

The narrow supported case is a positive, finite ordinary cash dividend added
after covered absence for that security/session. Prove that the original
retained record has no affected cash, scalar, unsupported, unresolved or identity
event being replaced. The new evidence must have one unambiguous permanent
identity, only the supported cash source addition, no scalar/unsupported/
unresolved/identity action for that identity, a unit split ratio and a dividend
bar consistent with the existing canonical cash normalizer. Unknown fields or
mixed structural changes cannot acquire this classification. Other securities'
events on the same day remain independent.

This classification means cash evidence is routed; it never means cash is paid,
the account is reconciled, or historical PAPER performance is verified. Keep
ordinary structural restrictions for removals, replacements, changed identities,
splits, unsupported actions and unavailable preimages. No ticker/date exception
or DELL-specific bypass exists.

## One execution view for actions and cash

Use the same qualified evidence for both execution share restrictions and the
existing `SnapshotCashInputs` entitlement reader. A delegated action view may
remove only the exact classified generic history marker from structural
restrictions. Scalar multipliers and all other material events are unchanged.

The cash view includes the classified session and its security-scoped source,
bar, identity and predecessor evidence. Preserve original data for unrelated
securities and preserve the original sparse archive byte for byte. The existing
dated durable-fill ownership calculation, dividend normalization, account cash
checks and permanent PAPER performance quarantine consume that view normally.
Never omit the new dividend merely because the old sparse record lacked it.
Classification evidence remains attributable to immutable publication hashes;
no source row, old observation, plan, command or canonical checkpoint is edited.

This change does not broaden economic extraction of stale retained targets.
If a correction falls inside a carried target's retained interval, that existing
material-history guard may still refuse the carry. The observed October 20
correction precedes the current October 30 decision; it does not require changing
that guard. Supporting other carry intervals requires a separate design.

Broker credit and market-data publication are independent knowledge streams.
Native broker `DIV` activity may precede or follow market-data knowledge. Real
broker cash remains authoritative and is reconciled by native activity identity;
source knowledge cannot create broker cash or a second credit. A data-first
entitlement is not proof of payment. No broker activity enters Wealth Core or the
controller. Alpaca PAPER's missing dividend simulation remains a visible
performance limitation, not synthetic broker cash or a permanent share-trading
latch.

## Scoped preflight and preparation

Restore the existing [security-scoped recovery contract](automatic-share-unit-reconciliation.md)
for fresh cycles as well as already prepared plans. Add a distinct
`READY_TO_PREPARE` callback disposition for current-generation, planless
preflight only. Require a complete account-bound transport observation with a
durable transport reconciliation identity, no foreign activity, no unresolved
command outcome and no in-flight command. Scoped restrictions remain in the
diagnostic and `last_clean_reconciliation_id` remains absent.

Only preflight may consume this disposition to advance data refresh and plan
preparation. Preparation retains its existing account, sizing, source, envelope
and durable-plan guards while accepting complete transport readiness with
security-scoped restrictions. The executor repeats restrictions under its own
writer lock; affected securities remain deferred and deferred reductions never
fund dependent purchases. A restricted result cannot declare execution success,
clean convergence or verified PAPER performance.

Use the callback's actual completion time. An expired/stale obligation or a
callback completing at or after its original opening cutover is superseded
before publication/preparation. Old-generation recovery never earns this
disposition. UNKNOWN outcomes retain priority. Never replay a stale plan or
create late opening buys.

Corporate-action waits are not generic REFRESH/PREPARE source-availability
retries. Preserve the existing bounded retry policy and report the actual
restriction rather than claiming malformed source-availability evidence.

## Qualification and delivery

Replay the exact DELL sparse evidence in private tests, plus cash-before-data
and data-before-cash, duplicate/restart, current/former/zero ex-date ownership,
missing/tampered publication links, wrong identity, changed/deleted cash terms
and structural/mixed corrections. Remove cash/identity/structural guards to
prove negative oracles fail. Exercise fresh and retried preflight, actual-open
crossing, old generations, UNKNOWN/foreign/incomplete observations, restricted
transport and funding dependencies. No `tests/wealth_core` or backtest resources
are involved.

Keep economic compiler bytes and frozen historical baselines unchanged. Update
only actual runtime source commitments and the precise execution delta evidence
required by changed files. Deliver through a separate PR from Ubuntu migration.
Local qualification and PR publication do not claim production activation or
resolution of the running account's incident.
