# Authority polling during dataset contention

Decision: 2026-10-11. The installed waiting cycle was blocked when the snapshot
reader raised `CorpusLockUnavailable` during publication or retirement. The
authority adapter promoted that expected availability exception to permanent
integrity failure and the notification path engaged the kill switch.

Authority checks use the existing reviewed dependency classifier. Only its
explicit temporary exceptions may retry. A failed lock acquisition is not proof
that a certificate or book is invalid, and must not persist a negative authority
verdict. It also cannot produce a positive verdict, authorize a broker call or
renew a proof clock. The transaction rolls back and the idle control poll returns
to its existing finite control-poll interval. Callback paths retain their
original retry/exhaustion and immutable trading-window boundaries.

Actual signature, identity, configuration, lineage and ownership failures remain
permanent. Stale leaders return to the existing scheduler without renewing their
fence. Unknown programming defects remain visible. Do not unwrap an integrity
exception merely because its cause happens to be a timeout or lock conflict.

Qualification holds an actual opposing corpus advisory lock on another
PostgreSQL session while the production authority/control-poll adapter runs.
The same waiting cycle, control generation and plan must survive; no broker,
kill, terminal transition or authority verdict is produced during the conflict.
After lock release the complete authority gate must run again and may publish
PASS only on success. Permanent revocation and missing lock ownership must still
block. The source-admission catalog pins the exact installed and final runtime
bytes and qualification preserves the already formed book.

This repair does not undo an already latched production failure. That evidence
remains retained; recovery requires the supported exact certified upgrade and
separately authorized activation, preserving the book and financial journal.
