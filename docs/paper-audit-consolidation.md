# PAPER audit consolidation

Decision following the November 25 audit of the backed PAPER release through
PR 638.

## One classification for a missed buy

The immutable terminal automation event owns the proof that only BUYs were
missed. The notification sender and dashboard consume the same validated
record, including the plan, cycle, generation and exact clean observation.
When an older event predates the recorded proof, the dashboard may reconstruct
it only through the same verifier and original transition facts. An incomplete
proof never establishes a safe miss. The historical order display can still
read the original durable intent and progress.

The dashboard independently proves that the enabled worker has a current path
to the next decision. Check the latest saved broker observation against the
proved holdings and order identities using the same verifier as the terminal
check. A later observation can withdraw current readiness without rewriting
the immutable event or its notification. Preserve operator acknowledgement,
command identity, and the original outcome of the trial.

The exchange-local session date owns the lifetime of the current trading-run
card. A well-formed, already-proved historical retirement becomes ordinary
history when its scheduled display boundary passes. Do not create a review
incident just because a cached snapshot still contains that card. Early expiry,
invalid dates, unexplained order outcomes, and independent current failures
retain their existing operational meaning. Qualification exercises the same
saved snapshot across the boundary and through its eventual removal.

## Verified publication and bounded database reads

Use one authenticated publication pin through same-connection preparation or
execution preflight. The inner gateway may borrow it only while its owning
connection still holds the pin. Direct callers acquire and verify their own pin.
Read the date and measure readiness from the pinned publication. Recompute
time-dependent readiness, and keep independent authority checks at the
existing broker, writer and recovery boundaries. An operation cannot borrow an
expired, foreign, or caller-supplied unverified publication.

The normalized price predecessor reader and rolling strategy window reader use
one physical session iterator for the shared layout. Retain each query's
predicates, canonical row order, work checkpoints, and cursor lifetime.
Qualification compares the resulting ordered facts and avoids the whole-window
sort on shared storage.

## Timed exit qualification

Account and residual cash retain their exact stored decimal representation in
plan readback. A zero balance is a valid input to the plan fingerprint. The
readback must preserve values such as `0.00` through save and restart.

Rehearse an eligible 100% to 0% exit and a 55% to 0% exit using the ordinary
opening boundaries, twenty reductions and the defensive BIL purchase. Run the
opening checks, scheduler, gateway, and command recovery in a private database.
A durable broker simulator may model quotes, cash and order visibility. Lose the
response after the eleventh sale is accepted and restart with the same journal.
Require positive exact-key recovery, at most one accepted submission per
command, and a fresh settled-cash check before the BIL order. Keep the installed
9:31–9:40 exchange-local window. Record the elapsed opening and completion times
and any parts of the run that still use simulated evidence. The rehearsal
supplies no broker or installation authority. LIVE remains forbidden.
