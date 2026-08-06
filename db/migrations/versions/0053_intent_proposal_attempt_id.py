"""intent_proposals.attempt_id: make repeated attempts distinguishable

Revision ID: 0053
Revises: 0052

Migration 0052 made a ticker's proposals inspectable. It did not make a run's
ATTEMPTS inspectable, and the difference only shows up on a retry.

WHAT THE RETRY ACTUALLY DID, measured rather than assumed. Production writes both
tables inside ONE savepoint:

    write_proposals(...)      # rows insert fine — no uniqueness here
    write_net_intents(...)    # unique index raises on the second attempt
                              # -> the SAVEPOINT rolls back, taking the new
                              #    proposal rows with it

So a retried run stayed at its original proposal count. The append-only table was
append-only right up to the moment anything went wrong, which is the moment an
audit ledger is worth having. A test asserting `write_proposals` alone is
additive was measuring a path production never takes.

`attempt_id` is one UUID per INVOCATION of the writer, shared by every row that
invocation inserts. Combined with the idempotent-or-fatal net-intent write it
gives coherent retry semantics:

    identical net intent already present   -> idempotent success, the retry's
                                              proposals COMMIT under a new
                                              attempt_id, and both attempts stay
                                              readable
    a DIFFERENT net intent for the key     -> fatal divergence; the savepoint
                                              rolls back and nothing is written
                                              (the divergence detail travels in
                                              the exception, not in the table)

NOT NULL with NO DEFAULT, deliberately. A `DEFAULT gen_random_uuid()` would give
every ROW its own attempt id, which is the opposite of what the column is for and
would look correct in every schema dump. The writer must supply it.

Existing rows are grouped one attempt per run_id — the only honest reading of
data written before attempts were tracked.
"""
from alembic import op

revision = "0053"
down_revision = "0052"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE intent_proposals ADD COLUMN IF NOT EXISTS attempt_id UUID")
    # Pre-existing rows: one attempt per run. Not gen_random_uuid() per row —
    # that would assert every historical row was its own attempt, which is false.
    op.execute("""
        UPDATE intent_proposals p
           SET attempt_id = g.aid
          FROM (SELECT run_id, gen_random_uuid() AS aid
                  FROM intent_proposals
                 WHERE attempt_id IS NULL
                 GROUP BY run_id) g
         WHERE p.run_id = g.run_id AND p.attempt_id IS NULL
    """)
    op.execute("ALTER TABLE intent_proposals ALTER COLUMN attempt_id SET NOT NULL")
    op.execute("CREATE INDEX IF NOT EXISTS idx_intent_proposals_attempt "
               "ON intent_proposals(run_id, attempt_id)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_intent_proposals_attempt")
    op.execute("ALTER TABLE intent_proposals DROP COLUMN IF EXISTS attempt_id")
