"""Add at_risk/buy_add/sell_trim actions, actual_weight, weight_drift, and counters

Revision ID: 0004
Revises: 0003
Create Date: 2026-05-23 00:00:00.000000
"""
from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Widen the action CHECK constraint on delta_intents to allow new action values.
    #    We find and drop any check constraint on the action column by querying pg_constraint
    #    rather than relying on the auto-generated name — the auto-name is predictable on
    #    postgres:16 but may differ on older installs or manually-created schemas.
    op.execute("""
        DO $$
        DECLARE r record;
        BEGIN
            FOR r IN
                SELECT c.conname
                FROM   pg_constraint c
                JOIN   pg_class t ON t.oid = c.conrelid
                WHERE  t.relname = 'delta_intents'
                  AND  c.contype = 'c'
                  AND  pg_get_constraintdef(c.oid) LIKE '%action%'
            LOOP
                EXECUTE 'ALTER TABLE delta_intents DROP CONSTRAINT ' || quote_ident(r.conname);
            END LOOP;
        END $$
    """)
    op.execute("""
        ALTER TABLE delta_intents
        ADD CONSTRAINT delta_intents_action_check
        CHECK (action IN ('entry','exit','hold','watch','at_risk','buy_add','sell_trim'))
    """)

    # 2. New columns on delta_intents for drift tracking
    op.execute("""
        ALTER TABLE delta_intents
        ADD COLUMN IF NOT EXISTS actual_weight  NUMERIC(10,6),
        ADD COLUMN IF NOT EXISTS weight_drift   NUMERIC(10,6)
    """)

    # 3. New counter columns on delta_runs
    op.execute("""
        ALTER TABLE delta_runs
        ADD COLUMN IF NOT EXISTS at_risk_count   INTEGER NOT NULL DEFAULT 0,
        ADD COLUMN IF NOT EXISTS buy_add_count   INTEGER NOT NULL DEFAULT 0,
        ADD COLUMN IF NOT EXISTS sell_trim_count INTEGER NOT NULL DEFAULT 0
    """)


def downgrade() -> None:
    pass
