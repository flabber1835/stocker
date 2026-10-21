# Explicit protected PAPER debug window

Decision: 2026-10-21. The owner authorizes same-day paper orders after the normal
opening cutoff to diagnose the actual production path without waiting another
session. This supersedes only the time restriction in the missed-open policy
and anytime-activation cutover for the explicit window below. It grants no live
trading, old-session replay, provider access or financial readiness.

## One signed session and one finite window

Add an optional PAPER_DEBUG_WINDOW_V1 document to canonical automation policy,
loaded from literal SENTINEL_PAPER_DEBUG_WINDOW JSON. It names one exact effective
XNYS session and aware whole-second not_before/not_after instants wholly inside its real
regular session, with at most 30 minutes between them. Operators choose actual
future times; clocks, the session open and the exchange calendar remain real.
The complete document participates in the automation configuration fingerprint
and signed activation authority. An absent document preserves the existing
configuration fingerprint and 09:31–09:40 ET protected submission behavior.

Selection requires PROTECTED_LIMIT_DAY_V1 with the already approved cap of
exactly 100 basis points. The protected projection also commits the complete
debug window and its actual open-relative start/cutoff seconds. Its persisted
policy, current configuration and final guard must agree. Authenticated prior
RAW close, whole-share rounding, fixed LIMIT/DAY terms, per-security allocation,
maximum-cost cash reservations and long-only unlevered guards remain unchanged.
No live quote or SIP entitlement is introduced.

## Fresh obligation, ordinary ownership and recovery

For the named session, the scheduler retains actual execution_open_at and uses
not_before as execute_at and not_after as the last new-submission boundary.
A clean preflight first reached after the real open may proceed only for this
exact current signed configuration while the explicit window has not expired.
All ordinary data, authority, book, backup, certificate, leader and reconciliation
gates still apply. Preparing during a valid explicit window is permitted;
execution must still occur before its end.

Existing pre-transport predecessor replacement keeps its exact binding,
generation, lineage and negative transport proofs. Only its prospective clock
boundary may use the explicit window end. A prior SUPERSEDED
DISCOVERED_AFTER_SESSION_OPEN cutover may also be replaced only for the exact
same current effective session, with no plan, both native clean-preflight
terminal flags, and the unchanged negative event/command transport proofs.
Its fresh genesis retains the complete debug configuration whose digest must
match the new cycle's signed configuration. Lineage readers reconstruct and
verify that subject and every eligible predecessor; a free-text terminal reason
cannot authorize replacement. BLOCKED cycles retain their existing reviewed
recovery rules; non-retired, historical or possibly transported predecessors
still refuse.
No immutable prior cycle, command, marker, publication or book is edited. Fresh
preparation under current authority must name the actual latest closed decision
and its following effective session; Monday/Tuesday plans cannot be replayed.

The final canonical broker guard rechecks the matching authenticated policy and
actual broker clock immediately before every BUY POST, after awaited authority
and funding work. It refuses at exact not_after, on another session, on a changed
configuration, or with market/unprotected BUY terms. An ordinary manual grant
cannot consume the debug window; the production dual automation membrane owns it.

At expiry, new submissions stop. Existing attributable DAY orders may remain
working until their normal market-close lifetime; UNKNOWN outcomes and recovery
retain the ordinary rules and command identities. The setting is session-bound;
clearing it or selecting another session requires fresh canonical signed
activation, not a daily source change or direct database edit.

## Delivery and focused proof

Preserve prior source profiles verbatim and admit only exact reviewed successor
bytes, including the scheduling/transport modules newly in this bounded profile.
No retained receipt is relabeled and no source overlay is a qualified runtime.
Test default identity/window preservation, actual exchange/early-close bounds,
current-session scheduling, late clean preflight, strict predecessor ownership,
final POST after slow awaited work, policy/projection mismatch and expiry. Guard
removal must fail its boundary and lineage falsifiers. Run the relevant native
scheduler and execution tests; do not run unrelated Wealth Core tests.
Signed CI, the exact new image and supported installation/activation remain
required. This change alone neither activates automation nor submits an order.

The successor extends the protected source scope from 23 to 29 modules, adding
`automation/schedule.py`, `automation/store.py`, `automation/integrity.py`,
`execution/guarded.py`,
`execution/protected_limits.py` and `paper/validation.py`. Each added baseline
hash comes from genuine `52b2bd7b` source bytes. Preserve the full f295a701
predecessor profile verbatim. Existing full-manifest witness SHA/revision pins
stay unchanged; extend only their projections with the actual new path hashes
read from those same authenticated fixture manifests. Existing projected entries
and retained financial history remain unchanged.
