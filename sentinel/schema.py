"""Sentinel's BEHAVIOURAL state schema — everything the appliance needs to
resume correctly, transactionally, in one database.

Separate from `sentinel/feed/schema.py`, which owns the CORPUS. The split is not
cosmetic: the corpus is rebuildable from the vendor and the behavioural state is
not, so they have different backup obligations and different recovery stories.

## Why this exists at all

`ownership.jsonl` was the right call when it was written — Sentinel had no
database, and the ownership decision had to be durable before one existed. That
is no longer true, and the file has a property no safety-critical state should
keep: losing it re-arms classification of a Sentinel-owned book as legacy. It
lives on a different Docker volume from PostgreSQL, so a restore that recovers
the database can still lose it, and the two would then disagree about whether an
account had been migrated.

The file survives as optional append-only AUDIT evidence. The database is
authoritative.

## The binding is one row, enforced by the schema

`CHECK (id = 1)` rather than convention. An appliance controls exactly one broker
account; a second binding row would mean two answers to "whose account is this?"
and the failure would surface as an appliance confidently managing the wrong
book. Making it unrepresentable is cheaper than detecting it.
"""
from __future__ import annotations

DDL = (
    # ------------------------------------------------------------------
    # WHO WE ARE, AND WHOSE ACCOUNT THIS IS.
    #
    # Verified at every startup against what the broker says. A mismatch is a
    # refusal to trade, not a warning.
    # ------------------------------------------------------------------
    """CREATE TABLE IF NOT EXISTS sentinel_account_binding (
        id                INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
        deployment_id     TEXT        NOT NULL,
        broker            TEXT        NOT NULL,
        broker_account_id TEXT        NOT NULL,
        -- MONOTONIC. Incremented only by an explicit adopt-restored-account.
        -- It fences a restored appliance's key namespace off from its
        -- predecessor's so their orders can never be confused. It does NOT stop
        -- both trading — that needs credential revocation — but it bounds and
        -- attributes the damage.
        takeover_epoch    BIGINT      NOT NULL DEFAULT 1,
        ownership_state   TEXT        NOT NULL,
        established_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        notes             TEXT)""",

    # ------------------------------------------------------------------
    # THE OWNERSHIP HISTORY. Append-only by application convention, and the
    # same caveat Stocker's intent_proposals earned applies here and is worth
    # stating rather than implying: nothing at the DATABASE level prevents an
    # UPDATE or DELETE. What is guaranteed is that no code path in this package
    # rewrites a row. Before this is treated as a permanent audit ledger it
    # needs table-level immutability or restricted grants.
    # ------------------------------------------------------------------
    """CREATE TABLE IF NOT EXISTS sentinel_ownership_events (
        seq        BIGSERIAL PRIMARY KEY,
        state      TEXT        NOT NULL,
        at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        detail     JSONB       NOT NULL DEFAULT '{}'::jsonb)""",
    """CREATE INDEX IF NOT EXISTS idx_sentinel_ownership_state
        ON sentinel_ownership_events (state)""",

    # ------------------------------------------------------------------
    # EXECUTION PLANS. Immutable. A new session's decision creates a NEW plan
    # and may supersede the previous one's UNSENT commands; it never edits one.
    # ------------------------------------------------------------------
    """CREATE TABLE IF NOT EXISTS sentinel_execution_plans (
        plan_id                 TEXT PRIMARY KEY,
        decision_session        DATE        NOT NULL,
        effective_session       DATE        NOT NULL,
        target_exposure         NUMERIC     NOT NULL,
        -- The corpus version this decision CONSUMED. Architecture invariant #3.
        data_version            BIGINT,
        shadow_snapshot_hash    TEXT,
        sentinel_transition_hash TEXT,
        strategy_fingerprint    TEXT,
        target_basket           JSONB       NOT NULL DEFAULT '{}'::jsonb,
        superseded_by           TEXT,
        created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW())""",

    # ------------------------------------------------------------------
    # THE COMMAND JOURNAL. One row per client_key, which is the whole point:
    # the key is derived, so a crash-recovered process recomputes it and finds
    # THIS row rather than guessing.
    #
    # `client_key` is the PRIMARY KEY, so a duplicate command is a constraint
    # violation rather than a second order.
    # ------------------------------------------------------------------
    """CREATE TABLE IF NOT EXISTS sentinel_commands (
        client_key       TEXT PRIMARY KEY,
        plan_id          TEXT        NOT NULL,
        security_id      TEXT        NOT NULL,
        revision         INT         NOT NULL DEFAULT 0,
        symbol           TEXT        NOT NULL,
        broker_instrument_id TEXT,
        side             TEXT        NOT NULL,
        quantity         NUMERIC     NOT NULL,
        state            TEXT        NOT NULL,
        broker_order_id  TEXT,
        filled_quantity  NUMERIC     NOT NULL DEFAULT 0,
        detail           TEXT,
        -- ADOPTED FROM THE BROKER rather than created here. Its client_key was
        -- minted by a previous generation of this appliance and CANNOT be
        -- regenerated (the key is a hash; plan_id and revision are not
        -- recoverable from it), so the recompute check that guards ordinary
        -- rows is skipped for these. Without adoption a stale restore left the
        -- position permanently unexplained: the appliance could de-risk but
        -- never re-risk.
        recovered        BOOLEAN     NOT NULL DEFAULT FALSE,
        created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
    """ALTER TABLE sentinel_commands
        ADD COLUMN IF NOT EXISTS recovered BOOLEAN NOT NULL DEFAULT FALSE""",
    # AT MOST ONE IN-FLIGHT COMMAND PER SECURITY, enforced by the database and
    # not only by `authorize`. The application check can be bypassed by a bug or
    # a second process; this cannot. UNKNOWN is in the list deliberately — an
    # order we cannot see may still be resting.
    """CREATE UNIQUE INDEX IF NOT EXISTS idx_sentinel_commands_inflight
        ON sentinel_commands (security_id)
        WHERE state IN ('SEND_PENDING','ACKNOWLEDGED','UNKNOWN',
                        'PARTIALLY_FILLED','CANCEL_PENDING')""",
    """CREATE INDEX IF NOT EXISTS idx_sentinel_commands_plan
        ON sentinel_commands (plan_id)""",

    # ------------------------------------------------------------------
    # EVERY STATE CHANGE, append-only. The commands table is the CURRENT
    # answer; this is how it got there, which is what a post-mortem needs.
    # ------------------------------------------------------------------
    """CREATE TABLE IF NOT EXISTS sentinel_command_events (
        seq         BIGSERIAL PRIMARY KEY,
        client_key  TEXT        NOT NULL,
        from_state  TEXT,
        to_state    TEXT        NOT NULL,
        filled_quantity NUMERIC,
        detail      TEXT,
        at          TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
    """CREATE INDEX IF NOT EXISTS idx_sentinel_command_events_key
        ON sentinel_command_events (client_key, seq)""",

    # ------------------------------------------------------------------
    # FILLS, keyed so the same fill cannot be counted twice on replay.
    # ------------------------------------------------------------------
    # `fill_key` is a CONTENT fingerprint, not an ordinal. Keying on a fill's
    # position in whatever list the broker happened to return meant a query over
    # a different window gave the same fill a different key — and could give a
    # DIFFERENT fill one already used, which ON CONFLICT DO NOTHING then
    # silently dropped. See journal.fill_fingerprint, including why this is not
    # the final answer: broker-native activity ids (and trade corrections) must
    # replace it before this table becomes the accounting ledger.
    """CREATE TABLE IF NOT EXISTS sentinel_fills (
        broker_order_id TEXT        NOT NULL,
        fill_key        TEXT        NOT NULL,
        client_key      TEXT,
        quantity        NUMERIC     NOT NULL,
        price           NUMERIC     NOT NULL,
        filled_at       TIMESTAMPTZ,
        PRIMARY KEY (broker_order_id, fill_key))""",

    # ------------------------------------------------------------------
    # OBSERVATIONS, retained because a reconciliation dispute is unanswerable
    # without knowing what the broker actually said at the time.
    # ------------------------------------------------------------------
    """CREATE TABLE IF NOT EXISTS sentinel_observations (
        seq          BIGSERIAL PRIMARY KEY,
        observed_at  TIMESTAMPTZ NOT NULL,
        completeness TEXT        NOT NULL,
        positions    JSONB       NOT NULL DEFAULT '{}'::jsonb,
        orders       JSONB       NOT NULL DEFAULT '[]'::jsonb,
        runtime_state TEXT)""",

    # ------------------------------------------------------------------
    # CATCH-UP. How far the deterministic replay has advanced.
    #
    # ONE ROW, keyed by a cursor name. A table with many rows would invite
    # "the latest by timestamp", and a wall clock is not an ordering of
    # trading sessions — a re-run at 09:00 would look newer than the session
    # it is behind.
    #
    # The pointer is written in the SAME TRANSACTION as the state the session
    # produced. Written after the whole loop instead, a crash replays sessions
    # that already advanced — and Wealth Core's state is path-dependent, so a
    # replayed session double-ages every episode. Written before, a crash
    # SKIPS a session, which is the silent one.
    # ------------------------------------------------------------------
    """CREATE TABLE IF NOT EXISTS sentinel_processed_sessions (
        cursor_name TEXT PRIMARY KEY,
        session     DATE NOT NULL,
        -- THE STATE, BESIDE THE CURSOR AND IN THE SAME STATEMENT.
        --
        -- `advance_state` is handed the transaction so it CAN write its own
        -- durable state; nothing can make it. Without this column the only
        -- durable half was the pointer, so a crash after the commit left the
        -- cursor saying Aug 10 was done while the book still said Aug 9 — and
        -- Aug 10 is then skipped permanently and silently.
        state       JSONB,
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
    """ALTER TABLE sentinel_processed_sessions
        ADD COLUMN IF NOT EXISTS state JSONB""",

    # ------------------------------------------------------------------
    # EXTERNAL CASH. Declared, never inferred from a balance.
    #
    # NAV moves for two reasons and the number does not say which. Guessing
    # "P&L" puts a $50k deposit into every return the system will ever report;
    # guessing "cash flow" gives a genuine reconciliation break a benign label
    # and stops it being investigated. See sentinel/core/cashflow.py.
    #
    # `amount` is SIGNED — positive is money in — rather than a magnitude plus
    # a direction column. Two fields that must agree are two fields that can
    # disagree, and the disagreement here inverts the correction.
    # ------------------------------------------------------------------
    """CREATE TABLE IF NOT EXISTS sentinel_cash_flows (
        flow_id     TEXT PRIMARY KEY,
        session     DATE NOT NULL,
        amount      NUMERIC NOT NULL CHECK (amount <> 0),
        detail      TEXT NOT NULL,
        recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
    """CREATE INDEX IF NOT EXISTS idx_sentinel_cash_flows_session
        ON sentinel_cash_flows (session)""",

    # The residual, kept. "Was Tuesday's move ever explained?" is asked days
    # later by someone who was not there, and an answer that lived only in a
    # log line has scrolled past.
    """CREATE TABLE IF NOT EXISTS sentinel_nav_reconciliations (
        session       DATE PRIMARY KEY,
        previous_nav  NUMERIC NOT NULL,
        observed_nav  NUMERIC NOT NULL,
        marked_pl     NUMERIC NOT NULL,
        external      NUMERIC NOT NULL,
        unexplained   NUMERIC NOT NULL,
        attribution   TEXT NOT NULL
                      CHECK (attribution IN ('DECLARED','MARKET','UNEXPLAINED')),
        reconciled_at TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
)


def ensure_schema(conn) -> None:
    with conn.cursor() as cur:
        for statement in DDL:
            cur.execute(statement)
    conn.commit()
