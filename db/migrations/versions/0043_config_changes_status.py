"""config_changes.status — transactional apply ordering (audit finding #4)

Revision ID: 0043
Revises: 0042

The one-click apply used to replace the live YAML FIRST and write the audit
row after, best-effort — a DB failure left the trading config changed with no
durable record. New ordering: rows are INSERTed as status='pending' BEFORE any
file write (DB failure → apply aborted, file untouched), flipped to 'applied'
after the atomic replace, or 'failed' if the replace itself failed. A row stuck
'pending' means "file applied, finalize failed" — an honest, queryable state.
Existing rows predate the column and were all real applies → default 'applied'.
"""
from alembic import op

revision = "0043"
down_revision = "0042"


def upgrade() -> None:
    op.execute(
        "ALTER TABLE config_changes "
        "ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'applied'"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE config_changes DROP COLUMN IF EXISTS status")
