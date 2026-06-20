"""fix idx_alpaca_orders_intent_open predicate token: partially_filled -> partial_fill

Revision ID: 0026
Revises: 0025

Migration 0023 widened the partial UNIQUE index idx_alpaca_orders_intent_open to
the full working-status set, but its predicate used the BROKER spelling
'partially_filled' — a token alpaca-sync NEVER persists. alpaca-sync (and the
shared OPEN_ORDER_STATUSES constant) write 'partial_fill'. So a partially-filled
order was NOT covered by the dedup index, leaving a hole through which a second
open order for the same intent could be created while the first works its
remainder.

We do NOT edit the already-applied 0023 (history is immutable); instead drop and
recreate the index with the correct 'partial_fill' token. Idempotent and additive
(no data change).
"""
from alembic import op

revision = "0026"
down_revision = "0025"


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_alpaca_orders_intent_open")
    op.execute(
        """
        CREATE UNIQUE INDEX idx_alpaca_orders_intent_open
          ON alpaca_orders(intent_id)
          WHERE intent_id IS NOT NULL
            AND status IN ('pending','submitted','deferred',
                           'accepted','new','partial_fill')
        """
    )


def downgrade() -> None:
    # Revert to the 0023 predicate (with the buggy broker spelling) so down/up is
    # symmetric with the prior migration state.
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
