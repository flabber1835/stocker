# Audit repairs for recovery and bounded work

## Recover the same obligation

An execution or preflight recovery callback inherits the recorded broker retry
time even if a newer decision is due, the leader restarts, or the active control
generation changes. Recover the old journal before forming a new obligation. A
recovery explicitly scheduled for now can still run immediately.
Order outcomes use Alpaca's published lifecycle and exact client-order lookup.
An uncertain submission requires reconciliation before deciding how to proceed.
[Alpaca Trading API order lifecycle](https://docs.alpaca.markets/us/docs/orders-at-alpaca)

An exactly explained pending native debit fee continues bounded observation
through the opening cutoff. Its prior purchase deadline stays in the evidence.
After that deadline, preflight or execution recovery may reconcile and complete
eligible reductions within the original trading session. Purchases remain subject
to the original cutoff and all actual-cash checks. Incomplete, ambiguous, and
unexplained evidence retains its existing refusal policies.

Use the authenticated terminal event to distinguish a clean missed opening from
an active execution stop. Retain failed PAPER trial evidence for review, with a
warning for an authenticated missed window and a critical alert for genuine
verification exceptions. LIVE terminal alerts come from its automation events.
Within one worker lifetime, a terminal state already handled at its exact
revision needs no repeat trial projection. Restart can repair unfinished work.

PAPER and LIVE operational opens acquire one verified publication pin before
the source and current-plan checks and keep it through adapter construction and
the gateway. LIVE still verifies its signed certificate and account evidence
under its own authority contract. The standing PAPER metadata cache has no LIVE
consumer. Exact shadow-state reuse in sizing applies in both modes.

## Resume host transitions after interruption

Record the exact old and intended environment digests for the current request
under the managed writer lock before replacing the environment. After an
interruption either recorded digest may be present. Any other content requires a
new reviewed activation. Existing completed checkpoints remain readable.

The activation coordinator records its exact private attempt directory and
installed-image identity before beginning financial activation. A matching
successful activation receipt can complete that request and restore its public
status after a bounded read-only probe confirms the exact current durable
control. An interruption after receipt publication can engage the emergency
fence. A different generation or killed control requires review before any
re-activation. An unavailable database delays completion without moving control.
The coordinator preserves its existing fence and review gates whenever no
success receipt exists. Previously completed requests remain readable.

For optional USB backup transport, serialize host attach and detach and record
the exact intended filesystem root for each bind before invoking mount. Recovery
can recognize a pending bind only when its observed device, filesystem, source
and root match the recorded identity. Full observed mount ownership replaces the
pending intent after success. The optional service uses the same exact ownership
test to clean up after a failed or interrupted attach. Contradictory or
unrecorded mounts are refused.

## Check one publication once per transaction

Under the MIRROR change-stream lock, each plan's source-material recheck for the
transaction's selected publication runs once. Every authenticated event is still
consumed and counted against the work budget. Separate transactions and new
publication selections derive their own checks. Historical mismatch latching
and the PAPER transport's current-plan verification are independent of this reuse.
