# November 24 close: verified work and bounded optimization

The November 24 PAPER close published source version 29 at 21:13:53 UTC,
advanced its rolling shadow cursor at 21:16:25, and prepared the next plan by
21:21:50. The plan and financial authority were preserved. This note separates
work proved redundant from costs that still need attribution.

## Expected-key traversal

The Alpaca candidate builder materializes approximately 1.6 million expected
`(session, security_id)` keys in a temporary table. Its primary key currently
uses the database's default `en_US.utf8` text collation, while sealing reads
the keys in `security_id COLLATE "C"` order. Those are different index orders.
Read-only `EXPLAIN` on the PAPER database confirmed the same mismatch on the
retained acquisition-price index: the explicit `C` order requires an
incremental sort, whereas its native order uses an index-only scan. This proves
an avoidable sort in the expected-key traversal; PostgreSQL's retained
database-wide counters cannot attribute either observed approximately 504 MB
temporary-file burst to this query.

Define the temporary expected-key table's `security_id` column with `C`
collation, so its existing primary key can supply the sealing query's exact
bytewise order. Keep the provider-derived key set, duplicate rejection,
canonical `C` output order, candidate validation, content hashes, and
publication checks unchanged. Do not raise database memory limits or change
the workload's financial scope. Qualify on a private PostgreSQL cluster whose
default collation differs from `C`: check the unforced plan, exact ordered keys
and sealed manifest parity, and make the plan witness fail when the collation is
removed.

The builder participates in the retained economic source identity even though
this change affects only the temporary index order. Retain the installed
economic identity only for the one reviewed, exact source transition after
tests prove identical ordered keys and sealed content. Keep dependency and
source closure checks, preserve every earlier reviewed transition, and let an
unknown builder revision acquire its actual new identity and fail ordinary
compatibility checks. This optimization grants no new PAPER or LIVE authority.

## Other close work

The first approximately 32-second automation preflight failed while acquiring
a source publication pin, before a broker adapter was constructed. Its retry
performed the sole required pre-publication broker reconciliation, completing
observation 623 at 21:01:06 UTC. There is no duplicate broker reconciliation to
remove.

One full independent SHADOW dashboard scan became stale when the rolling
shadow cursor committed. The next scan admitted at 21:16:43 and completed at
21:17:44. The exact first admission time was not retained, so a change to
verification scheduling is deferred until its timing and current-proof state
can be established. In particular, a completed check for source version 29
must not be reused after the cursor changes its subject.

The approximately 504 MB PostgreSQL temp-file bursts were bounded and did not
continue after publication. The retained counter is cumulative for the entire
database. With per-query temporary-file logging disabled, neither burst can
be assigned to a particular statement. A future close trace must correlate
query identity and backend with per-query temporary bytes before another
spill-specific change is selected.
