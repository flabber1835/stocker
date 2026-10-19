-- Frozen complete v1 schema from ce3083025b07c3447ac6319cefabadfa8f20d667.
-- Installed directly; never derive the v1 predecessor from current schema.

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

CREATE TABLE IF NOT EXISTS sentinel_signed_execution_certificates (
        install_sequence       BIGSERIAL   UNIQUE NOT NULL,
        certificate_sha256     TEXT        PRIMARY KEY
                                           CHECK (certificate_sha256 ~ '^[0-9a-f]{64}$'),
        certificate_id         TEXT        UNIQUE NOT NULL,
        key_id                 TEXT        NOT NULL,
        envelope_bytes         BYTEA       NOT NULL,
        envelope               JSONB       NOT NULL,
        claims                 JSONB       NOT NULL,
        issuer_generation      BIGINT      NOT NULL CHECK (issuer_generation >= 1),
        supersedes_certificate_sha256 TEXT REFERENCES
                                           sentinel_signed_execution_certificates
                                           (certificate_sha256),
        not_before             TIMESTAMPTZ NOT NULL,
        expires_at             TIMESTAMPTZ NOT NULL,
        installed_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK (not_before < expires_at));

CREATE TABLE IF NOT EXISTS sentinel_execution_certificate_lifecycle (
        certificate_sha256     TEXT        PRIMARY KEY REFERENCES
                                           sentinel_signed_execution_certificates
                                           (certificate_sha256),
        status                 TEXT        NOT NULL
                                           CHECK (status IN
                                           ('STAGED','ACTIVE','RETIRED','REVOKED')),
        activated_at           TIMESTAMPTZ,
        retired_at             TIMESTAMPTZ,
        revoked_at             TIMESTAMPTZ,
        revocation_reason      TEXT,
        CHECK ((status = 'REVOKED' AND revoked_at IS NOT NULL
                 AND revocation_reason IS NOT NULL)
            OR (status <> 'REVOKED' AND revoked_at IS NULL
                 AND revocation_reason IS NULL)));

CREATE UNIQUE INDEX IF NOT EXISTS
        idx_sentinel_one_active_signed_certificate
        ON sentinel_execution_certificate_lifecycle ((1))
        WHERE status = 'ACTIVE';

CREATE TABLE IF NOT EXISTS sentinel_execution_authority_state (
        id                     INT         PRIMARY KEY CHECK (id = 1),
        generation             BIGINT      NOT NULL CHECK (generation >= 0),
        highest_issuer_generation BIGINT   NOT NULL CHECK
                                           (highest_issuer_generation >= 0),
        active_certificate_sha256 TEXT REFERENCES
                                           sentinel_signed_execution_certificates
                                           (certificate_sha256),
        updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW());

CREATE TABLE IF NOT EXISTS sentinel_execution_certificate_revocations (
        certificate_sha256     TEXT        PRIMARY KEY REFERENCES
                                           sentinel_signed_execution_certificates
                                           (certificate_sha256),
        reason                 TEXT        NOT NULL CHECK (LENGTH(BTRIM(reason)) > 0),
        revoked_at             TIMESTAMPTZ NOT NULL DEFAULT NOW());

CREATE TABLE IF NOT EXISTS sentinel_execution_key_revocations (
        key_id                 TEXT        PRIMARY KEY,
        reason                 TEXT        NOT NULL CHECK (LENGTH(BTRIM(reason)) > 0),
        revoked_at             TIMESTAMPTZ NOT NULL DEFAULT NOW());

CREATE TABLE IF NOT EXISTS sentinel_execution_certificate_events (
        seq                    BIGSERIAL   PRIMARY KEY,
        authority_generation   BIGINT      NOT NULL CHECK (authority_generation >= 0),
        certificate_sha256     TEXT        NOT NULL,
        action                 TEXT        NOT NULL CHECK (action IN
                                           ('STAGED','ACTIVATED','ROTATED',
                                            'RETIRED','REVOKED','KEY_REVOKED')),
        detail                 TEXT        NOT NULL,
        at                     TIMESTAMPTZ NOT NULL DEFAULT NOW());

CREATE TABLE IF NOT EXISTS sentinel_signed_administrative_certificates (
        install_sequence       BIGSERIAL   UNIQUE NOT NULL,
        certificate_sha256     TEXT        PRIMARY KEY
                                           CHECK (certificate_sha256 ~ '^[0-9a-f]{64}$'),
        certificate_id         TEXT        UNIQUE NOT NULL,
        key_id                 TEXT        NOT NULL,
        envelope_bytes         BYTEA       NOT NULL,
        envelope               JSONB       NOT NULL,
        claims                 JSONB       NOT NULL,
        issuer_generation      BIGINT      NOT NULL CHECK (issuer_generation >= 1),
        supersedes_certificate_sha256 TEXT REFERENCES
                                           sentinel_signed_administrative_certificates
                                           (certificate_sha256),
        not_before             TIMESTAMPTZ NOT NULL,
        expires_at             TIMESTAMPTZ NOT NULL,
        status                 TEXT        NOT NULL CHECK (status IN
                                           ('STAGED','ACTIVE','RETIRED','REVOKED')),
        installed_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        activated_at           TIMESTAMPTZ,
        retired_at             TIMESTAMPTZ,
        revoked_at             TIMESTAMPTZ,
        revocation_reason      TEXT,
        CHECK (not_before < expires_at),
        CHECK ((status = 'REVOKED' AND revoked_at IS NOT NULL
                 AND revocation_reason IS NOT NULL)
            OR (status <> 'REVOKED' AND revoked_at IS NULL
                 AND revocation_reason IS NULL)));

CREATE UNIQUE INDEX IF NOT EXISTS
        idx_sentinel_one_active_administrative_certificate
        ON sentinel_signed_administrative_certificates ((1))
        WHERE status = 'ACTIVE';

CREATE TABLE IF NOT EXISTS sentinel_administrative_authority_state (
        id                     INT         PRIMARY KEY CHECK (id = 1),
        generation             BIGINT      NOT NULL CHECK (generation >= 0),
        highest_issuer_generation BIGINT   NOT NULL CHECK
                                           (highest_issuer_generation >= 0),
        active_certificate_sha256 TEXT REFERENCES
                                           sentinel_signed_administrative_certificates
                                           (certificate_sha256),
        updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW());

CREATE TABLE IF NOT EXISTS sentinel_administrative_certificate_events (
        seq                    BIGSERIAL   PRIMARY KEY,
        authority_generation   BIGINT      NOT NULL CHECK (authority_generation >= 0),
        certificate_sha256     TEXT        NOT NULL,
        action                 TEXT        NOT NULL CHECK (action IN
                                           ('STAGED','ACTIVATED','ROTATED',
                                            'RETIRED','REVOKED','KEY_REVOKED')),
        detail                 TEXT        NOT NULL,
        at                     TIMESTAMPTZ NOT NULL DEFAULT NOW());

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
        -- Every new plan stamps explicit rollout authority. There is no
        -- database default that can turn an unstamped legacy row into durable
        -- PINNED/version-1 intent.
        rollout_mode            TEXT        NOT NULL,
        rollout_version         BIGINT      NOT NULL,
        rollout_certificate_sha256 TEXT,
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

ALTER TABLE sentinel_execution_plans
        ADD COLUMN IF NOT EXISTS rollout_mode TEXT;

ALTER TABLE sentinel_execution_plans
        ADD COLUMN IF NOT EXISTS rollout_version BIGINT;

ALTER TABLE sentinel_execution_plans
        ADD COLUMN IF NOT EXISTS rollout_certificate_sha256 TEXT;

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

CREATE TABLE IF NOT EXISTS sentinel_observation_provenance (
        observation_seq   BIGINT PRIMARY KEY REFERENCES sentinel_observations(seq),
        broker            TEXT        NOT NULL,
        broker_account_id TEXT        NOT NULL,
        observed_at       TIMESTAMPTZ NOT NULL,
        positions         JSONB       NOT NULL DEFAULT '[]'::jsonb,
        canonical_payload_sha256 TEXT CHECK (
            canonical_payload_sha256 IS NULL OR
            canonical_payload_sha256 ~ '^[0-9a-f]{64}$'));

ALTER TABLE sentinel_observation_provenance
        ADD COLUMN IF NOT EXISTS positions JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE sentinel_observation_provenance
        ADD COLUMN IF NOT EXISTS canonical_payload_sha256 TEXT CHECK (
            canonical_payload_sha256 IS NULL OR
            canonical_payload_sha256 ~ '^[0-9a-f]{64}$');

CREATE TABLE IF NOT EXISTS sentinel_trial_strategy_evidence (
        session             DATE PRIMARY KEY,
        data_version        BIGINT      NOT NULL,
        state_sha256        TEXT        NOT NULL CHECK (
            state_sha256 ~ '^[0-9a-f]{64}$'),
        strategy_identity   JSONB       NOT NULL,
        decision            JSONB       NOT NULL,
        evidence            JSONB       NOT NULL,
        recent_leadership   JSONB,
        ldrc                JSONB,
        payload_sha256      TEXT        NOT NULL CHECK (
            payload_sha256 ~ '^[0-9a-f]{64}$'),
        recorded_at         TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp());

CREATE OR REPLACE FUNCTION sentinel_refuse_trial_evidence_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'sentinel_trial_strategy_evidence is append-only';
        END; $$;

DO $$
        BEGIN
          IF NOT EXISTS (
              SELECT 1 FROM pg_trigger
               WHERE tgname = 'sentinel_trial_strategy_evidence_append_only'
                 AND tgrelid = 'sentinel_trial_strategy_evidence'::regclass
                 AND NOT tgisinternal) THEN
            CREATE TRIGGER sentinel_trial_strategy_evidence_append_only
              BEFORE UPDATE OR DELETE ON sentinel_trial_strategy_evidence
              FOR EACH ROW EXECUTE FUNCTION
                sentinel_refuse_trial_evidence_mutation();
          END IF;
        END $$;

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

CREATE TABLE IF NOT EXISTS sentinel_automation_control (
        id                  INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
        enabled             BOOLEAN     NOT NULL DEFAULT FALSE,
        generation          BIGINT      NOT NULL DEFAULT 1 CHECK (generation >= 1),
        kill_switch_engaged BOOLEAN     NOT NULL DEFAULT TRUE,
        deployment_id       TEXT,
        broker              TEXT,
        broker_account_id   TEXT,
        takeover_epoch      BIGINT CHECK (takeover_epoch >= 1),
        certificate_sha256  TEXT CHECK (
            certificate_sha256 IS NULL OR certificate_sha256 ~ '^[0-9a-f]{64}$'),
        rollout_mode        TEXT,
        rollout_version     BIGINT CHECK (rollout_version >= 1),
        config_sha256       TEXT CHECK (
            config_sha256 IS NULL OR config_sha256 ~ '^[0-9a-f]{64}$'),
        authority_verdict   TEXT CHECK (
            authority_verdict IS NULL OR authority_verdict IN ('PASS','FAIL')),
        authority_detail    TEXT,
        authority_checked_at TIMESTAMPTZ,
        enabled_at          TIMESTAMPTZ,
        disabled_at         TIMESTAMPTZ,
        updated_at          TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        CHECK (NOT enabled OR (
            deployment_id IS NOT NULL AND broker IS NOT NULL
            AND broker_account_id IS NOT NULL AND takeover_epoch IS NOT NULL
            AND certificate_sha256 IS NOT NULL AND rollout_mode IS NOT NULL
            AND rollout_version IS NOT NULL AND config_sha256 IS NOT NULL)));

ALTER TABLE sentinel_automation_control
        ADD COLUMN IF NOT EXISTS authority_verdict TEXT CHECK (
            authority_verdict IS NULL OR authority_verdict IN ('PASS','FAIL'));

ALTER TABLE sentinel_automation_control
        ADD COLUMN IF NOT EXISTS authority_detail TEXT;

ALTER TABLE sentinel_automation_control
        ADD COLUMN IF NOT EXISTS authority_checked_at TIMESTAMPTZ;

CREATE TABLE IF NOT EXISTS sentinel_automation_events (
        seq                 BIGSERIAL PRIMARY KEY,
        generation          BIGINT      NOT NULL CHECK (generation >= 1),
        action              TEXT        NOT NULL CHECK (action IN (
            'ACTIVATED','DEACTIVATED','KILL_ENGAGED','KILL_RELEASED')),
        actor               TEXT        NOT NULL,
        reason              TEXT        NOT NULL,
        detail              JSONB       NOT NULL DEFAULT '{}'::jsonb,
        at                  TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp());

CREATE INDEX IF NOT EXISTS idx_sentinel_automation_events_generation
        ON sentinel_automation_events (generation,seq);

CREATE TABLE IF NOT EXISTS sentinel_automation_lease (
        id                  INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
        holder_id           TEXT,
        fence_token         BIGINT      NOT NULL DEFAULT 0 CHECK (fence_token >= 0),
        control_generation  BIGINT CHECK (control_generation >= 1),
        acquired_at         TIMESTAMPTZ,
        heartbeat_at        TIMESTAMPTZ,
        expires_at          TIMESTAMPTZ,
        updated_at          TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        CHECK ((holder_id IS NULL AND control_generation IS NULL
                AND acquired_at IS NULL AND heartbeat_at IS NULL
                AND expires_at IS NULL)
            OR (holder_id IS NOT NULL AND control_generation IS NOT NULL
                AND acquired_at IS NOT NULL AND heartbeat_at IS NOT NULL
                AND expires_at IS NOT NULL)));

CREATE TABLE IF NOT EXISTS sentinel_automation_cycles (
        cycle_id                     TEXT PRIMARY KEY,
        state                        TEXT        NOT NULL CHECK (state IN (
            'DISCOVERED','REFRESHING_DATA','PREPARING','PLAN_READY',
            'WAITING_OPEN','EXECUTING','RECONCILING','RETRY_WAIT',
            'SUCCEEDED','MISSED_STATE_ONLY','SUPERSEDED','BLOCKED')),
        decision_session             DATE        NOT NULL,
        effective_session            DATE        NOT NULL,
        deployment_id                TEXT        NOT NULL,
        broker                       TEXT        NOT NULL,
        broker_account_id            TEXT        NOT NULL,
        takeover_epoch               BIGINT      NOT NULL CHECK (takeover_epoch >= 1),
        control_generation           BIGINT      NOT NULL CHECK (control_generation >= 1),
        certificate_sha256           TEXT        NOT NULL CHECK (
            certificate_sha256 ~ '^[0-9a-f]{64}$'),
        rollout_mode                 TEXT        NOT NULL,
        rollout_version              BIGINT      NOT NULL CHECK (rollout_version >= 1),
        config_sha256                TEXT        NOT NULL CHECK (
            config_sha256 ~ '^[0-9a-f]{64}$'),
        decision_close_at            TIMESTAMPTZ NOT NULL,
        prepare_at                   TIMESTAMPTZ NOT NULL,
        execution_open_at            TIMESTAMPTZ NOT NULL,
        execute_at                   TIMESTAMPTZ NOT NULL,
        execution_close_at           TIMESTAMPTZ NOT NULL,
        historical_state_only        BOOLEAN     NOT NULL DEFAULT FALSE,
        plan_id                      TEXT,
        data_version                 TEXT,
        publication_fingerprint      TEXT,
        state_fingerprint            TEXT,
        plan_fingerprint             TEXT,
        last_clean_reconciliation_id TEXT,
        attempt_count                INT         NOT NULL DEFAULT 0
                                             CHECK (attempt_count >= 0),
        next_wake_at                 TIMESTAMPTZ,
        last_fence_token             BIGINT CHECK (last_fence_token >= 1),
        failure_code                 TEXT,
        failure_detail               TEXT,
        diagnostic                   JSONB       NOT NULL DEFAULT '{}'::jsonb,
        created_at                   TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        updated_at                   TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        completed_at                 TIMESTAMPTZ,
        CONSTRAINT sentinel_automation_cycles_generation_key
            UNIQUE (deployment_id,broker,broker_account_id,takeover_epoch,
                    decision_session,control_generation),
        CHECK (decision_close_at <= prepare_at
               AND prepare_at < execution_open_at),
        CHECK (execution_open_at <= execute_at
               AND execute_at < execution_close_at));

ALTER TABLE sentinel_automation_cycles
        ADD COLUMN IF NOT EXISTS historical_state_only BOOLEAN NOT NULL
        DEFAULT FALSE;

CREATE INDEX IF NOT EXISTS idx_sentinel_automation_cycles_due
        ON sentinel_automation_cycles (state,next_wake_at,decision_session);

CREATE TABLE IF NOT EXISTS sentinel_automation_cycle_events (
        seq                 BIGSERIAL PRIMARY KEY,
        cycle_id            TEXT        NOT NULL REFERENCES sentinel_automation_cycles(cycle_id),
        from_state          TEXT,
        to_state            TEXT        NOT NULL,
        control_generation  BIGINT      NOT NULL,
        fence_token         BIGINT      NOT NULL,
        detail              JSONB       NOT NULL DEFAULT '{}'::jsonb,
        at                  TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp());

CREATE INDEX IF NOT EXISTS idx_sentinel_automation_cycle_events
        ON sentinel_automation_cycle_events (cycle_id,seq);

CREATE TABLE IF NOT EXISTS sentinel_alert_outbox (
        alert_id             TEXT PRIMARY KEY,
        idempotency_key      TEXT        NOT NULL UNIQUE,
        schema_version       INT         NOT NULL CHECK (schema_version >= 1),
        event_type           TEXT        NOT NULL,
        severity             TEXT        NOT NULL,
        payload              JSONB       NOT NULL,
        state                TEXT        NOT NULL CHECK (state IN (
            'PENDING','DELIVERING','DELIVERED','DEAD_LETTER')),
        attempt_count        INT         NOT NULL DEFAULT 0
                                          CHECK (attempt_count >= 0),
        max_attempts         INT         NOT NULL CHECK (max_attempts >= 1),
        next_attempt_at      TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        delivery_holder      TEXT,
        delivery_expires_at  TIMESTAMPTZ,
        last_error           TEXT,
        ack_state            TEXT        NOT NULL DEFAULT 'UNACKNOWLEDGED'
                                          CHECK (ack_state IN (
                                              'UNACKNOWLEDGED','ACKNOWLEDGED')),
        acknowledged_by      TEXT,
        acknowledged_at      TIMESTAMPTZ,
        acknowledgement      TEXT,
        created_at           TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        updated_at           TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        delivered_at         TIMESTAMPTZ,
        CHECK ((delivery_holder IS NULL AND delivery_expires_at IS NULL)
            OR (delivery_holder IS NOT NULL AND delivery_expires_at IS NOT NULL)),
        CHECK ((ack_state = 'UNACKNOWLEDGED' AND acknowledged_by IS NULL
                AND acknowledged_at IS NULL AND acknowledgement IS NULL)
            OR (ack_state = 'ACKNOWLEDGED' AND acknowledged_by IS NOT NULL
                AND acknowledged_at IS NOT NULL AND acknowledgement IS NOT NULL)));

CREATE INDEX IF NOT EXISTS idx_sentinel_alert_outbox_due
        ON sentinel_alert_outbox (state,next_attempt_at);

CREATE TABLE IF NOT EXISTS sentinel_alert_delivery_events (
        seq                  BIGSERIAL PRIMARY KEY,
        alert_id             TEXT        NOT NULL REFERENCES sentinel_alert_outbox(alert_id),
        attempt              INT         NOT NULL CHECK (attempt >= 1),
        action               TEXT        NOT NULL CHECK (action IN (
            'CLAIMED','DELIVERED','RETRY_SCHEDULED','DEAD_LETTERED')),
        holder_id            TEXT        NOT NULL,
        error                TEXT,
        at                   TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp());

CREATE INDEX IF NOT EXISTS idx_sentinel_alert_delivery_events
        ON sentinel_alert_delivery_events (alert_id,seq);

DO $$ BEGIN
        IF to_regclass('public.sentinel_alert_health_cursor') IS NULL THEN
            IF EXISTS(SELECT 1 FROM sentinel_alert_outbox
                WHERE idempotency_key LIKE 'automation-health-occurrence:%') THEN
                RAISE EXCEPTION 'notification occurrence history has lost its cursor';
            END IF;
            CREATE TABLE sentinel_alert_health_cursor (
                id INT PRIMARY KEY CHECK (id=1), active_identity TEXT,
                occurrence BIGINT NOT NULL DEFAULT 0 CHECK (occurrence>=0));
            INSERT INTO sentinel_alert_health_cursor(id) VALUES(1);
        END IF;
    END $$;

CREATE TABLE IF NOT EXISTS sentinel_alert_dispatcher_health (
        dispatcher_id        TEXT PRIMARY KEY,
        started_at           TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        heartbeat_at         TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        state                TEXT        NOT NULL CHECK (state IN (
            'STARTING','HEALTHY','DEGRADED','FAILED')),
        last_attempt_at      TIMESTAMPTZ,
        last_success_at      TIMESTAMPTZ,
        consecutive_failures INT         NOT NULL DEFAULT 0
                                        CHECK (consecutive_failures >= 0),
        last_error           TEXT,
        updated_at           TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        CHECK ((state IN ('STARTING','HEALTHY')
                AND consecutive_failures = 0 AND last_error IS NULL)
            OR (state IN ('DEGRADED','FAILED')
                AND consecutive_failures >= 1 AND last_error IS NOT NULL)));

CREATE INDEX IF NOT EXISTS idx_sentinel_alert_dispatcher_health_heartbeat
        ON sentinel_alert_dispatcher_health (heartbeat_at);

CREATE TABLE IF NOT EXISTS sentinel_notification_policy (
        id                    INT PRIMARY KEY CHECK (id = 1),
        web_push_activated_at TIMESTAMPTZ NOT NULL);

CREATE TABLE IF NOT EXISTS sentinel_web_push_subscriptions (
        subscription_id     TEXT PRIMARY KEY CHECK (
            subscription_id ~ '^[0-9a-f]{64}$'),
        endpoint            TEXT        NOT NULL UNIQUE CHECK (
            endpoint ~ '^https://'),
        p256dh              TEXT        NOT NULL CHECK (length(p256dh) > 0),
        auth                TEXT        NOT NULL CHECK (length(auth) > 0),
        user_agent          TEXT        NOT NULL DEFAULT '',
        created_at          TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        refreshed_at        TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        last_successful_push_at TIMESTAMPTZ,
        last_failed_push_at TIMESTAMPTZ,
        retired_at          TIMESTAMPTZ,
        retire_reason       TEXT,
        CHECK ((retired_at IS NULL AND retire_reason IS NULL)
            OR (retired_at IS NOT NULL AND retire_reason IS NOT NULL)));

ALTER TABLE sentinel_web_push_subscriptions
        ADD COLUMN IF NOT EXISTS last_successful_push_at TIMESTAMPTZ;

ALTER TABLE sentinel_web_push_subscriptions
        ADD COLUMN IF NOT EXISTS last_failed_push_at TIMESTAMPTZ;

ALTER TABLE sentinel_web_push_subscriptions
        ADD COLUMN IF NOT EXISTS successor_id TEXT REFERENCES
        sentinel_web_push_subscriptions(subscription_id);

ALTER TABLE sentinel_web_push_subscriptions
        ADD COLUMN IF NOT EXISTS eligible_from TIMESTAMPTZ;

UPDATE sentinel_web_push_subscriptions SET eligible_from=created_at
        WHERE eligible_from IS NULL;

ALTER TABLE sentinel_web_push_subscriptions
        ALTER COLUMN eligible_from SET DEFAULT clock_timestamp(),
        ALTER COLUMN eligible_from SET NOT NULL;

CREATE INDEX IF NOT EXISTS idx_sentinel_web_push_active
        ON sentinel_web_push_subscriptions (refreshed_at,subscription_id)
        WHERE retired_at IS NULL;

CREATE TABLE IF NOT EXISTS sentinel_broker_account_evidence (
        seq                 BIGSERIAL PRIMARY KEY,
        broker              TEXT        NOT NULL,
        broker_account_id   TEXT        NOT NULL,
        status              TEXT        NOT NULL,
        flags               JSONB       NOT NULL,
        equity              NUMERIC     NOT NULL,
        cash                NUMERIC     NOT NULL,
        buying_power        NUMERIC,
        multiplier          NUMERIC,
        observed_at         TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp());

CREATE INDEX IF NOT EXISTS idx_sentinel_broker_account_evidence_latest
        ON sentinel_broker_account_evidence (observed_at DESC,seq DESC);

CREATE TABLE IF NOT EXISTS sentinel_backup_evidence (
        seq                 BIGSERIAL PRIMARY KEY,
        kind                TEXT        NOT NULL CHECK (kind IN (
            'BASE_BACKUP','RUNTIME_CHAIN','RESTORE_DRILL','MAINTENANCE_PROGRESS')),
        evidence_sha256     TEXT        NOT NULL CHECK (
            evidence_sha256 ~ '^[0-9a-f]{64}$'),
        proof               JSONB       NOT NULL,
        observed_at         TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp());

ALTER TABLE sentinel_backup_evidence DROP CONSTRAINT IF EXISTS
        sentinel_backup_evidence_evidence_sha256_key;

ALTER TABLE sentinel_backup_evidence DROP CONSTRAINT IF EXISTS sentinel_backup_evidence_kind_check;

ALTER TABLE sentinel_backup_evidence ADD CONSTRAINT sentinel_backup_evidence_kind_check
        CHECK (kind IN ('BASE_BACKUP','RUNTIME_CHAIN','RESTORE_DRILL','MAINTENANCE_PROGRESS'));

CREATE OR REPLACE FUNCTION sentinel_backup_progress_guard() RETURNS trigger
        LANGUAGE plpgsql AS $$
        DECLARE previous jsonb;
        BEGIN
            IF TG_OP<>'INSERT' AND (OLD.kind='MAINTENANCE_PROGRESS' OR NEW.kind='MAINTENANCE_PROGRESS') THEN
                RAISE EXCEPTION 'backup maintenance progress is append-only';
            END IF;
            IF TG_OP='DELETE' THEN RETURN OLD; END IF;
            IF NEW.kind<>'MAINTENANCE_PROGRESS' THEN RETURN NEW; END IF;
            SELECT proof INTO previous FROM sentinel_backup_evidence
                WHERE kind='MAINTENANCE_PROGRESS' AND proof->>'attempt'=NEW.proof->>'attempt'
                ORDER BY seq DESC LIMIT 1;
            IF previous IS NULL THEN
                IF NEW.proof->>'phase' NOT IN ('BASE_BACKUP','VERIFY_RESTORE') THEN
                    RAISE EXCEPTION 'backup maintenance must start before work';
                END IF;
            ELSIF (previous - 'phase' - 'base_backup') IS DISTINCT FROM
                    (NEW.proof - 'phase' - 'base_backup')
                OR previous->>'phase' IN ('COMPLETE','FAILED')
                OR (previous->>'base_backup' IS DISTINCT FROM NEW.proof->>'base_backup'
                    AND NOT (previous->>'phase'='BASE_BACKUP' AND NEW.proof->>'phase'='VERIFY_RESTORE'))
                OR NOT (NEW.proof->>'phase'='FAILED'
                    OR (previous->>'phase'='BASE_BACKUP' AND NEW.proof->>'phase'='VERIFY_RESTORE')
                    OR (previous->>'phase'='VERIFY_RESTORE' AND NEW.proof->>'phase'='VERIFY_CHAIN')
                    OR (previous->>'phase'='VERIFY_CHAIN' AND NEW.proof->>'phase'='COMPLETE')) THEN
                RAISE EXCEPTION 'backup maintenance identity, deadline or phase changed';
            END IF;
            RETURN NEW;
        END $$;

DROP TRIGGER IF EXISTS sentinel_backup_progress_guard ON sentinel_backup_evidence;

CREATE TRIGGER sentinel_backup_progress_guard BEFORE INSERT OR UPDATE OR DELETE
        ON sentinel_backup_evidence FOR EACH ROW EXECUTE FUNCTION sentinel_backup_progress_guard();

CREATE INDEX IF NOT EXISTS idx_sentinel_backup_evidence_latest
        ON sentinel_backup_evidence (kind,observed_at DESC,seq DESC);

CREATE TABLE IF NOT EXISTS sentinel_web_push_fanouts (
        alert_id             TEXT PRIMARY KEY REFERENCES sentinel_alert_outbox(alert_id),
        recipient_count      INT         NOT NULL CHECK (recipient_count >= 0),
        delivery_required    BOOLEAN     NOT NULL,
        initialized_at       TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp());

CREATE TABLE IF NOT EXISTS sentinel_web_push_deliveries (
        alert_id             TEXT        NOT NULL REFERENCES sentinel_alert_outbox(alert_id),
        subscription_id      TEXT        NOT NULL REFERENCES sentinel_web_push_subscriptions(subscription_id),
        state                TEXT        NOT NULL CHECK (state IN (
            'PENDING','DELIVERED','RETIRED')),
        attempt_count        INT         NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
        last_status_code     INT,
        last_error           TEXT,
        created_at           TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        updated_at           TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        delivered_at         TIMESTAMPTZ,
        PRIMARY KEY (alert_id,subscription_id),
        CHECK ((state = 'DELIVERED' AND delivered_at IS NOT NULL)
            OR (state <> 'DELIVERED' AND delivered_at IS NULL)));

CREATE INDEX IF NOT EXISTS idx_sentinel_web_push_deliveries_pending
        ON sentinel_web_push_deliveries (alert_id,state,subscription_id);

CREATE TABLE IF NOT EXISTS sentinel_automation_service_instances (
        instance_id          TEXT PRIMARY KEY,
        started_at           TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        heartbeat_at         TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
        state                TEXT        NOT NULL,
        next_wake_at         TIMESTAMPTZ,
        last_error           TEXT,
        authority_verdict    TEXT CHECK (
            authority_verdict IS NULL OR authority_verdict IN ('PASS','FAIL')),
        authority_detail     TEXT,
        authority_checked_at TIMESTAMPTZ,
        callback_started_at  TIMESTAMPTZ,
        callback_deadline_at TIMESTAMPTZ,
        updated_at           TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp());

ALTER TABLE sentinel_automation_service_instances
        ADD COLUMN IF NOT EXISTS authority_verdict TEXT CHECK (
            authority_verdict IS NULL OR authority_verdict IN ('PASS','FAIL'));

ALTER TABLE sentinel_automation_service_instances
        ADD COLUMN IF NOT EXISTS authority_detail TEXT;

ALTER TABLE sentinel_automation_service_instances
        ADD COLUMN IF NOT EXISTS authority_checked_at TIMESTAMPTZ;

ALTER TABLE sentinel_automation_service_instances
        ADD COLUMN IF NOT EXISTS callback_started_at TIMESTAMPTZ;

ALTER TABLE sentinel_automation_service_instances
        ADD COLUMN IF NOT EXISTS callback_deadline_at TIMESTAMPTZ;

INSERT INTO sentinel_rollout_state
    (id,mode,version) VALUES (1,'PINNED_1_00',1);

ALTER TABLE sentinel_execution_plans
        ALTER COLUMN rollout_mode DROP DEFAULT;

ALTER TABLE sentinel_execution_plans
        ALTER COLUMN rollout_version DROP DEFAULT;

ALTER TABLE sentinel_execution_plans
        ADD CONSTRAINT sentinel_execution_plan_rollout_authority_ck CHECK (
            (rollout_mode IS NULL
             AND rollout_version IS NULL
             AND rollout_certificate_sha256 IS NULL)
            OR
            (rollout_mode IS NOT NULL
             AND rollout_version IS NOT NULL
             AND rollout_mode IN ('PINNED_1_00','CONTROLLER')
             AND rollout_version >= 1
             AND ((rollout_mode = 'PINNED_1_00'
                   AND rollout_certificate_sha256 IS NULL)
                  OR (rollout_mode = 'CONTROLLER'
                      AND rollout_certificate_sha256 IS NOT NULL))));

CREATE TABLE sentinel_behavioral_schema_migrations (
    version          INT PRIMARY KEY CHECK (version > 0),
    name             TEXT        NOT NULL UNIQUE,
    migration_sha256 TEXT        NOT NULL
                     CHECK (migration_sha256 ~ '^[0-9a-f]{64}$'),
    bootstrap_kind   TEXT        NOT NULL
                     CHECK (bootstrap_kind IN
                            ('NEW','LEGACY','PR84_HEAD_BRIDGE')),
    source_git_oid   TEXT,
    applied_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CHECK ((bootstrap_kind = 'PR84_HEAD_BRIDGE'
            AND source_git_oid IS NOT NULL)
        OR (bootstrap_kind <> 'PR84_HEAD_BRIDGE'
            AND source_git_oid IS NULL)));

INSERT INTO sentinel_behavioral_schema_migrations(version,name,migration_sha256,bootstrap_kind,source_git_oid) VALUES (1,'rollout-authority-v1','0f3bd2d906b032502128683c8e78725946da3fd719d3863ccde43bd484f75be5','NEW',NULL);

INSERT INTO sentinel_automation_control
    (id,enabled,generation,kill_switch_engaged)
    VALUES (1,FALSE,1,TRUE) ON CONFLICT (id) DO NOTHING;

INSERT INTO sentinel_automation_lease
    (id,fence_token) VALUES (1,0) ON CONFLICT (id) DO NOTHING;

INSERT INTO sentinel_notification_policy(id,web_push_activated_at) VALUES (1,clock_timestamp());
