"""delta_intents approval marker — durable enqueue for the single-consumer drain

Revision ID: 0033
Revises: 0032

Trader flakiness root-cause fix (see docs/architecture.md "Design Decision:
approval = durable enqueue + single-consumer drain"). Approval moves from N
synchronous size->risk->submit RPCs (which serialized on a per-account advisory
lock held across the risk HTTP call, causing lock timeouts on large rotations) to
a durable marker on delta_intents drained by a single background worker.

Columns added to delta_intents:
  - approved_at           TIMESTAMPTZ  — set when a human (or cron) greenlights the
                                         intent. NULL = not approved. The durable
                                         enqueue: persisted before any risk/broker
                                         work, so a browser refresh can't strand it.
  - approval_mode         VARCHAR(16)  — 'immediate' | 'scheduled' (passed to the
                                         per-intent orchestration verbatim).
  - approval_processed_at TIMESTAMPTZ  — stamped by the worker AFTER it has
                                         processed this approval. NULL (or < the
                                         latest approved_at) = still to process.
                                         Prevents reprocessing loops; a re-approval
                                         sets approved_at afresh (> processed_at)
                                         so the worker runs it exactly once more.

Partial index supports the worker's hot scan ("approved & not-yet-processed").
Backwards compatible (all-NULL on existing rows = "never approved") and idempotent.
"""
from alembic import op

revision = "0033"
down_revision = "0032"


def upgrade() -> None:
    op.execute("ALTER TABLE delta_intents ADD COLUMN IF NOT EXISTS approved_at TIMESTAMPTZ")
    op.execute("ALTER TABLE delta_intents ADD COLUMN IF NOT EXISTS approval_mode VARCHAR(16)")
    op.execute("ALTER TABLE delta_intents ADD COLUMN IF NOT EXISTS approval_processed_at TIMESTAMPTZ")
    # Worker scan: approved intents still awaiting processing. Partial so the index
    # stays tiny (only the transient in-flight approvals), ordered by approved_at.
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_delta_intents_approved_pending "
        "ON delta_intents(approved_at) "
        "WHERE approved_at IS NOT NULL AND approval_processed_at IS NULL"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_delta_intents_approved_pending")
    op.execute("ALTER TABLE delta_intents DROP COLUMN IF EXISTS approval_processed_at")
    op.execute("ALTER TABLE delta_intents DROP COLUMN IF EXISTS approval_mode")
    op.execute("ALTER TABLE delta_intents DROP COLUMN IF EXISTS approved_at")
