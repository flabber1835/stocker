"""persist the crash-loop-breaker counter across scheduler restarts

Revision ID: 0024
Revises: 0023

The scheduler's crash-loop breaker (MAX_RESTART_ABORT_RETRIES) counts how many
distinct RESTART_ABORTED crash cycles a single (step, run_date) has gone through.
A RESTART_ABORTED orphan is normally re-triggered (recover from a transient
restart), but a DETERMINISTIC crash — e.g. the factor step OOM-killing on a
RAM-constrained host — reproduces on every retry, so after the limit the breaker
SUSPENDS the chain instead of looping forever.

Until now that counter lived ONLY in process memory (_restart_abort_cycles /
_restart_abort_seen). The defect: a deterministic crash that ALSO restarts the
scheduler (the OOM took the whole box, or compose restarted everything) wiped the
in-memory counter on the very restart the breaker is meant to guard — so it
re-armed from 0 and looped forever, exactly the failure mode it was added for.

This table makes the count durable. One row per (step, run_date):

    step           — the chain step name ('fetch-data', 'pipeline', 'vet', ...)
    run_date       — the data-date the crash cycles belong to
    run_id_token   — the orphan run_id last counted, for cross-tick dedup: re-
                     seeing the SAME orphan across fast ticks must count once
    cycle_count    — distinct crash cycles seen so far
    updated_at     — last touch

Minimal and additive: the in-memory dicts stay as a fast cache, but this row is
the source of truth, so the count survives the restart it is guarding. Cleared
(row deleted) on a clean success, matching _clear_restart_abort_state semantics.
"""
from alembic import op

revision = "0024"
down_revision = "0023"


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS scheduler_restart_cycles (
            step          TEXT        NOT NULL,
            run_date      DATE        NOT NULL,
            run_id_token  TEXT,
            cycle_count   INTEGER     NOT NULL DEFAULT 0,
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (step, run_date)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS scheduler_restart_cycles")
