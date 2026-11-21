# Bound and reuse idle acquisition retention work

The November 20 trace of protected release `9a3ef0cb` found useful acquisition
cleanup during trading idle. SHADOW used 31 percent of one core over 45 minutes
while the acquisition deletion counter advanced by 297,984 rows. The supervisor
restarted a disposable helper five seconds after each positive pass. The current
database price guard checks the distinct affected parts after each DELETE
statement. The legacy per-row price guard is absent from the supported catalog.

Space new idle retention attempts at least thirty seconds apart after the prior
attempt finishes. Keep that clock in the SHADOW supervisor across normal polls
and worker starts. Its existing dependency deadline, drain admission, opening
exclusion, closing-plan exclusion, lifetime owner, and next-publication reserve
continue to apply. Successful passes still publish committed work and continue
while more work remains. This trades catch-up throughput for a bounded duty
cycle of a background cleanup task. Worker admission and financial scheduling
keep their current clocks.

Within private SHADOW retention only, let the supervisor carry one small result
from a completed helper. Each new transaction reads the current cold and daily
checkpoint rows and the exact compact daily archive in one PostgreSQL statement.
Take fresh SHA-256 digests of their stored JSONB text. Keep the original read
committed isolation and leave checkpoint writers free of new locks from this
optional work. The name, date, physical version and digest of every row, the
receipt-key identity and the database identity bind the result. It carries no checkpoint values,
pin eligibility, a stale view of database rows, or backup admission. Only exact
equality with the prior canonically authenticated bytes can omit another decode,
parse, canonical serialization and HMAC calculation. Use the original full
read on missing or legacy input shapes and on any changed digest. An archive
change alone must miss. Compare the complete witness before and after a full
read so a concurrent replacement cannot seed the next pass. Fresh backup admission,
pin tables, per-step eligibility and delete guards still apply to each write.

Only return a positive result for reuse when the full read agrees with the exact
row witness and the owning pass returned after commit. A killed, failed or
incomplete helper supplies no result. The slot closes with the owner and uses
no filesystem or database cache. The physical receipt and transaction rules
remain in force for other maintenance and live authority callers.

Qualify with real PostgreSQL and canonical checkpoint readers. Reuse an exact
archive across separate committed passes, replace only archive bytes, change
the signing identity, and exercise concurrent checkpoint replacement. Verify the
rate limit across both routine poll and worker boundaries. Preserve ordinary
guard failures and test the exact installed predecessor edge. Deliver this
owner-authorized application patch with the backed local installer and preserve
the existing PAPER activation across the completed-cycle handoff.
