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

## Private qualification

On a synthetic packed history of 300 sessions and 5,300 securities, the prior
and revised SQL both returned the same 5,000 requested marks across 62 dates.
PostgreSQL EXPLAIN ANALYZE with a 4 MiB work_mem reported 300 expanded blocks
and 30,665 temporary 8 KiB blocks written by the prior query. The revised
query expanded the requested 62 blocks and wrote zero temporary blocks.
Warm execution was 6.12 and 1.25 seconds respectively on this fixture.
