"""factor_scores.scores JSONB — generic factor store (no column per factor)

Revision ID: 0030
Revises: 0029

The factor-engine output was a column per factor, so adding a factor required an
ALTER TABLE (e.g. 0028 added earnings_surprise). This adds a single `scores` JSONB
column that holds {factor_name: value} for ALL factors. New factors go into the
JSONB with NO migration. The legacy per-factor columns are KEPT (dual-written) for
backward compatibility and easy rollback; readers prefer `scores` and fall back to
the columns when it is null (old rows).

Backfills existing rows from the current columns so every historical row has a
populated `scores`. Backwards compatible and idempotent.
"""
from alembic import op

revision = "0030"
down_revision = "0029"

_LEGACY_FACTOR_COLUMNS = [
    "momentum", "quality", "value", "growth", "low_volatility", "liquidity",
    "issuance", "small_cap", "volume_surge", "near_high", "high_volatility",
    "earnings_surprise",
]


def upgrade() -> None:
    op.execute("ALTER TABLE factor_scores ADD COLUMN IF NOT EXISTS scores JSONB")
    # Backfill: build the JSONB object from the existing per-factor columns. NULLs
    # become JSON null (jsonb_build_object handles it), matching the read fallback.
    pairs = ", ".join(f"'{c}', {c}" for c in _LEGACY_FACTOR_COLUMNS)
    op.execute(
        f"UPDATE factor_scores SET scores = jsonb_build_object({pairs}) "
        f"WHERE scores IS NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE factor_scores DROP COLUMN IF EXISTS scores")
