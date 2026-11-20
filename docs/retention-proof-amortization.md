# Reuse checkpoint authentication during private retention

The November 20 trace observed the private retention worker authenticate the
cold-start and daily strategy checkpoints for each deletion of up to 128
obsolete acquisition prices. A read-only profile attributed 2.29 seconds
of wall time and 1.58 CPU seconds to each authentication, including archived
input decompression and canonical serialization. The durable maintenance
cursor showed real progress.

Private acquisition retention may repeat at most eight existing acquisition
steps in one owned transaction. Each step keeps the 128-row select/delete
limit and independently checks candidate eligibility, row ownership and
database delete guards. The caller's row limit also caps the combined work in
the pass. A private pass retains its existing backup admission, lock set,
opening exclusion, five-second pass deadline, publication reserve and
single 500-millisecond class window after checkpoint proof. Repeated steps
share the remaining class window. They cannot obtain another time allocation
or renew an authorization.

The transaction must authenticate the full checkpoints before its first
positive mutation. Multiple steps may use that proof under the same locks and
transaction. Keep each step in its own savepoint so a cancelled or late step
rolls back its deletion and preserves earlier successful steps. Publish the
combined counts, cursor and data changes in the same commit. The existing
candidate cursor still yields after a bounded per-part burst. Stop the private
pass at the first failed or progress-only step so traversal does not consume
the unused batch budget. Other work classes keep their own passes under the
existing rotation, and each new private pass checks admission and
authenticates again.

Qualify using real PostgreSQL under the private acquisition lock set. Assert
several bounded deletions per authentication, caller and pass row caps,
original deadline reuse, rollback of a late batch, cursor fairness across
classes and no authentication reuse after commit. Use work counts so the
regression does not depend on the host's CPU speed.
