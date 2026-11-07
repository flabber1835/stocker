# Drain polling with a retained older acknowledgement

Observed on2026-11-06: a valid new drain request was written for the current
shadow incarnation while the transient ACK file still held a genuine earlier
operation's acknowledgement. `poll()` treated that older identity as a refusal
before the worker reached its next admission boundary. The worker subsequently
wrote a genuine matching acknowledgement without a restart. The first delivery
attempt remained at DRAIN_REQUESTED and expired during its separate review.
The fresh operation retained all original financial gates and completed after
an explicitly bounded read-only wait for matching evidence.

Decision before implementation: polling may report **pending** for a genuinely
authenticated, well-formed, strictly older acknowledgement. It never accepts
that acknowledgement as proof for the current request. Keep strict direct
`acknowledged()` semantics, original600-second request lifetime,180-second
remaining-time guard and all source/incarnation/quiescence checks. No deletion,
renewal, new clock, automatic operation retry or history acknowledgement occurs.

Take the poll's current-status/request/ACK decision under the same admission
file lock as request creation and worker admission. Factor the existing strict
acknowledgement reader into an internal lock-held function. Direct callers
remain strict; only polling selects the pending-prior mode. Before pending is
allowed, require the current request still exactly installed, live and bound
to the fresh current IDLE incarnation, with no pending/critical worker markers.
The prior ACK must have the exact DRAINED schema/shape, an authenticated embedded
DRAIN request and its matching digest, valid bounded UTC request clocks,
requested_at strictly before the current request, and quiescent_at inside its
own live interval and no later than now. A changed binding/incarnation on that
older proof is permissible only as pending evidence, since it grants no current
authority. Malformed, forged, future or same-request mismatches still refuse.

Preserve the old ACK bytes until ordinary worker admission replaces them. The
new matching ACK must pass the unchanged full strict predicate before any
delivery stop or start. Re-read under the admission lock; returning pending
never permits work or grants deployment authority. Tests must reproduce the
observed two-operation case, prove old bytes/clocks remain unchanged, admit
only the later genuine matching ACK, reject malformed/authentication/clock and
quiescence failures, and execute falsifiers for the new prior-proof and lock
guards. The canonical book, command journal and broker authority are untouched.

This fixes release coordination. The separately installed lineage index fixes
the expensive verifier negative scan; this polling change does not claim to
explain the transient cold-start operational publisher timeout.

The current67458b207 runtime must remain a valid exact financial predecessor.
Add its complete453-module closuref4eaa5729cee9c2ce5794e4fa334c945dbf2ab2cadd55a77aa35a8b1abe61121
to the source compatibility profile, preserve all eleven earlier predecessor
maps byte-for-byte, and seal the complete new source after the poller changes.
The profile version advances to12; this is a source-identity edge with authority
NONE, not a change to strategy, book, catalogue, execution-envelope or finance.
