# November 27 closing resource ownership

Historical signal anchors belong to exact candidate, security and session triples.
On shared block storage the reader groups the requested securities by session,
selects that candidate's daily blocks, then extracts matching rows. An anchor
must still have its signal price. Legacy row storage continues to use its
indexed join. Compare both paths with the logical view on the same immutable
data and count block expansions and temporary writes in private PostgreSQL.

The closing refresh can wait briefly for the current session's missing
attestation using the authenticated predecessor and a current publisher and
worker. This scheduling observation grants no verification or execution
authority. It must expire with the original publication, worker and exchange
deadlines, and fall back to ordinary verification on changed or incomplete
evidence. A separate recheck time caps accumulated retry backoff at the hint
expiry. Original publisher and worker deadlines remain independently visible.
Completion always follows the canonical verification path.

Financial callbacks have priority over independent display verification when
both require the same snapshot slot. A background observation waiting for that
slot must yield without holding a snapshot or writer lock. Its original work
deadline and the clocks on any displayed evidence still apply.

A display worker that yields to a foreground database owner hands its
allocation back to the verifier immediately. The worker reports a typed
scheduling outcome across the process boundary. The parent may retain a
completed proof for the identical subject only through its original expiry.
Otherwise it publishes a dated verification-in-progress row while it waits to
retry. All attempts in that wait share the first admission's absolute deadline
and remaining work budget. A genuine SQL timeout, worker failure, expired
budget or regressing clock remains visible. Only a completed verification can
clear a recorded failure. The database writer does not wait for the display.
After a verifier restart, an authenticated checking receipt for the current
subject can only shorten the replacement attempt's waiting indication. A new
worker must acquire the slot and measure the current subject independently.

The full automation authority check uses the authenticated control row returned
by the database-time leadership fence. Both operations formerly replayed the
same control history in succession. The signed authority check, revocation
checks, financial callback fences and idle recheck interval still apply.
Each idle poll also reads the current lease and enabled generation together
using the database clock. This permits the short-lived prior attestation to
use that same observation without another complete control-history replay.

The price provider can revise history. In the November 27 trace all thirteen
complete, date-matched monthly responses also contained different row counts
from the preceding publication. Each request uses the new closing date as
Alpaca's symbol-mapping as-of date. The selected securities and action-based
history floors also participate in the acquisition identity.
Reuse of a stored monthly response based solely on its date range would publish
different inputs. Content-addressed block reuse remains subject to the
canonical source, security mapping, corporate actions and normalization.

Publication 31 and its predecessor, 30, share 299 sessions. All 299 daily
stock blocks have different content hashes. All 299 benchmark blocks have
identical hashes and share storage. Carrying forward a complete prior daily
stock block would have changed the result for every overlapping session.

The backup-maintenance journal also explains a separate burst of database
file reads during normalization. The 10:10 Pacific pass verified newly archived
WAL in two passes, recording 68 hash operations, and deferred discretionary
maintenance while the close was active. Both passes belong to the restore
contract. The database sampler alone could not identify the individual files.

Before acquisition, the strategy worker authenticates the predecessor's cold
origin, daily checkpoint and corresponding archived input. Within one committed
proof, repeated requests can reuse the two authenticated checkpoint payloads
while they fit the shared 64 MiB buffer. A different proof must read them anew.
The early-close sampler did not record the names or parameters of the individual
cursor reads. Its bytes cannot be assigned to either checkpoint.

Choosing the length of the next price window needs only to know whether a
lineage exists. The canonical origin's primary key is sufficient to choose
the ordinary window. In its absence, inspect all original lineage predicates
and retain the existing freshness checks before choosing a formation window.
This routing decision grants no financial authority.

## Private qualification

On a synthetic packed history of 300 sessions and 5,300 securities, the prior
and revised SQL both returned the same 5,000 requested marks across 62 dates.
PostgreSQL EXPLAIN ANALYZE with a 4 MiB work_mem reported 300 expanded blocks
and 30,665 temporary 8 KiB blocks written by the prior query. The revised
query expanded the requested 62 blocks and wrote zero temporary blocks.
Warm execution was 6.12 and 1.25 seconds respectively on this fixture.

In a separate private PostgreSQL fixture, one origin row shared a table with
2,500 unrelated out-of-line JSON documents. The original window-selection
query and the primary-key probe both found the lineage. The former performed
a sequential scan with 17,875 buffer visits. The latter used an index-only
scan with three buffer visits. These counts include pages in cache.

The private closing worker also advanced a real, signed daily fixture to the
point where it would acquire the following session. It loaded and authenticated
the cold and daily checkpoints once each and fetched the daily input archive
once. Both checkpoints fitted the buffer. Disabling reuse caused another cold
checkpoint load and authentication. The original Friday sampling did not
measure checkpoint serialization sizes or buffer admission.
