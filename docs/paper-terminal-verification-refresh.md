# PAPER verification after a terminal cycle block

The November 12 close trace saw 38 failed PAPER observations across nine
verification subjects while the same closed cycle remained blocked. Eleven
observations used one unchanged subject. The reader schedules all negatives
using its 30-second retry interval. Each observation of this exact terminal
cycle produced the same negative row and another attempt record.

The current PAPER result may carry the typed `BLOCKED` fact when its producer
observed a durable terminal blocked cycle. Keep the original failed row, signed
subject, attempt, and receipt clocks. The background verifier refreshes that
single scoped result at the existing 300-second periodic refresh age while the
exact subject remains current and its original receipt is still fresh. The
negative remains visible and cannot establish readiness or be acknowledged
into health. Exact subject movement re-enters the ordinary admission path.
An expired result, unreadable identity, transient error, unknown observation,
and any other negative retain their existing retry and refusal behavior.

Use the existing typed row serialization and verifier owner. Only the current
PAPER result whose validated row was a durable `BLOCKED` cycle is eligible.
An old result carried across a subject change remains dated evidence and cannot
defer work for the new subject. Read the current subject on every iteration and
recheck it before publishing. Keep the original queue, work, supersession,
receipt, and diagnostic clocks and the existing owner checks.

The open trace separately recorded a 12.2-second snapshot admission wait behind
the strategy worker and a 72-second recovery admission wait behind the
verifier. At the close, preparation waited 32.2 seconds for the verifier after
publication and its subject changed. The scan slot remains exclusive. The
signed SHADOW display result lacks the execution reader's full authenticated
state and publication commitments. Keep required new-subject scans and measure
their owners and durations independently of SQL execution. No proof or backup
deadline changes are selected here.

Qualify the original signed failure and clocks, exact same-subject refresh
boundary, subject change and nonterminal or unreadable failures. Remove the
terminal refresh restriction in an isolated test to show that repeated work
returns. Preserve the existing owner, retry, and supersession tests.
