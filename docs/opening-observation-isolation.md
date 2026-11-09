# Opening execution and independent observation

Decision 2026-11-09, before implementation. The retained 14:20–14:45Z
passive trace and durable command/cycle records establish:

- EXECUTING began 14:31:00; the sole SELL command was minted 14:35:02.
  RECONCILING began 14:35:17 and SUCCEEDED at 14:37:55. There is no failed
  transport in that durable transition: it records one submitted command and
  COMMANDS_IN_FLIGHT. Fill observation time is not the broker's fill time.
- A warm execution proof waited 40 seconds on the snapshot admission held by
  a verifier. Admission currently precedes even callback-private cache lookup.
  Recovery has no corresponding writer/publication-scoped structural reuse.
- Operational publishers wait on FOR SHARE revision rows updated by financial
  transactions. These rows are invalidation tokens, not financial ownership.
  Holding the verifier owner while waiting delays all display publication.
- Historical transition detail stores next_wake_at as JSON text. The transport
  projection passes it to a datetime-only submitted-command predicate, falsely
  declaring the observed successful submission interrupted.
- PAPER verification and HTTP projection use statement-level snapshots across
  multiple related reads. Independent commits can mix mirror/index facts or a
  dashboard receipt with a newer review head. SHADOW verification already uses
  a coherent committed snapshot.

Use repeatable-read read-only transactions for these owned observation paths.
Continue before/after subject checks on financial verification, receipt MACs,
original expiry and independent review/negative precedence. Publication protects
revision-row existence with FOR KEY SHARE; non-key revision increments remain
free to commit. Immutable incarnation plus versions and consumption-time subject
checks withdraw changed financial payloads. No display lock may serialize a
broker command or extend financial authority.

Look up callback-private verified structural material before acquiring the
global heavy-scan resource slot. A cache-only miss has one typed outcome and
re-enters the original admitted cold path; it cannot silently execute a heavy
load outside admission. Preserve writer ownership, publication pin, native row
versions, fresh readiness, authority, broker and clock checks. Add the same scope
to rolling dual recovery under its existing writer lock and publication pin.
Reuse that same pin for the mirror check; legacy recovery keeps its original
conditional pin. Share no
proof across callbacks or processes, and never store a GO verdict.

Normalize only the historical event timestamp through the existing strict aware
timestamp parser before the existing submitted-command predicate. UNKNOWN,
uncertain, foreign, failed and malformed evidence retain their failure behavior.
Ordinary EXECUTING/RECONCILING visibility is not permission to hide a negative
broker or financial observation. Preserve all incident history.

Qualification must include actual PostgreSQL revision-update concurrency,
repeatable observation across a concurrent commit, warm-cache admission bypass,
invalidated-cache cold admission, lost writer/pin refusal and JSON transition
replay. Omission falsifiers must exercise the guards. Reuse the protected
economic implementation and the prior qualified backup/maintenance policy.

The passive trace records lower bounds on repeated statements, not every short
query. Its seven HTTP errors lack response bodies/status and cannot establish
seven independent server exceptions. The 18 filtered log signals are 12 shadow
workflow lines and six Pydantic field-name warnings, not 18 execution failures.
Keep those limitations explicit; do not manufacture missing historical causes.

Additional forensic decision, before its implementation: reconstructing the
bounded NEGATIVE_RESULT material exactly matches both PAPER fingerprints to
`historical mirror warning remains recorded; current scheduled readiness is
unproved · cycle RECONCILING`. The historical-warning dispatcher admits only
WAITING_OPEN and SUCCEEDED, so ordinary in-flight transport falls through to a
false current mismatch. Coherent snapshots remain a separate verified defect.

Add a bounded in-progress historical-warning projection for EXECUTING and
RECONCILING. Require the current bound local account, healthy enabled leader and
current authority, exact cycle/run/plan/publication/session identity, original
execution window, known native command states and complete coverage of outstanding
commands. RECONCILING additionally requires the existing positive submitted-command
predicate. Bound progress by the original next wake or an actually active,
current-fence callback's original deadline; a due wake is not a stalled callback.
Uncertain, rejected, foreign, failed,
expired or unproved progress keeps the existing refusal. Display PENDING with
the historical count and original bounded progress deadline; never call it
completed, reconciled, clean or verified. A pending transport warning remains
visible; this does not change the human-health or financial-admission policy.
