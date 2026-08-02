"""delta_intents.action: room for the crash brake's risk_reduce / risk_restore

Revision ID: 0049
Revises: 0048

The crash brake scales the whole book's gross exposure on a market signal and
restores it when the signal clears. Those are NOT sell_trim / buy_add: a trim is
a per-name correction toward a target weight, and using it here would make a
book-level de-risking indistinguishable from ordinary rebalancing in every
downstream reader — the risk-service turnover accounting, the decision ledger,
the forest map's by_mechanism attribution, and any post-mortem asking "why did we
sell half of everything on the 14th".

Two changes, and the first is a hard blocker rather than a nicety:

  1. `action` is VARCHAR(10). 'risk_reduce' is 11 characters and 'risk_restore'
     is 12, so both are silently unstorable today — an INSERT would raise
     StringDataRightTruncation at the moment the brake first engages, which is
     precisely the moment nothing may fail. Widened to VARCHAR(20).

  2. The CHECK constraint enumerates the allowed tokens and has to learn the two
     new ones.

Applied to delta_intents only. `alpaca_orders.action` and the other action
columns carry the EXECUTED side (buy/sell) rather than the intent's mechanism,
so they need neither change; widening them would imply a vocabulary they do not
have.

Reversible: the downgrade narrows back to VARCHAR(10) and restores the old CHECK,
which will fail loudly if any risk_* row exists — correct, since silently
deleting risk decisions to fit a column would be worse.
"""
from alembic import op

revision = "0049"
down_revision = "0048"
branch_labels = None
depends_on = None

_OLD = "('entry','exit','hold','watch','at_risk','buy_add','sell_trim')"
_NEW = ("('entry','exit','hold','watch','at_risk','buy_add','sell_trim',"
        "'risk_reduce','risk_restore')")


def upgrade() -> None:
    # Drop the CHECK first: widening the column while a constraint references it
    # is fine, but re-adding is cheaper than an ALTER that has to re-validate.
    op.execute("ALTER TABLE delta_intents DROP CONSTRAINT IF EXISTS delta_intents_action_check")
    op.execute("ALTER TABLE delta_intents ALTER COLUMN action TYPE VARCHAR(20)")
    op.execute(f"ALTER TABLE delta_intents ADD CONSTRAINT delta_intents_action_check "
               f"CHECK (action IN {_NEW})")


def downgrade() -> None:
    op.execute("ALTER TABLE delta_intents DROP CONSTRAINT IF EXISTS delta_intents_action_check")
    # Intentionally NOT deleting risk_* rows to make the column fit. If any exist
    # this raises, which is the honest outcome: a downgrade that quietly discards
    # risk decisions is worse than one that refuses.
    op.execute("ALTER TABLE delta_intents ALTER COLUMN action TYPE VARCHAR(10)")
    op.execute(f"ALTER TABLE delta_intents ADD CONSTRAINT delta_intents_action_check "
               f"CHECK (action IN {_OLD})")
