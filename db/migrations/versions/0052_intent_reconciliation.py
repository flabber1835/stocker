"""intent_proposals + net_intents: reconcile conflicting intents (defect 4)

Revision ID: 0052
Revises: 0051

THE DEFECT. Crash-brake moves are APPENDED to the decision list without removing
the base decision, and `delta_intents` has no unique `(run_id, ticker)`. So one
ticker can carry `exit` AND `risk_reduce` in a single run, and whichever row a
downstream reader picked up was the instruction that executed. That is not a
theoretical ordering concern: `exit` and `risk_reduce` are different trades, and
the pair executes as either "close the position" or "sell part of it" depending
on nothing.

WHY THIS IS NOT AN INDEX ON `delta_intents`. A unique constraint there would turn
conflicting LOGIC into an INSERTION FAILURE — the delta step would raise at the
moment the brake first engages, which is exactly the moment nothing may fail, and
the operator would learn that two controls disagreed without learning what either
wanted. Uniqueness is not reconciliation. The layering instead:

    intent_proposals   APPEND-ONLY audit. Every contributing proposal survives,
                       including the ones reconciliation discarded. NO uniqueness
                       constraint — that is the point of the table.
    net_intents        ONE final economic instruction per
                       (run_id, account_id, ticker). The unique index lives HERE,
                       on the table that represents the executable instruction.
    provenance         `resolved_by` (the rule) + `contributing` (the proposals,
                       flagged with which one won), stored ON the net intent.

`delta_intents` is UNTOUCHED by this migration and the trade-executor still reads
it. Both new tables are SHADOW-WRITTEN first so the reconciliation is observed
against real traffic before anything depends on it; switching the executor's read
is a separate, later change with its own evidence.

`account_id` is in the key even though the deploy runs one broker account today
(default 'default'). The invariant being enforced is per-account by nature, and
retrofitting a column into a unique index later means rebuilding it under load.

Reversible: the downgrade drops both tables. Nothing else references them, and no
executable path reads them yet, so a downgrade loses shadow audit rows only.
"""
from alembic import op

revision = "0052"
down_revision = "0051"
branch_labels = None
depends_on = None

# Same vocabulary as delta_intents (migration 0049). Kept literal rather than
# imported so the migration is a frozen record of the tokens legal at this point
# in history, and a later widening shows up as its own migration.
_ACTIONS = ("('entry','exit','hold','watch','at_risk','buy_add','sell_trim',"
            "'risk_reduce','risk_restore')")


def upgrade() -> None:
    op.execute(f"""
        CREATE TABLE IF NOT EXISTS intent_proposals (
            id                    UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id                UUID         NOT NULL
                                  REFERENCES delta_runs(run_id) ON DELETE CASCADE,
            account_id            VARCHAR(64)  NOT NULL DEFAULT 'default',
            ticker                VARCHAR(20)  NOT NULL,
            source                VARCHAR(32)  NOT NULL,
            action                VARCHAR(20)  NOT NULL CHECK (action IN {_ACTIONS}),
            seq                   INTEGER      NOT NULL,
            rank                  INTEGER,
            composite_score       NUMERIC(12,6),
            confirmation_days_met INTEGER,
            target_weight         NUMERIC(10,6),
            actual_weight         NUMERIC(10,6),
            weight_drift          NUMERIC(10,6),
            reason                TEXT,
            created_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """)
    # Deliberately NOT unique on (run_id, account_id, ticker): a ticker having
    # several proposals is the condition this table exists to record.
    op.execute("CREATE INDEX IF NOT EXISTS idx_intent_proposals_run "
               "ON intent_proposals(run_id, ticker)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_intent_proposals_source "
               "ON intent_proposals(run_id, source)")

    op.execute(f"""
        CREATE TABLE IF NOT EXISTS net_intents (
            id                    UUID         PRIMARY KEY DEFAULT gen_random_uuid(),
            run_id                UUID         NOT NULL
                                  REFERENCES delta_runs(run_id) ON DELETE CASCADE,
            account_id            VARCHAR(64)  NOT NULL DEFAULT 'default',
            ticker                VARCHAR(20)  NOT NULL,
            action                VARCHAR(20)  NOT NULL CHECK (action IN {_ACTIONS}),
            source                VARCHAR(32)  NOT NULL,
            resolved_by           VARCHAR(64)  NOT NULL,
            conflicted            BOOLEAN      NOT NULL DEFAULT FALSE,
            contributing          JSONB        NOT NULL DEFAULT '[]'::jsonb,
            rank                  INTEGER,
            composite_score       NUMERIC(12,6),
            confirmation_days_met INTEGER,
            target_weight         NUMERIC(10,6),
            actual_weight         NUMERIC(10,6),
            weight_drift          NUMERIC(10,6),
            reason                TEXT,
            created_at            TIMESTAMPTZ  NOT NULL DEFAULT NOW()
        )
    """)
    # THE invariant. On this table it is a guarantee about the executable
    # instruction; on delta_intents it would have been a crash.
    op.execute("CREATE UNIQUE INDEX IF NOT EXISTS uq_net_intents_run_account_ticker "
               "ON net_intents(run_id, account_id, ticker)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_net_intents_conflicted "
               "ON net_intents(run_id) WHERE conflicted")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS net_intents")
    op.execute("DROP TABLE IF EXISTS intent_proposals")
