"""vendor_shadow_runs — one row per AV-vs-Sharadar comparison

Revision ID: 0051
Revises: 0050

The AV→Sharadar migration cannot be decided from an argument about vendor
quality. Live's `adjusted_close` is AV-vintage (written once, re-based only when
AV restates) while Sharadar's `closeadj` is uniformly restated, so a cutover
silently re-bases every price — moving momentum, low_volatility, every drawdown,
and every peak the trailing stop reads on a book whose exit policy IS the peak.

So the decision needs a measured series, not a snapshot. This table is that
series: one row per session compared, holding the diff summary verbatim.

Design notes worth keeping:

  * `report` is JSONB and holds the WHOLE comparison. Nothing is recomputed at
    read time, so a stored row can never disagree with the run that produced it.
    The promoted columns below exist only so a trend can be queried without
    unpacking JSON on every row.
  * `score_date` is UNIQUE. The comparison is a pure function of (session,
    config, corpus), so a re-run must overwrite rather than accumulate — a
    duplicate would double-count that session in any trend read off this table.
  * `status` distinguishes 'success' from 'unavailable'. bt-postgres is a
    SEPARATE compose project that is legitimately down during a live-only
    deploy, and a row saying so is materially more useful than no row: it
    explains a gap in the series that would otherwise look like a skipped
    measurement.
  * No FK to any live table. This is a diagnostic about DATA PROVENANCE, not
    about a trading decision, and a foreign key would tie its retention to the
    lifecycle of runs it only observes.

Purely additive; nothing reads it in the trading path. Reversible.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0051"
down_revision = "0050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vendor_shadow_runs",
        sa.Column("run_id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("score_date", sa.Date, nullable=False, unique=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="success"),
        sa.Column("config_hash", sa.String(64)),
        # Promoted from `report` for trend queries. Every one is nullable: a
        # comparison can legitimately produce some measurements and not others
        # (a short window has no price probe), and a 0.0 default would read as
        # "measured, total disagreement" — the worst possible misreading.
        sa.Column("universe_jaccard", sa.Numeric(6, 5)),
        sa.Column("ranking_spearman", sa.Numeric(6, 5)),
        sa.Column("overlap_at_25", sa.Numeric(6, 5)),
        sa.Column("target_jaccard", sa.Numeric(6, 5)),
        sa.Column("n_suspicious_prices", sa.Integer),
        sa.Column("verdict", sa.Text),
        sa.Column("report", postgresql.JSONB),
        sa.Column("error_message", sa.Text),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("NOW()"), nullable=False),
    )
    op.create_index("idx_vendor_shadow_date", "vendor_shadow_runs",
                    ["score_date"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_vendor_shadow_date", table_name="vendor_shadow_runs")
    op.drop_table("vendor_shadow_runs")
