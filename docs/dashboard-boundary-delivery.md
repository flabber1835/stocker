# Display continuity across evidence boundaries

Decision 2026-11-09, before implementation. The seven opening HTTP failures
include two short workflow-boundary gaps and five publication-contention gaps.
The prior patch removes incompatible revision locking. The remaining defect is
the use of the earliest individual fact deadline as the lifetime of every panel
and of the HTTP document itself. An account or workflow transition can therefore
withdraw an independently current canonical book and prevent rendering a dated
account, even though authenticated unchanged inputs remain available.

Keep strict snapshot encoding and decoding, original row/receipt/recovery
deadlines, financial scope verification and machine readiness unchanged. Add an
explicit display-only consumption mode to the same owned, repeatable-read HTTP
transaction. Authenticate and validate the original signed snapshot exactly
once at its original generation time, then enforce its existing maximum
observation window: generation <= actual database time < generation + 30 seconds.
This is not a renewed expiry, a new TTL or permission to consume the snapshot
as current financial evidence. Wrong context/owner/account/image, bad signatures,
malformed shape, future clocks and an exhausted observation window still refuse.

The display consumer uses actual database time to derive per-row currentness.
For a retained envelope, a known positive row needs its own finite unexpired
boundary and unchanged scope. Expired positives and unclassified/unbounded
positives lose current styling and executable-looking JSON payloads. Preserve
explicit authenticated negative rows. Fresh SHADOW/PAPER receipt replacements
continue to take precedence over retained facts, including current negatives.
Keep the before/after expiry check inside the same original display window.

A changed authenticated review head also withdraws current observation and ACK
eligibility. If current signed review state contains active conditions, expose
a current negative source condition immediately; never turn a newly recorded
incident into a neutral retained page. A display projection cannot acknowledge,
record recovery, start a verification worker, hash a corpus or contact a broker.

Expose consumer-only retained/generation metadata. Signed producer snapshots
must contain only its empty defaults. Strict callers keep the existing reader;
only the human HTTP display opts into retained consumption. Partial delivery
keeps machine operational status UNKNOWN and /operational-health HTTP 503.
Acknowledgement continues to require a strict current view and unchanged token.

Render affected overview cards as last known only when their original payload
was eligible at the authenticated generation time. Keep original evidence
timestamps and mark the card non-current; do not modify its financial row or
serialize it as current JSON. Unaffected panels remain independently current.
Re-evaluating these clocks and fresh invalidation subjects avoids rebuilding
unchanged verified financial inputs during a short phase transition. The
existing asynchronous producer remains the sole owner of new collection and
incident publication; no extra service, polling loop or request-triggered work
is introduced.

Qualify exact expiry, clock crossing during a read, exhausted retention, malformed
consumer metadata, negative precedence, changed review head, source/owner changes,
read-only repeatable-read transactions, concurrent updates and ACK refusal. Use
the captured opening timestamps and executed omission falsifiers. Preserve the
canonical book, command journal, independent maintenance process and PAPER-only
execution contract. Deliver through the owner-authorized local patch workflow.
