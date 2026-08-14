-- Frozen delta from sentinel/schema.py at
-- 6113bffd896824ee24891b0c1aeada60c2b73ef5.
-- Apply after behavioral_schema_pre_rollout_69cdfe8.sql. Together they
-- construct the exact reviewed pre-ledger behavioral schema without
-- invoking the current ensure_schema().

CREATE TABLE IF NOT EXISTS sentinel_system_certificates (
        certificate_sha256  TEXT PRIMARY KEY,
        manifest_bytes      BYTEA       NOT NULL,
        manifest            JSONB       NOT NULL,
        allowed_rollout_modes JSONB     NOT NULL,
        installed_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        revoked_at          TIMESTAMPTZ,
        revocation_reason   TEXT,
        CHECK ((revoked_at IS NULL AND revocation_reason IS NULL)
            OR (revoked_at IS NOT NULL AND revocation_reason IS NOT NULL)));

CREATE UNIQUE INDEX IF NOT EXISTS idx_sentinel_one_active_certificate
        ON sentinel_system_certificates ((1)) WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS sentinel_system_certificate_events (
        seq                 BIGSERIAL PRIMARY KEY,
        certificate_sha256  TEXT        NOT NULL,
        action              TEXT        NOT NULL
                            CHECK (action IN ('INSTALLED','REVOKED')),
        detail              TEXT        NOT NULL,
        at                  TIMESTAMPTZ NOT NULL DEFAULT NOW());

CREATE TABLE IF NOT EXISTS sentinel_rollout_state (
        id                  INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
        mode                TEXT        NOT NULL
                            CHECK (mode IN ('PINNED_1_00','CONTROLLER')),
        version             BIGINT      NOT NULL CHECK (version >= 1),
        certificate_sha256  TEXT,
        updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK ((mode = 'PINNED_1_00' AND certificate_sha256 IS NULL)
            OR (mode = 'CONTROLLER' AND certificate_sha256 IS NOT NULL)));

CREATE TABLE IF NOT EXISTS sentinel_rollout_events (
        seq                 BIGSERIAL PRIMARY KEY,
        version             BIGINT      NOT NULL UNIQUE,
        from_mode           TEXT        NOT NULL,
        to_mode             TEXT        NOT NULL,
        certificate_sha256  TEXT,
        reason              TEXT        NOT NULL,
        at                  TIMESTAMPTZ NOT NULL DEFAULT NOW());

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
        rollout_mode            TEXT        NOT NULL DEFAULT 'PINNED_1_00',
        rollout_version         BIGINT      NOT NULL DEFAULT 1,
        rollout_certificate_sha256 TEXT,
        target_basket           JSONB       NOT NULL DEFAULT '{}'::jsonb,
        superseded_by           TEXT,
        created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW());

ALTER TABLE sentinel_execution_plans
        ADD COLUMN IF NOT EXISTS rollout_mode TEXT NOT NULL
        DEFAULT 'PINNED_1_00';

ALTER TABLE sentinel_execution_plans
        ADD COLUMN IF NOT EXISTS rollout_version BIGINT NOT NULL DEFAULT 1;

ALTER TABLE sentinel_execution_plans
        ADD COLUMN IF NOT EXISTS rollout_certificate_sha256 TEXT;
