-- Frozen from sentinel/schema.py at
-- 69cdfe8085a73bc68cc66da0d8dd3f9cd0bafd88.
-- This is a genuine pre-rollout behavioral schema: it is installed
-- directly and never passes through the current ensure_schema().

CREATE TABLE IF NOT EXISTS sentinel_account_binding (
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
        notes             TEXT);

CREATE TABLE IF NOT EXISTS sentinel_ownership_events (
        seq        BIGSERIAL PRIMARY KEY,
        state      TEXT        NOT NULL,
        at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        detail     JSONB       NOT NULL DEFAULT '{}'::jsonb);

CREATE INDEX IF NOT EXISTS idx_sentinel_ownership_state
        ON sentinel_ownership_events (state);

CREATE TABLE IF NOT EXISTS sentinel_execution_plans (
        plan_id                 TEXT PRIMARY KEY,
        decision_session        DATE        NOT NULL,
        effective_session       DATE        NOT NULL,
        target_exposure         NUMERIC     NOT NULL,
        -- The corpus version this decision CONSUMED. Architecture invariant #3.
        data_version            BIGINT,
        shadow_snapshot_hash    TEXT,
        sentinel_transition_hash TEXT,
        strategy_fingerprint    TEXT,
        deployment_id           TEXT,
        broker                  TEXT,
        broker_account_id       TEXT,
        takeover_epoch          BIGINT,
        publication_fingerprint TEXT,
        account_nav             NUMERIC     NOT NULL DEFAULT 0,
        account_cash            NUMERIC     NOT NULL DEFAULT 0,
        cash_residual           NUMERIC     NOT NULL DEFAULT 0,
        unpriced_securities     JSONB       NOT NULL DEFAULT '[]'::jsonb,
        defensive_security      TEXT,
        target_basket           JSONB       NOT NULL DEFAULT '{}'::jsonb,
        superseded_by           TEXT,
        created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW());

ALTER TABLE sentinel_execution_plans
        ADD COLUMN IF NOT EXISTS deployment_id TEXT;

ALTER TABLE sentinel_execution_plans
        ADD COLUMN IF NOT EXISTS broker TEXT;

ALTER TABLE sentinel_execution_plans
        ADD COLUMN IF NOT EXISTS broker_account_id TEXT;

ALTER TABLE sentinel_execution_plans
        ADD COLUMN IF NOT EXISTS takeover_epoch BIGINT;

ALTER TABLE sentinel_execution_plans
        ADD COLUMN IF NOT EXISTS publication_fingerprint TEXT;

ALTER TABLE sentinel_execution_plans
        ADD COLUMN IF NOT EXISTS account_nav NUMERIC NOT NULL DEFAULT 0;

ALTER TABLE sentinel_execution_plans
        ADD COLUMN IF NOT EXISTS account_cash NUMERIC NOT NULL DEFAULT 0;

ALTER TABLE sentinel_execution_plans
        ADD COLUMN IF NOT EXISTS cash_residual NUMERIC NOT NULL DEFAULT 0;

ALTER TABLE sentinel_execution_plans
        ADD COLUMN IF NOT EXISTS unpriced_securities JSONB NOT NULL
        DEFAULT '[]'::jsonb;

ALTER TABLE sentinel_execution_plans
        ADD COLUMN IF NOT EXISTS defensive_security TEXT;

CREATE TABLE IF NOT EXISTS sentinel_commands (
        client_key       TEXT PRIMARY KEY,
        plan_id          TEXT        NOT NULL,
        security_id      TEXT        NOT NULL,
        revision         INT         NOT NULL DEFAULT 0,
        -- The identity which MINTED client_key. It is stored on every command
        -- rather than inferred from today's binding: a restored-host adoption
        -- increments takeover_epoch, while predecessor commands remain real
        -- broker obligations under their original keys.
        deployment_id    TEXT        NOT NULL,
        broker           TEXT        NOT NULL,
        broker_account_id TEXT       NOT NULL,
        takeover_epoch   BIGINT      NOT NULL,
        symbol           TEXT        NOT NULL,
        broker_instrument_id TEXT,
        side             TEXT        NOT NULL,
        quantity         NUMERIC     NOT NULL,
        state            TEXT        NOT NULL,
        broker_order_id  TEXT,
        filled_quantity  NUMERIC     NOT NULL DEFAULT 0,
        filled_average_price NUMERIC,
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
        updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW());

ALTER TABLE sentinel_commands
        ADD COLUMN IF NOT EXISTS deployment_id TEXT;

ALTER TABLE sentinel_commands
        ADD COLUMN IF NOT EXISTS broker TEXT;

ALTER TABLE sentinel_commands
        ADD COLUMN IF NOT EXISTS broker_account_id TEXT;

ALTER TABLE sentinel_commands
        ADD COLUMN IF NOT EXISTS takeover_epoch BIGINT;

UPDATE sentinel_commands c
          SET deployment_id = b.deployment_id,
              broker = b.broker,
              broker_account_id = b.broker_account_id,
              takeover_epoch = b.takeover_epoch
         FROM sentinel_account_binding b
        WHERE b.id = 1
          AND (c.deployment_id IS NULL OR c.broker IS NULL
               OR c.broker_account_id IS NULL OR c.takeover_epoch IS NULL);

ALTER TABLE sentinel_commands
        ALTER COLUMN deployment_id SET NOT NULL;

ALTER TABLE sentinel_commands
        ALTER COLUMN broker SET NOT NULL;

ALTER TABLE sentinel_commands
        ALTER COLUMN broker_account_id SET NOT NULL;

ALTER TABLE sentinel_commands
        ALTER COLUMN takeover_epoch SET NOT NULL;

ALTER TABLE sentinel_commands
        ADD COLUMN IF NOT EXISTS recovered BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE sentinel_commands
        ADD COLUMN IF NOT EXISTS filled_average_price NUMERIC;

CREATE UNIQUE INDEX IF NOT EXISTS idx_sentinel_commands_inflight
        ON sentinel_commands (security_id)
        WHERE state IN ('SEND_PENDING','ACKNOWLEDGED','UNKNOWN',
                        'PARTIALLY_FILLED','CANCEL_PENDING');

CREATE INDEX IF NOT EXISTS idx_sentinel_commands_plan
        ON sentinel_commands (plan_id);

CREATE TABLE IF NOT EXISTS sentinel_command_events (
        seq         BIGSERIAL PRIMARY KEY,
        client_key  TEXT        NOT NULL,
        from_state  TEXT,
        to_state    TEXT        NOT NULL,
        filled_quantity NUMERIC,
        detail      TEXT,
        at          TIMESTAMPTZ NOT NULL DEFAULT NOW());

CREATE INDEX IF NOT EXISTS idx_sentinel_command_events_key
        ON sentinel_command_events (client_key, seq);

CREATE TABLE IF NOT EXISTS sentinel_fills (
        broker_order_id TEXT        NOT NULL,
        fill_key        TEXT        NOT NULL,
        client_key      TEXT,
        quantity        NUMERIC     NOT NULL,
        price           NUMERIC     NOT NULL,
        filled_at       TIMESTAMPTZ,
        PRIMARY KEY (broker_order_id, fill_key));

CREATE TABLE IF NOT EXISTS sentinel_observations (
        seq          BIGSERIAL PRIMARY KEY,
        observed_at  TIMESTAMPTZ NOT NULL,
        terminal_recovery_through TIMESTAMPTZ,
        completeness TEXT        NOT NULL,
        positions    JSONB       NOT NULL DEFAULT '{}'::jsonb,
        orders       JSONB       NOT NULL DEFAULT '[]'::jsonb,
        runtime_state TEXT);

ALTER TABLE sentinel_observations
        ADD COLUMN IF NOT EXISTS terminal_recovery_through TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS sentinel_terminal_recovery_watermark (
        id                INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
        broker            TEXT        NOT NULL,
        broker_account_id TEXT        NOT NULL,
        processed_through TIMESTAMPTZ NOT NULL,
        updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW());

CREATE TABLE IF NOT EXISTS sentinel_processed_sessions (
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
        updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW());

ALTER TABLE sentinel_processed_sessions
        ADD COLUMN IF NOT EXISTS state JSONB;

CREATE TABLE IF NOT EXISTS sentinel_cash_flows (
        flow_id     TEXT PRIMARY KEY,
        session     DATE NOT NULL,
        amount      NUMERIC NOT NULL CHECK (amount <> 0),
        detail      TEXT NOT NULL,
        recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW());

CREATE INDEX IF NOT EXISTS idx_sentinel_cash_flows_session
        ON sentinel_cash_flows (session);

CREATE TABLE IF NOT EXISTS sentinel_nav_reconciliations (
        session       DATE PRIMARY KEY,
        previous_nav  NUMERIC NOT NULL,
        observed_nav  NUMERIC NOT NULL,
        marked_pl     NUMERIC NOT NULL,
        external      NUMERIC NOT NULL,
        unexplained   NUMERIC NOT NULL,
        attribution   TEXT NOT NULL
                      CHECK (attribution IN ('DECLARED','MARKET','UNEXPLAINED')),
        reconciled_at TIMESTAMPTZ NOT NULL DEFAULT NOW());
