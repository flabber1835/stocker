# Complete notification reconstruction once per source event

Decision before implementation, 2026-11-14. The notification sender evaluates
cycle and control history in bounded batches. Keep the existing activation
boundary, first-incident idempotency keys, quiet-close classifier, outbox
payloads, delivery ordering and recipient state. Leave fill, backup and plan
reconstruction on their existing paths. Fill ownership can still change as
command identity is reconciled.

Use a notification-only completion table. A completion identifies the source
family, event sequence and exact PostgreSQL row version, including relation
and file identity. Existing cycle/control event writers append, but the base
catalog does not block all administrator edits. A different row version must
be classified again. Record the existing outbox key with a foreign-key
reference when an alert exists. A quiet close completion has no outbox row.
Keep completed outcomes append-only. Progress never depends on a maximum
allocated sequence or observed timestamp. A lower sequence committed later
remains eligible. Each poll bounds the rows selected for classification in
each stream and selects them in source sequence order.

The dispatcher discovers and materializes before the existing delivery claim.
An outbox row and its completion commit in one transaction, so an interrupted
transaction leaves replayable source work. A duplicate materializer converges
on the same immutable outbox key and completion. Preserve the existing outbox
row when a direct notifier already produced it. An invalid source candidate
fails closed and obtains no completion. The sender claims only committed rows,
and all transport remains outside the materialization transaction. Keep the
existing reconstruction path for unmigrated databases and standalone callers
until guarded installation. Installed-catalog loss or alteration requires the
explicit existing installer validation.

Install the ledger through the quiescent, database-fenced operational extension
installer. It is supplemental notification metadata with its own private
PostgreSQL catalog witness. The original behavioral and financial installation
markers retain their exact contents. Transfer existing authenticated evidence
prefixes across only the reviewed DDL epoch increment. No HTTP path creates the
table and no notification prerequisite is added to native financial writes.
