"""validate fk_alpaca_orders_risk + widen the intent-open dedup index

Revision ID: 0023
Revises: 0022

Two safety/audit hardening steps that pair with the trade-executor / risk-service
fixes in the same change:

1. VALIDATE fk_alpaca_orders_risk.
   alpaca_orders.risk_check_id is the FK into risk_decisions(decision_id) — the
   audit guarantee "which risk decision approved/rejected this order?". The FK was
   created NOT VALID in migration 0001, so Postgres enforces it for NEW rows but
   never checked the rows that already existed and, crucially, lets the planner
   skip it. Now that the executor refuses to record a fabricated/dangling
   risk_check_id (it treats "approved but no check_id" as a hard failure), the
   data is clean enough to VALIDATE the constraint, making the audit link a hard,
   fully-enforced invariant. VALIDATE is idempotent in effect (re-validating an
   already-valid constraint is a no-op) and guarded so a fresh DB created from
   init.sql (where the constraint may already be valid or named differently) does
   not error.

2. Widen idx_alpaca_orders_intent_open to the full working-status set.
   The partial unique index that stops two open orders for the same intent only
   covered ('pending','submitted','deferred'). alpaca-sync maps live broker
   orders into accepted/new/partially_filled; an order working in one of those
   states is still in flight and must keep blocking a duplicate for the same
   intent. Widening the predicate keeps the DB-level guard consistent with the
   trade-executor's OPEN_ORDER_STATUSES code constant.

Both steps are additive/idempotent and make no data change.
"""
from alembic import op

revision = "0023"
down_revision = "0022"


def upgrade() -> None:
    # 1. VALIDATE the risk FK if it exists and is not already valid.
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'fk_alpaca_orders_risk'
                  AND conrelid = 'alpaca_orders'::regclass
                  AND NOT convalidated
            ) THEN
                ALTER TABLE alpaca_orders VALIDATE CONSTRAINT fk_alpaca_orders_risk;
            END IF;
        END $$;
        """
    )

    # 2. Widen the intent-open dedup unique index to the full working set.
    op.execute("DROP INDEX IF EXISTS idx_alpaca_orders_intent_open")
    op.execute(
        """
        CREATE UNIQUE INDEX idx_alpaca_orders_intent_open
          ON alpaca_orders(intent_id)
          WHERE intent_id IS NOT NULL
            AND status IN ('pending','submitted','deferred',
                           'accepted','new','partially_filled')
        """
    )


def downgrade() -> None:
    # Revert the index to the prior (0008) predicate. We cannot un-VALIDATE a
    # constraint in Postgres (and would not want to weaken the audit guarantee),
    # so the FK validation is intentionally left in place.
    op.execute("DROP INDEX IF EXISTS idx_alpaca_orders_intent_open")
    op.execute(
        """
        CREATE UNIQUE INDEX idx_alpaca_orders_intent_open
          ON alpaca_orders(intent_id)
          WHERE intent_id IS NOT NULL
            AND status IN ('pending','submitted','deferred')
        """
    )
