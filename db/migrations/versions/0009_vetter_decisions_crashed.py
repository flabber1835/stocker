"""Add 'crashed' column to vetter_decisions

The API surfaces a per-ticker `vetter_crashed` boolean (rankings overlay,
search, and delta/trade-proposal overlay) so the dashboard can show a CRASHED
badge without string-scanning the reason text. Those SELECTs reference a
`crashed` column that the schema never defined, so once a vetter run exists the
overlay queries raise `column "crashed" does not exist` → HTTP 500 → the rank
tab renders "No ranking data".

This migration adds the missing column. The vetter already computes `crashed`
per ticker (set True by the crash-isolation fallback) and now persists it.

Revision ID: 0009
Revises: 0008
Create Date: 2026-05-28 07:00:00.000000
"""
from alembic import op


revision = "0009"
down_revision = "0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE vetter_decisions "
        "ADD COLUMN IF NOT EXISTS crashed BOOLEAN NOT NULL DEFAULT FALSE"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE vetter_decisions DROP COLUMN IF EXISTS crashed")
