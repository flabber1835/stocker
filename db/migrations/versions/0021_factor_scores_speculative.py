"""factor_scores: add speculative-style factor columns

Revision ID: 0021
Revises: 0020

Adds four optional, display-and-scoring factors to factor_scores so the
speculative_growth strategy can rank high-momentum / small-cap / high-vol /
breakout names the core quality-value model screens out:

  - small_cap        : prefers smaller market cap
  - volume_surge     : recent volume vs baseline (accumulation)
  - near_high        : proximity to the trailing high (breakout)
  - high_volatility  : inverse of low_volatility (prefers high vol)

All nullable. Backwards compatible: the core strategy gives these weight 0
(FactorWeights defaults), so they're computed/stored but never affect its
composite. NUMERIC(10,6) to match the other factor percentile columns.
"""
from alembic import op

revision = "0021"
down_revision = "0020"


def upgrade() -> None:
    for col in ("small_cap", "volume_surge", "near_high", "high_volatility"):
        op.execute(f"ALTER TABLE factor_scores ADD COLUMN IF NOT EXISTS {col} NUMERIC(10,6)")


def downgrade() -> None:
    for col in ("small_cap", "volume_surge", "near_high", "high_volatility"):
        op.execute(f"ALTER TABLE factor_scores DROP COLUMN IF EXISTS {col}")
