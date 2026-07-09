"""evaluator_reports.tool_transcript — Phase-2 tool-call audit trail

Revision ID: 0040
Revises: 0039

The Phase-2 evaluator lets the LLM call read-only tools mid-review (backtester
config-replay, SQL, source read, web search). Every call — name, arguments,
truncated result, elapsed ms — is persisted here so any number the narrative
cites can be traced to the exact query/backtest that produced it.

Backwards compatible and idempotent.
"""
from alembic import op

revision = "0040"
down_revision = "0039"


def upgrade() -> None:
    op.execute("ALTER TABLE evaluator_reports ADD COLUMN IF NOT EXISTS tool_transcript JSONB")


def downgrade() -> None:
    op.execute("ALTER TABLE evaluator_reports DROP COLUMN IF EXISTS tool_transcript")
