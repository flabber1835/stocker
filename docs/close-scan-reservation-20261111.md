# Close verification work scheduling

The November 11 trace recorded one SHADOW scan waiting through the first 17
seconds of close and two PAPER preparation scans waiting about 95 seconds in
total. A background verifier held the existing heavy snapshot slot in each
case. The slot bounds simultaneous cold work and stays in place.

Extend the existing opening reservation for optional SHADOW refresh to two
bounded close periods. A completed current-generation cycle on the exact
effective exchange session can reserve the slot from 90 seconds before its
stored close until 60 seconds after it. Once the current decision cycle owns
an active preflight, refresh, or preparation callback, reserve only up to that
invocation's original deadline and the next execution open. The active
callback must match its durable state and current fence, have a fresh heartbeat,
and start after the cycle enters that state. Require current approved control,
exact binding, and a live lease in both cases. A settled older cycle may retain
its historical fence. These periods only defer a new optional verifier scan.

Use the verifier's existing same-subject positive-result checks and original
renewal cutoff. A new subject, missing proof, failure, or result nearing expiry
refreshes normally. A running verifier scan completes under its existing
deadline. Keep PAPER observation, receipts, and operational publication active.
The reservation adds no financial evidence, shared proof, lock, or authority.

Validate the exact close boundary, early-close timing from stored schedules,
active callback state and deadline, stale heartbeat, lost fence or lease, and
wrong session. Exercise exact-subject positive renewal deferral alongside the
existing opening tests. The next captured close can measure remaining lock
waits without inferring speedup from a unit test.
