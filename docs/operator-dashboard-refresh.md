# Operator dashboard refresh and inspection

The panel must distinguish a normal bounded refresh from unreadable evidence,
and identify the producer of each fact. This change is presentation and
operational evidence only; it does not change strategy decisions, execution,
historical cycles, or broker authority.

## Financial observation

Validate the observer's original timestamp against its completion timestamp.
A successful answer that sat unconsumed while the UI was idle may expire before
the next request. Expiry withdraws its green status and starts the existing
bounded refresh, showing amber and dated last-known metrics. It is not a
malformed observation. A result already stale or future-dated when completed,
malformed payload, timeout, or known negative result remains a failure. Neither
consumption nor polling renews the original proof clock. Refresh still starts
after 300 seconds of a 600-second proof lifetime whenever requests are active.

## Backup maintenance

The existing append-only backup evidence relation gains `MAINTENANCE_PROGRESS`.
The host maintenance owner publishes a fixed invocation deadline, immutable
runtime image, database identity, predecessor base, exact selected successor,
and phase before renewal/restore work. Phase updates retain the original
deadline. Completion and failure close the attempt. The panel can show amber
only for a current, identity-bound transition from the proven predecessor
chain to that exact successor while its semantic restore and runtime chain
are being checked. It cannot excuse a foreign cluster, arbitrary mismatch,
malformed proof, missing predecessor proof, failed phase, or expired deadline.
Progress is never restore proof and never changes an execution gate.
The immutable image must match the panel's installed image digest. A transition
cannot hide a future-dated backup or an expired base objective. Its original
budget includes the coordinator's prerequisite work, using elapsed monotonic
time and the primary's clock; phase publication cannot start a new hour.
The explicit schema installer migrates only the exact preceding operational
catalog while automation is fenced. Routine runtime validation performs no
DDL. The migration preserves all rows and control generations. A database
trigger makes progress records append-only and keeps each attempt's original
identity and deadline immutable across its ordered phases.
Installation must create a fresh base and complete its semantic restore with
the new image after the catalog migration, before restarting recurring
maintenance or releasing paper automation. An older physical backup still
contains the previous catalog; it is not evidence for the new image's schema.

## Acquisition and cycle wording

Reviewed operational mode reads the latest operational snapshot job, including
publication state and progress, rather than the legacy ingest-run table. An
unreadable job is unknown; no fallback invents a successful ingest. Legacy
mode retains its existing source. A current generation without a cycle says it
is waiting for its next eligible decision. A previous terminal cycle remains
visible as a cycle failure, without claiming that broker positions mismatched.
Actual reconciliation mismatches retain their existing red status.

## Canonical holdings

The already verified canonical session supplies a bounded holdings projection
on the book row: security identity, ticker, held quantity, canonical raw close,
value, weight, cash, and session. Pending operations are identified separately;
they are not counted as filled holdings. Missing marks remain unavailable,
never zero or invented broker quotes. The full canonical state never crosses
the observer pipe. The bounded payload limit increases to 32 KiB, with at most
100 held securities and strict field validation. Holdings disappear when the
book proof is unavailable or expires. The expandable view explains that the
Wealth Core book is the unscaled stock-selection book, whereas simulated
strategy value is the controller's strategy ledger including its cash/T-bill
sleeve. Neither is the Alpaca account balance. Repeated page refresh preserves
the operator's expanded detail panels.
Display decimals are finite and bounded to 19 integer digits and 30 fractional
places. Holdings arithmetic is exact Decimal arithmetic; comparison with the
existing floating-point estimated book value permits only a two-cent residual.

## Qualification

Focused tests cover idle answer consumption, stale/future/malformed answers,
backup transition identity/deadline falsifiers, operational acquisition reads,
canonical holdings arithmetic and escaping, and historical cycle wording.
Retained data is inspected read-only in an isolated candidate process. Exact
runtime source admission hashes must include the predecessor and candidate
bytes; no broad source substitution or financial-state reset is permitted.
