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

import hashlib
import json

_SCHEMA_LOCK = (1_397_050_964, 1_380_928_588)  # ASCII SENT / ROLL.
_SCHEMA_LOCK_TIMEOUT_MS = 2_000

_MIGRATION_VERSION = 1
_MIGRATION_NAME = "rollout-authority-v1"
_MIGRATION_CONTRACT = (
    "sentinel.behavioral-schema/1;rollout-ledger-authority;"
    "empty-or-recognized-fb97372-or-69cdfe8-legacy-seeds-pinned-v1;"
    "6113bffd896824ee24891b0c1aeada60c2b73ef5-bridge-preserves-state;"
    "execution-plan-rollout-columns-have-no-defaults;"
    "plan-authority-check-all-null-or-coherent;"
    "complete-behavioral-catalog-fingerprint")
_MIGRATION_SHA256 = hashlib.sha256(
    _MIGRATION_CONTRACT.encode("ascii")).hexdigest()
_REVIEWED_HEAD = "6113bffd896824ee24891b0c1aeada60c2b73ef5"

_INITIAL_ROLLOUT_STATE = """INSERT INTO sentinel_rollout_state
    (id,mode,version) VALUES (1,'PINNED_1_00',1)"""

_MIGRATION_LEDGER_DDL = """CREATE TABLE sentinel_behavioral_schema_migrations (
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
            AND source_git_oid IS NULL)))"""

# These defaults existed at the reviewed PR head.  Dropping them is both the
# correct plan-authority contract and an independent post-ledger witness: if the
# ledger is later lost, that database cannot masquerade as the one-time 6113
# compatibility bridge, whose exact fingerprint still has both defaults.
_MIGRATION_FINALIZE_DDL = (
    """ALTER TABLE sentinel_execution_plans
        ALTER COLUMN rollout_mode DROP DEFAULT""",
    """ALTER TABLE sentinel_execution_plans
        ALTER COLUMN rollout_version DROP DEFAULT""",
    """ALTER TABLE sentinel_execution_plans
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
                      AND rollout_certificate_sha256 IS NOT NULL))))""",
)


class SchemaMigrationRefused(RuntimeError):
    """Behavioral migration authority is absent, corrupt, or inconsistent.

    Routine startup must never repair this condition.  In particular, table
    absence is not permission to recreate a rollout singleton whose previous
    value may have been CONTROLLER.
    """


_PRE_ROLLOUT_COLUMNS = {
    "sentinel_account_binding": frozenset({
        "id", "deployment_id", "broker", "broker_account_id",
        "takeover_epoch", "ownership_state", "established_at", "updated_at",
        "notes"}),
    "sentinel_ownership_events": frozenset({
        "seq", "state", "at", "detail"}),
    "sentinel_execution_plans": frozenset({
        "plan_id", "decision_session", "effective_session", "target_exposure",
        "data_version", "shadow_snapshot_hash", "sentinel_transition_hash",
        "strategy_fingerprint", "deployment_id", "broker",
        "broker_account_id", "takeover_epoch", "publication_fingerprint",
        "account_nav", "account_cash", "cash_residual",
        "unpriced_securities", "defensive_security", "target_basket",
        "superseded_by", "created_at"}),
    "sentinel_commands": frozenset({
        "client_key", "plan_id", "security_id", "revision", "symbol",
        "broker_instrument_id", "side", "quantity", "state",
        "broker_order_id", "filled_quantity", "filled_average_price", "detail",
        "recovered", "created_at", "updated_at"}),
    "sentinel_command_events": frozenset({
        "seq", "client_key", "from_state", "to_state", "filled_quantity",
        "detail", "at"}),
    "sentinel_fills": frozenset({
        "broker_order_id", "fill_key", "client_key", "quantity", "price",
        "filled_at"}),
    "sentinel_observations": frozenset({
        "seq", "observed_at", "terminal_recovery_through", "completeness",
        "positions", "orders", "runtime_state"}),
    "sentinel_terminal_recovery_watermark": frozenset({
        "id", "broker", "broker_account_id", "processed_through",
        "updated_at"}),
    "sentinel_processed_sessions": frozenset({
        "cursor_name", "session", "state", "updated_at"}),
    "sentinel_cash_flows": frozenset({
        "flow_id", "session", "amount", "detail", "recorded_at"}),
    "sentinel_nav_reconciliations": frozenset({
        "session", "previous_nav", "observed_nav", "marked_pl", "external",
        "unexplained", "attribution", "reconciled_at"}),
}

_COMMAND_AUTHORITY_COLUMNS = frozenset({
    "deployment_id", "broker", "broker_account_id", "takeover_epoch"})
_ROLLOUT_PLAN_COLUMNS = frozenset({
    "rollout_mode", "rollout_version", "rollout_certificate_sha256"})

_ROLLOUT_COLUMNS = {
    "sentinel_system_certificates": frozenset({
        "certificate_sha256", "manifest_bytes", "manifest",
        "allowed_rollout_modes", "installed_at", "revoked_at",
        "revocation_reason"}),
    "sentinel_system_certificate_events": frozenset({
        "seq", "certificate_sha256", "action", "detail", "at"}),
    "sentinel_rollout_state": frozenset({
        "id", "mode", "version", "certificate_sha256", "updated_at"}),
    "sentinel_rollout_events": frozenset({
        "seq", "version", "from_mode", "to_mode", "certificate_sha256",
        "reason", "at"}),
}

_LEDGER_COLUMNS = frozenset({
    "version", "name", "migration_sha256", "bootstrap_kind",
    "source_git_oid", "applied_at"})

_PRE_ROLLOUT_TABLES = frozenset(_PRE_ROLLOUT_COLUMNS)
_ROLLOUT_TABLES = frozenset(_ROLLOUT_COLUMNS)
_LEDGER_TABLE = "sentinel_behavioral_schema_migrations"
_CURRENT_NO_LEDGER_TABLES = _PRE_ROLLOUT_TABLES | _ROLLOUT_TABLES
_CURRENT_TABLES = _CURRENT_NO_LEDGER_TABLES | {_LEDGER_TABLE}

# Semantic pg_catalog hashes, derived from the frozen source fixtures. They are
# stable across the repository-pinned PostgreSQL 16 and test-image PostgreSQL
# 17 because OIDs, owners, attnum order, and physical storage are excluded.
# Constraint/index behavior is included: losing the one-in-flight-command
# unique index, a primary key, or a check is corruption, not a startup repair.
_PRE_ROLLOUT_CATALOG_SHA256 = frozenset({
    # fb97372a166299b23ce7e9fa6951a6304e1c5333
    "a9f792a3e45c38e066d0c9f19b1b6e235463b693ec02f4472d06af1dd4d51263",
    # 69cdfe8085a73bc68cc66da0d8dd3f9cd0bafd88
    "3d62faae998cc6d90a238e73025208c1e5a36dfc13f4a2aceb62dca4438d1020",
})
_REVIEWED_HEAD_CATALOG_SHA256 = (
    "27f9fdc4ef0554cea60f0daa0973a138cc040047bbe98dab943ec5cd3cc753e1")
_TARGET_CATALOG_SHA256 = {
    "NEW": "c28490dc09038f1f6ed228e2a12b44222f2c76d72285395c51ed353646b80065",
    "PR84_HEAD_BRIDGE": (
        "c28490dc09038f1f6ed228e2a12b44222f2c76d72285395c51ed353646b80065"),
    "LEGACY": (
        "99bba3659cac35f9b6e797f861e2dbffd191824bfc6c02f5db66d693cf9cfd66"),
}

# Corpus tables may legitimately be installed before behavioral schema (the
# prepare CLI does exactly that).  They do not disqualify a database from being
# behaviorally empty.  An unknown ``sentinel_*`` table does: it may be evidence
# from a newer or damaged schema this build has no authority to reinterpret.
_FEED_TABLES = frozenset({
    "sentinel_bars", "sentinel_spy_total_return",
    "sentinel_ingest_rejections", "sentinel_rejection_truncation",
    "sentinel_corpus_anomalies", "sentinel_anomaly_observation_events",
    "sentinel_actions", "sentinel_action_generations",
    "sentinel_action_observations", "sentinel_action_generation_events",
    "sentinel_active_actions", "sentinel_active_ingest_rejections",
    "sentinel_universe",
    "sentinel_corpus_publications", "sentinel_bar_split_repairs",
    "sentinel_readiness_snapshots", "sentinel_sep_staging",
})

# Created by the safety-first physical backup path before behavioral schema.
# It is not a behavioral relation, but its exact shape is validated before it
# is excluded; a similarly named or malformed table must not become an escape
# from markerless-schema refusal.
_BACKUP_INFRASTRUCTURE_TABLE = "sentinel_backup_recovery_markers"

# Stage 4 is an additive, separately versioned operational surface layered on
# the PR #84 behavioral-schema ledger.  Its tables are installed/upgraded only
# after the ledgered core has validated, so routine DDL can never repair or
# reinterpret account, plan, command, rollout, or reconciliation authority.
_STAGE4_TABLES = frozenset({
    "sentinel_signed_execution_certificates",
    "sentinel_execution_certificate_lifecycle",
    "sentinel_execution_authority_state",
    "sentinel_execution_certificate_revocations",
    "sentinel_execution_key_revocations",
    "sentinel_execution_certificate_events",
    "sentinel_signed_administrative_certificates",
    "sentinel_administrative_authority_state",
    "sentinel_administrative_certificate_events",
    "sentinel_automation_control",
    "sentinel_automation_events",
    "sentinel_automation_lease",
    "sentinel_automation_cycles",
    "sentinel_automation_cycle_events",
    "sentinel_alert_outbox",
    "sentinel_alert_delivery_events",
    "sentinel_automation_service_instances",
    "sentinel_observation_provenance",
    "sentinel_trial_strategy_evidence",
})

# Additive Stage-4 migrations that historically arrived through ALTER.
# Runtime validation requires these exact witnesses plus every Stage-4 table;
# it never tries to recreate them.  The core behavioral catalog continues to
# receive the stronger closed semantic fingerprint in _validate_ledgered().
_STAGE4_RUNTIME_REQUIRED_COLUMNS = {
    "sentinel_automation_control": frozenset({
        "authority_verdict", "authority_detail", "authority_checked_at"}),
    "sentinel_automation_cycles": frozenset({"historical_state_only"}),
    "sentinel_automation_service_instances": frozenset({
        "authority_verdict", "authority_detail", "authority_checked_at"}),
}

_PLAN_AUTHORITY_CHECK = "sentinel_execution_plan_rollout_authority_ck"

_ROLLOUT_CONSTRAINT_MANIFESTS = {
    "sentinel_rollout_state": frozenset({
        ("p", "primary key (id)", True),
        ("c", "check (id = 1)", True),
        ("c", "check (mode = any (array['PINNED_1_00'::text, "
              "'CONTROLLER'::text]))", True),
        ("c", "check (version >= 1)", True),
        ("c", "check (mode = 'PINNED_1_00'::text and "
              "certificate_sha256 is null or mode = 'CONTROLLER'::text and "
              "certificate_sha256 is not null)", True),
    }),
    "sentinel_rollout_events": frozenset({
        ("p", "primary key (seq)", True),
        ("u", "unique (version)", True),
    }),
    "sentinel_system_certificates": frozenset({
        ("p", "primary key (certificate_sha256)", True),
        ("c", "check (revoked_at is null and revocation_reason is null or "
              "revoked_at is not null and revocation_reason is not null)",
         True),
    }),
    "sentinel_system_certificate_events": frozenset({
        ("p", "primary key (seq)", True),
        ("c", "check (action = any (array['INSTALLED'::text, "
              "'REVOKED'::text]))", True),
    }),
}

_ROLLOUT_DEFAULT_MANIFESTS = {
    "sentinel_rollout_state": {
        "id": "1", "mode": "", "version": "",
        "certificate_sha256": "", "updated_at": "now()",
    },
    "sentinel_rollout_events": {
        "seq": "nextval('sentinel_rollout_events_seq_seq'::regclass)",
        "version": "", "from_mode": "", "to_mode": "",
        "certificate_sha256": "", "reason": "", "at": "now()",
    },
    "sentinel_system_certificates": {
        "certificate_sha256": "", "manifest_bytes": "", "manifest": "",
        "allowed_rollout_modes": "", "installed_at": "now()",
        "revoked_at": "", "revocation_reason": "",
    },
    "sentinel_system_certificate_events": {
        "seq": (
            "nextval('sentinel_system_certificate_events_seq_seq'::regclass)"),
        "certificate_sha256": "", "action": "", "detail": "",
        "at": "now()",
    },
}

_PLAN_AUTHORITY_DEFINITION = (
    "check (rollout_mode is null and rollout_version is null and "
    "rollout_certificate_sha256 is null or rollout_mode is not null and "
    "rollout_version is not null and (rollout_mode = any "
    "(array['PINNED_1_00'::text, 'CONTROLLER'::text])) and "
    "rollout_version >= 1 and (rollout_mode = 'PINNED_1_00'::text and "
    "rollout_certificate_sha256 is null or rollout_mode = "
    "'CONTROLLER'::text and rollout_certificate_sha256 is not null))")

_LEDGER_CONSTRAINT_MANIFEST = frozenset({
    ("p", "primary key (version)", True),
    ("u", "unique (name)", True),
    ("c", "check (version > 0)", True),
    ("c", "check (migration_sha256 ~ '^[0-9a-f]{64}$'::text)", True),
    ("c", "check (bootstrap_kind = any (array['NEW'::text, "
          "'LEGACY'::text, 'PR84_HEAD_BRIDGE'::text]))", True),
    ("c", "check (bootstrap_kind = 'PR84_HEAD_BRIDGE'::text and "
          "source_git_oid is not null or bootstrap_kind <> "
          "'PR84_HEAD_BRIDGE'::text and source_git_oid is null)", True),
})

_INITIAL_AUTOMATION_CONTROL = """INSERT INTO sentinel_automation_control
    (id,enabled,generation,kill_switch_engaged)
    VALUES (1,FALSE,1,TRUE) ON CONFLICT (id) DO NOTHING"""

_INITIAL_AUTOMATION_LEASE = """INSERT INTO sentinel_automation_lease
    (id,fence_token) VALUES (1,0) ON CONFLICT (id) DO NOTHING"""

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
    # SYSTEM CERTIFICATION SUBSTRATE. The exact manifest bytes are retained,
    # not a path to a mounted file. They are deliberately non-authoritative
    # until a separately reviewed trusted issuer/signature verifier exists;
    # runtime execution currently refuses every row before its first broker
    # read.
    # ------------------------------------------------------------------
    """CREATE TABLE IF NOT EXISTS sentinel_system_certificates (
        certificate_sha256  TEXT PRIMARY KEY,
        manifest_bytes      BYTEA       NOT NULL,
        manifest            JSONB       NOT NULL,
        allowed_rollout_modes JSONB     NOT NULL,
        installed_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        revoked_at          TIMESTAMPTZ,
        revocation_reason   TEXT,
        CHECK ((revoked_at IS NULL AND revocation_reason IS NULL)
            OR (revoked_at IS NOT NULL AND revocation_reason IS NOT NULL)))""",
    """CREATE UNIQUE INDEX IF NOT EXISTS idx_sentinel_one_active_certificate
        ON sentinel_system_certificates ((1)) WHERE revoked_at IS NULL""",
    """CREATE TABLE IF NOT EXISTS sentinel_system_certificate_events (
        seq                 BIGSERIAL PRIMARY KEY,
        certificate_sha256  TEXT        NOT NULL,
        action              TEXT        NOT NULL
                            CHECK (action IN ('INSTALLED','REVOKED')),
        detail              TEXT        NOT NULL,
        at                  TIMESTAMPTZ NOT NULL DEFAULT NOW())""",

    # Signed authority is deliberately separate from the retained unsigned
    # manifest substrate above.  An old/restored self-attested row can therefore
    # never become trusted merely because a verifier was added later.
    """CREATE TABLE IF NOT EXISTS sentinel_signed_execution_certificates (
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
        CHECK (not_before < expires_at))""",
    """CREATE TABLE IF NOT EXISTS sentinel_execution_certificate_lifecycle (
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
                 AND revocation_reason IS NULL)))""",
    """CREATE UNIQUE INDEX IF NOT EXISTS
        idx_sentinel_one_active_signed_certificate
        ON sentinel_execution_certificate_lifecycle ((1))
        WHERE status = 'ACTIVE'""",
    """CREATE TABLE IF NOT EXISTS sentinel_execution_authority_state (
        id                     INT         PRIMARY KEY CHECK (id = 1),
        generation             BIGINT      NOT NULL CHECK (generation >= 0),
        highest_issuer_generation BIGINT   NOT NULL CHECK
                                           (highest_issuer_generation >= 0),
        active_certificate_sha256 TEXT REFERENCES
                                           sentinel_signed_execution_certificates
                                           (certificate_sha256),
        updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
    """CREATE TABLE IF NOT EXISTS sentinel_execution_certificate_revocations (
        certificate_sha256     TEXT        PRIMARY KEY REFERENCES
                                           sentinel_signed_execution_certificates
                                           (certificate_sha256),
        reason                 TEXT        NOT NULL CHECK (LENGTH(BTRIM(reason)) > 0),
        revoked_at             TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
    """CREATE TABLE IF NOT EXISTS sentinel_execution_key_revocations (
        key_id                 TEXT        PRIMARY KEY,
        reason                 TEXT        NOT NULL CHECK (LENGTH(BTRIM(reason)) > 0),
        revoked_at             TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
    """CREATE TABLE IF NOT EXISTS sentinel_execution_certificate_events (
        seq                    BIGSERIAL   PRIMARY KEY,
        authority_generation   BIGINT      NOT NULL CHECK (authority_generation >= 0),
        certificate_sha256     TEXT        NOT NULL,
        action                 TEXT        NOT NULL CHECK (action IN
                                           ('STAGED','ACTIVATED','ROTATED',
                                            'RETIRED','REVOKED','KEY_REVOKED')),
        detail                 TEXT        NOT NULL,
        at                     TIMESTAMPTZ NOT NULL DEFAULT NOW())""",

    # Administrative broker access happens before the first account binding,
    # so it cannot borrow the bound execution-certificate singleton above.
    # Its operation vocabulary is disjoint and its lifecycle is independently
    # monotonic.  Exact signed bytes remain the authority in both cases.
    """CREATE TABLE IF NOT EXISTS sentinel_signed_administrative_certificates (
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
                 AND revocation_reason IS NULL)))""",
    """CREATE UNIQUE INDEX IF NOT EXISTS
        idx_sentinel_one_active_administrative_certificate
        ON sentinel_signed_administrative_certificates ((1))
        WHERE status = 'ACTIVE'""",
    """CREATE TABLE IF NOT EXISTS sentinel_administrative_authority_state (
        id                     INT         PRIMARY KEY CHECK (id = 1),
        generation             BIGINT      NOT NULL CHECK (generation >= 0),
        highest_issuer_generation BIGINT   NOT NULL CHECK
                                           (highest_issuer_generation >= 0),
        active_certificate_sha256 TEXT REFERENCES
                                           sentinel_signed_administrative_certificates
                                           (certificate_sha256),
        updated_at             TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
    """CREATE TABLE IF NOT EXISTS sentinel_administrative_certificate_events (
        seq                    BIGSERIAL   PRIMARY KEY,
        authority_generation   BIGINT      NOT NULL CHECK (authority_generation >= 0),
        certificate_sha256     TEXT        NOT NULL,
        action                 TEXT        NOT NULL CHECK (action IN
                                           ('STAGED','ACTIVATED','ROTATED',
                                            'RETIRED','REVOKED','KEY_REVOKED')),
        detail                 TEXT        NOT NULL,
        at                     TIMESTAMPTZ NOT NULL DEFAULT NOW())""",

    # ------------------------------------------------------------------
    # EXPOSURE ROLLOUT. New and recognized pre-rollout databases are
    # deliberately pinned at 1.00 by the versioned migration, never by this
    # replayable DDL and never merely because this table is absent. A
    # controller transition names the certificate that authorized it and every
    # transition increments the durable version, even when the resulting
    # numeric exposure may happen to remain 1.00.
    # ------------------------------------------------------------------
    """CREATE TABLE IF NOT EXISTS sentinel_rollout_state (
        id                  INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
        mode                TEXT        NOT NULL
                            CHECK (mode IN ('PINNED_1_00','CONTROLLER')),
        version             BIGINT      NOT NULL CHECK (version >= 1),
        certificate_sha256  TEXT,
        updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
        CHECK ((mode = 'PINNED_1_00' AND certificate_sha256 IS NULL)
            OR (mode = 'CONTROLLER' AND certificate_sha256 IS NOT NULL)))""",
    """CREATE TABLE IF NOT EXISTS sentinel_rollout_events (
        seq                 BIGSERIAL PRIMARY KEY,
        version             BIGINT      NOT NULL UNIQUE,
        from_mode           TEXT        NOT NULL,
        to_mode             TEXT        NOT NULL,
        certificate_sha256  TEXT,
        reason              TEXT        NOT NULL,
        at                  TIMESTAMPTZ NOT NULL DEFAULT NOW())""",

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
        created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
    """ALTER TABLE sentinel_execution_plans
        ADD COLUMN IF NOT EXISTS deployment_id TEXT""",
    """ALTER TABLE sentinel_execution_plans
        ADD COLUMN IF NOT EXISTS broker TEXT""",
    """ALTER TABLE sentinel_execution_plans
        ADD COLUMN IF NOT EXISTS broker_account_id TEXT""",
    """ALTER TABLE sentinel_execution_plans
        ADD COLUMN IF NOT EXISTS takeover_epoch BIGINT""",
    """ALTER TABLE sentinel_execution_plans
        ADD COLUMN IF NOT EXISTS publication_fingerprint TEXT""",
    """ALTER TABLE sentinel_execution_plans
        ADD COLUMN IF NOT EXISTS account_nav NUMERIC NOT NULL DEFAULT 0""",
    """ALTER TABLE sentinel_execution_plans
        ADD COLUMN IF NOT EXISTS account_cash NUMERIC NOT NULL DEFAULT 0""",
    """ALTER TABLE sentinel_execution_plans
        ADD COLUMN IF NOT EXISTS cash_residual NUMERIC NOT NULL DEFAULT 0""",
    """ALTER TABLE sentinel_execution_plans
        ADD COLUMN IF NOT EXISTS unpriced_securities JSONB NOT NULL
        DEFAULT '[]'::jsonb""",
    """ALTER TABLE sentinel_execution_plans
        ADD COLUMN IF NOT EXISTS defensive_security TEXT""",
    # A genuine legacy table may already contain plans. They stay unstamped and
    # therefore unexecutable; schema migration must not manufacture authority.
    """ALTER TABLE sentinel_execution_plans
        ADD COLUMN IF NOT EXISTS rollout_mode TEXT""",
    """ALTER TABLE sentinel_execution_plans
        ADD COLUMN IF NOT EXISTS rollout_version BIGINT""",
    """ALTER TABLE sentinel_execution_plans
        ADD COLUMN IF NOT EXISTS rollout_certificate_sha256 TEXT""",

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
        updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW())""",
    # Existing databases predate per-command identity. Before adoption, every
    # such row was minted by the one binding present at that time, so the
    # binding is the only deterministic backfill. Commands with no binding fail
    # the NOT NULL conversion instead of being attributed by guesswork.
    """ALTER TABLE sentinel_commands
        ADD COLUMN IF NOT EXISTS deployment_id TEXT""",
    """ALTER TABLE sentinel_commands
        ADD COLUMN IF NOT EXISTS broker TEXT""",
    """ALTER TABLE sentinel_commands
        ADD COLUMN IF NOT EXISTS broker_account_id TEXT""",
    """ALTER TABLE sentinel_commands
        ADD COLUMN IF NOT EXISTS takeover_epoch BIGINT""",
    """UPDATE sentinel_commands c
          SET deployment_id = b.deployment_id,
              broker = b.broker,
              broker_account_id = b.broker_account_id,
              takeover_epoch = b.takeover_epoch
         FROM sentinel_account_binding b
        WHERE b.id = 1
          AND (c.deployment_id IS NULL OR c.broker IS NULL
               OR c.broker_account_id IS NULL OR c.takeover_epoch IS NULL)""",
    """ALTER TABLE sentinel_commands
        ALTER COLUMN deployment_id SET NOT NULL""",
    """ALTER TABLE sentinel_commands
        ALTER COLUMN broker SET NOT NULL""",
    """ALTER TABLE sentinel_commands
        ALTER COLUMN broker_account_id SET NOT NULL""",
    """ALTER TABLE sentinel_commands
        ALTER COLUMN takeover_epoch SET NOT NULL""",
    """ALTER TABLE sentinel_commands
        ADD COLUMN IF NOT EXISTS recovered BOOLEAN NOT NULL DEFAULT FALSE""",
    """ALTER TABLE sentinel_commands
        ADD COLUMN IF NOT EXISTS filled_average_price NUMERIC""",
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
        terminal_recovery_through TIMESTAMPTZ,
        completeness TEXT        NOT NULL,
        positions    JSONB       NOT NULL DEFAULT '{}'::jsonb,
        orders       JSONB       NOT NULL DEFAULT '[]'::jsonb,
        runtime_state TEXT)""",
    """ALTER TABLE sentinel_observations
        ADD COLUMN IF NOT EXISTS terminal_recovery_through TIMESTAMPTZ""",
    # Additive Stage-4 provenance avoids rewriting the core behavioral catalog
    # while binding each new authority-bearing observation to its broker account.
    """CREATE TABLE IF NOT EXISTS sentinel_observation_provenance (
        observation_seq   BIGINT PRIMARY KEY REFERENCES sentinel_observations(seq),
        broker            TEXT        NOT NULL,
        broker_account_id TEXT        NOT NULL,
        observed_at       TIMESTAMPTZ NOT NULL)""",

    # Per-session STRATEGY evidence for the forward paper trial.  Plans, broker
    # observations, commands and fills already have separate durable journals;
    # this table preserves the strategy-side facts that would otherwise be
    # overwritten when SessionState advances to the next close.
    """CREATE TABLE IF NOT EXISTS sentinel_trial_strategy_evidence (
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
        recorded_at         TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp())""",
    """CREATE OR REPLACE FUNCTION sentinel_refuse_trial_evidence_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          RAISE EXCEPTION 'sentinel_trial_strategy_evidence is append-only';
        END; $$""",
    """DO $$
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
        END $$""",

    # A broker response being durable is not proof that it was PROCESSED. This
    # watermark advances only after all Sentinel-keyed terminal rows in the
    # bounded recovery window have been adopted/synchronized. A crash before
    # this one-row commit therefore replays the window instead of skipping it.
    """CREATE TABLE IF NOT EXISTS sentinel_terminal_recovery_watermark (
        id                INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
        broker            TEXT        NOT NULL,
        broker_account_id TEXT        NOT NULL,
        processed_through TIMESTAMPTZ NOT NULL,
        updated_at        TIMESTAMPTZ NOT NULL DEFAULT NOW())""",

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

    # ------------------------------------------------------------------
    # STAGE 4 AUTOMATION.  Installation is inert: the genuinely new table is
    # seeded disabled and killed.  Missing rows in existing singleton tables
    # are corruption and are deliberately NOT repaired by ensure_schema().
    # ------------------------------------------------------------------
    """CREATE TABLE IF NOT EXISTS sentinel_automation_control (
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
            AND rollout_version IS NOT NULL AND config_sha256 IS NOT NULL)))""",
    """ALTER TABLE sentinel_automation_control
        ADD COLUMN IF NOT EXISTS authority_verdict TEXT CHECK (
            authority_verdict IS NULL OR authority_verdict IN ('PASS','FAIL'))""",
    """ALTER TABLE sentinel_automation_control
        ADD COLUMN IF NOT EXISTS authority_detail TEXT""",
    """ALTER TABLE sentinel_automation_control
        ADD COLUMN IF NOT EXISTS authority_checked_at TIMESTAMPTZ""",
    """CREATE TABLE IF NOT EXISTS sentinel_automation_events (
        seq                 BIGSERIAL PRIMARY KEY,
        generation          BIGINT      NOT NULL CHECK (generation >= 1),
        action              TEXT        NOT NULL CHECK (action IN (
            'ACTIVATED','DEACTIVATED','KILL_ENGAGED','KILL_RELEASED')),
        actor               TEXT        NOT NULL,
        reason              TEXT        NOT NULL,
        detail              JSONB       NOT NULL DEFAULT '{}'::jsonb,
        at                  TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp())""",
    """CREATE INDEX IF NOT EXISTS idx_sentinel_automation_events_generation
        ON sentinel_automation_events (generation,seq)""",

    """CREATE TABLE IF NOT EXISTS sentinel_automation_lease (
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
                AND expires_at IS NOT NULL)))""",

    """CREATE TABLE IF NOT EXISTS sentinel_automation_cycles (
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
        UNIQUE (deployment_id,broker,broker_account_id,takeover_epoch,
                decision_session),
        CHECK (decision_close_at <= prepare_at
               AND prepare_at < execution_open_at),
        CHECK (execution_open_at <= execute_at
               AND execute_at < execution_close_at))""",
    """ALTER TABLE sentinel_automation_cycles
        ADD COLUMN IF NOT EXISTS historical_state_only BOOLEAN NOT NULL
        DEFAULT FALSE""",
    """CREATE INDEX IF NOT EXISTS idx_sentinel_automation_cycles_due
        ON sentinel_automation_cycles (state,next_wake_at,decision_session)""",
    """CREATE TABLE IF NOT EXISTS sentinel_automation_cycle_events (
        seq                 BIGSERIAL PRIMARY KEY,
        cycle_id            TEXT        NOT NULL REFERENCES sentinel_automation_cycles(cycle_id),
        from_state          TEXT,
        to_state            TEXT        NOT NULL,
        control_generation  BIGINT      NOT NULL,
        fence_token         BIGINT      NOT NULL,
        detail              JSONB       NOT NULL DEFAULT '{}'::jsonb,
        at                  TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp())""",
    """CREATE INDEX IF NOT EXISTS idx_sentinel_automation_cycle_events
        ON sentinel_automation_cycle_events (cycle_id,seq)""",

    """CREATE TABLE IF NOT EXISTS sentinel_alert_outbox (
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
                AND acknowledged_at IS NOT NULL AND acknowledgement IS NOT NULL)))""",
    """CREATE INDEX IF NOT EXISTS idx_sentinel_alert_outbox_due
        ON sentinel_alert_outbox (state,next_attempt_at)""",
    """CREATE TABLE IF NOT EXISTS sentinel_alert_delivery_events (
        seq                  BIGSERIAL PRIMARY KEY,
        alert_id             TEXT        NOT NULL REFERENCES sentinel_alert_outbox(alert_id),
        attempt              INT         NOT NULL CHECK (attempt >= 1),
        action               TEXT        NOT NULL CHECK (action IN (
            'CLAIMED','DELIVERED','RETRY_SCHEDULED','DEAD_LETTERED')),
        holder_id            TEXT        NOT NULL,
        error                TEXT,
        at                   TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp())""",
    """CREATE INDEX IF NOT EXISTS idx_sentinel_alert_delivery_events
        ON sentinel_alert_delivery_events (alert_id,seq)""",

    """CREATE TABLE IF NOT EXISTS sentinel_automation_service_instances (
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
        updated_at           TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp())""",
    """ALTER TABLE sentinel_automation_service_instances
        ADD COLUMN IF NOT EXISTS authority_verdict TEXT CHECK (
            authority_verdict IS NULL OR authority_verdict IN ('PASS','FAIL'))""",
    """ALTER TABLE sentinel_automation_service_instances
        ADD COLUMN IF NOT EXISTS authority_detail TEXT""",
    """ALTER TABLE sentinel_automation_service_instances
        ADD COLUMN IF NOT EXISTS authority_checked_at TIMESTAMPTZ""",
)


def _operator_refusal(detail: str) -> SchemaMigrationRefused:
    return SchemaMigrationRefused(
        f"behavioral-schema operator action required: {detail}. Routine "
        "startup did not repair schema or reset durable rollout intent")


def _normal_sql(value: object) -> str:
    """Normalize keywords/spacing without changing quoted SQL semantics."""
    source = str(value or "").strip()
    output: list[str] = []
    quote: str | None = None
    pending_space = False
    index = 0
    while index < len(source):
        char = source[index]
        if quote is not None:
            output.append(char)
            if char == quote:
                if index + 1 < len(source) and source[index + 1] == quote:
                    output.append(source[index + 1])
                    index += 1
                else:
                    quote = None
            index += 1
            continue
        if char in {"'", '"'}:
            if pending_space and output:
                output.append(" ")
            pending_space = False
            quote = char
            output.append(char)
        elif char.isspace():
            pending_space = True
        else:
            if pending_space and output:
                output.append(" ")
            pending_space = False
            output.append(char.lower())
        index += 1
    return "".join(output).strip()


def _read_catalog(cur):
    """Return a semantic public-schema view with no OID/attnum assumptions."""
    cur.execute(
        "SELECT c.relname,c.relkind,c.relpersistence,c.relispartition,"
        " c.relrowsecurity,c.relforcerowsecurity"
        " FROM pg_catalog.pg_class c"
        " JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace"
        " WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f')")
    relations = {
        str(name): (str(kind), str(persistence), bool(is_partition),
                    bool(row_security), bool(force_row_security))
        for (name, kind, persistence, is_partition, row_security,
             force_row_security) in cur.fetchall()
    }

    cur.execute(
        "SELECT c.relname,a.attname,"
        " pg_catalog.format_type(a.atttypid,a.atttypmod),a.attnotnull,"
        " pg_catalog.pg_get_expr(d.adbin,d.adrelid)"
        " FROM pg_catalog.pg_class c"
        " JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace"
        " JOIN pg_catalog.pg_attribute a ON a.attrelid=c.oid"
        " LEFT JOIN pg_catalog.pg_attrdef d"
        "   ON d.adrelid=c.oid AND d.adnum=a.attnum"
        " WHERE n.nspname='public'"
        "   AND c.relkind IN ('r','p','v','m','f')"
        "   AND a.attnum>0 AND NOT a.attisdropped")
    columns: dict[str, dict[str, tuple[str, bool, object]]] = {}
    for table, name, type_name, not_null, default in cur.fetchall():
        columns.setdefault(str(table), {})[str(name)] = (
            str(type_name), bool(not_null), default)

    cur.execute(
        "SELECT c.relname,k.conname,k.contype,"
        " pg_catalog.pg_get_constraintdef(k.oid,true),k.convalidated"
        " FROM pg_catalog.pg_constraint k"
        " JOIN pg_catalog.pg_class c ON c.oid=k.conrelid"
        " JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace"
        " WHERE n.nspname='public'")
    constraints: dict[str, list[tuple[str, str, str, bool]]] = {}
    for table, name, kind, definition, validated in cur.fetchall():
        constraints.setdefault(str(table), []).append(
            (str(name), str(kind), str(definition), bool(validated)))

    cur.execute(
        "SELECT t.relname,i.relname,pg_catalog.pg_get_indexdef(i.oid),"
        " x.indisunique,x.indisvalid,x.indisready,x.indislive"
        " FROM pg_catalog.pg_index x"
        " JOIN pg_catalog.pg_class i ON i.oid=x.indexrelid"
        " JOIN pg_catalog.pg_class t ON t.oid=x.indrelid"
        " JOIN pg_catalog.pg_namespace n ON n.oid=t.relnamespace"
        " WHERE n.nspname='public'")
    indexes: dict[str, dict[str, tuple[str, bool, bool, bool, bool]]] = {}
    for (table, name, definition, unique, valid, ready,
         live) in cur.fetchall():
        indexes.setdefault(str(table), {})[str(name)] = (
            str(definition), bool(unique), bool(valid), bool(ready), bool(live))

    cur.execute(
        "SELECT c.relname,t.tgname,pg_catalog.pg_get_triggerdef(t.oid,true),"
        " t.tgenabled"
        " FROM pg_catalog.pg_trigger t"
        " JOIN pg_catalog.pg_class c ON c.oid=t.tgrelid"
        " JOIN pg_catalog.pg_namespace n ON n.oid=c.relnamespace"
        " WHERE n.nspname='public' AND NOT t.tgisinternal")
    triggers: dict[str, dict[str, tuple[str, str]]] = {}
    for table, name, definition, enabled in cur.fetchall():
        triggers.setdefault(str(table), {})[str(name)] = (
            str(definition), str(enabled))
    return relations, columns, constraints, indexes, triggers


def _behavioral_relations(relations) -> set[str]:
    return {
        name for name in relations
        if (name.startswith("sentinel_")
            and name not in _FEED_TABLES
            and name != _BACKUP_INFRASTRUCTURE_TABLE
            and name not in _STAGE4_TABLES)
    }


def _validate_backup_infrastructure(
        relations, columns, constraints, indexes, triggers) -> None:
    table = _BACKUP_INFRASTRUCTURE_TABLE
    if table not in relations:
        return
    if relations.get(table) != ("r", "p", False, False, False):
        raise _operator_refusal(
            "backup recovery-marker relation is not the exact known table")
    observed = columns.get(table, {})
    if frozenset(observed) != frozenset({"marker", "created_at"}):
        raise _operator_refusal(
            "backup recovery-marker relation has an unknown column fingerprint")
    marker = observed["marker"]
    created = observed["created_at"]
    if marker[:2] != ("text", True) or _normal_sql(marker[2]):
        raise _operator_refusal(
            "backup recovery-marker relation has invalid marker semantics")
    if (created[:2] != ("timestamp with time zone", True)
            or _normal_sql(created[2]) != "now()"):
        raise _operator_refusal(
            "backup recovery-marker relation has invalid timestamp semantics")
    if _constraint_manifest(constraints, table) != frozenset({
            ("p", "primary key (marker)", True)}):
        raise _operator_refusal(
            "backup recovery-marker relation has an unknown constraint fingerprint")
    expected_index_name = "sentinel_backup_recovery_markers_pkey"
    table_indexes = indexes.get(table, {})
    index = table_indexes.get(expected_index_name)
    expected_index = (
        "create unique index sentinel_backup_recovery_markers_pkey on "
        "public.sentinel_backup_recovery_markers using btree (marker)")
    if (frozenset(table_indexes) != frozenset({expected_index_name})
            or index is None or _normal_sql(index[0]) != expected_index
            or index[1:] != (True, True, True, True)):
        raise _operator_refusal(
            "backup recovery-marker relation has an unknown index fingerprint")
    if triggers.get(table):
        raise _operator_refusal(
            "backup recovery-marker relation has an unexpected trigger")


def _semantic_catalog_sha256(
        relations, columns, constraints, indexes, triggers, tables) -> str:
    """Hash physical behavior while ignoring OIDs and column order.

    Historical ``CREATE`` and ``ALTER`` paths assign different ``attnum``
    positions to the same logical columns.  Names, types, nullability,
    defaults, constraint semantics/validation, and index definitions are the
    behavior that startup must recognize exactly; owners and catalog OIDs are
    deployment-local and deliberately excluded.
    """
    manifest = []
    for table in sorted(tables):
        manifest.append(["relation", table, relations.get(table)])
        for name, (type_name, not_null, default) in sorted(
                columns.get(table, {}).items()):
            manifest.append([
                "column", table, name, type_name, bool(not_null),
                _normal_sql(default),
            ])
        for name, kind, definition, validated in sorted(
                constraints.get(table, [])):
            manifest.append([
                "constraint", table, name, kind,
                _normal_sql(definition), bool(validated),
            ])
        for name, index in sorted(indexes.get(table, {}).items()):
            definition, unique, valid, ready, live = index
            manifest.append([
                "index", table, name, _normal_sql(definition), unique, valid,
                ready, live,
            ])
        for name, (definition, enabled) in sorted(
                triggers.get(table, {}).items()):
            manifest.append([
                "trigger", table, name, _normal_sql(definition), enabled,
            ])
    payload = json.dumps(
        manifest, sort_keys=False, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(payload.encode("ascii")).hexdigest()


def _expected_current_columns(*, ledger: bool) -> dict[str, frozenset[str]]:
    expected = dict(_PRE_ROLLOUT_COLUMNS)
    expected["sentinel_commands"] = (
        expected["sentinel_commands"] | _COMMAND_AUTHORITY_COLUMNS)
    expected["sentinel_execution_plans"] = (
        expected["sentinel_execution_plans"] | _ROLLOUT_PLAN_COLUMNS)
    expected.update(_ROLLOUT_COLUMNS)
    if ledger:
        expected[_LEDGER_TABLE] = _LEDGER_COLUMNS
    return expected


def _require_exact_columns(
        relations: dict[str, str],
        columns: dict[str, dict[str, tuple[str, bool, object]]],
        expected: dict[str, frozenset[str]], *, label: str) -> None:
    for table, wanted in expected.items():
        if relations.get(table) not in {
                ("r", "p", False, False, False),
                ("p", "p", False, False, False)}:
            raise _operator_refusal(
                f"{label} relation {table!r} is missing or is not a table")
        observed = frozenset(columns.get(table, {}))
        if observed != wanted:
            missing = sorted(wanted - observed)
            extra = sorted(observed - wanted)
            raise _operator_refusal(
                f"{label} column fingerprint differs for {table}: "
                f"missing={missing}, unexpected={extra}")


def _require_column(
        columns: dict[str, dict[str, tuple[str, bool, object]]],
        table: str, name: str, type_name: str, *,
        not_null: bool | None = None) -> tuple[str, bool, object]:
    try:
        observed = columns[table][name]
    except KeyError as exc:                                  # pragma: no cover
        raise _operator_refusal(
            f"migration physical schema is missing {table}.{name}") from exc
    if observed[0] != type_name or (
            not_null is not None and observed[1] is not not_null):
        raise _operator_refusal(
            f"migration physical schema has invalid {table}.{name}: "
            f"type={observed[0]!r}, not_null={observed[1]!r}")
    return observed


def _validate_common_authority_columns(columns) -> None:
    for name, type_name in (
            ("deployment_id", "text"), ("broker", "text"),
            ("broker_account_id", "text"), ("takeover_epoch", "bigint")):
        _require_column(
            columns, "sentinel_commands", name, type_name, not_null=True)

    _require_column(
        columns, "sentinel_execution_plans", "rollout_mode", "text")
    _require_column(
        columns, "sentinel_execution_plans", "rollout_version", "bigint")
    _require_column(
        columns, "sentinel_execution_plans",
        "rollout_certificate_sha256", "text", not_null=False)

    critical = {
        "sentinel_rollout_state": (
            ("id", "integer", True), ("mode", "text", True),
            ("version", "bigint", True),
            ("certificate_sha256", "text", False),
            ("updated_at", "timestamp with time zone", True)),
        "sentinel_rollout_events": (
            ("seq", "bigint", True), ("version", "bigint", True),
            ("from_mode", "text", True), ("to_mode", "text", True),
            ("certificate_sha256", "text", False),
            ("reason", "text", True),
            ("at", "timestamp with time zone", True)),
        "sentinel_system_certificates": (
            ("certificate_sha256", "text", True),
            ("manifest_bytes", "bytea", True), ("manifest", "jsonb", True),
            ("allowed_rollout_modes", "jsonb", True),
            ("installed_at", "timestamp with time zone", True),
            ("revoked_at", "timestamp with time zone", False),
            ("revocation_reason", "text", False)),
        "sentinel_system_certificate_events": (
            ("seq", "bigint", True),
            ("certificate_sha256", "text", True),
            ("action", "text", True), ("detail", "text", True),
            ("at", "timestamp with time zone", True)),
    }
    for table, fields in critical.items():
        for name, type_name, not_null in fields:
            _require_column(
                columns, table, name, type_name, not_null=not_null)


def _constraint_manifest(constraints, table: str):
    return frozenset(
        (kind, _normal_sql(definition), valid)
        for _name, kind, definition, valid in constraints.get(table, []))


def _validate_rollout_structure(constraints, indexes) -> None:
    for table, expected in _ROLLOUT_CONSTRAINT_MANIFESTS.items():
        if _constraint_manifest(constraints, table) != expected:
            raise _operator_refusal(
                f"rollout migration constraint fingerprint differs for {table}")
    index = indexes.get("sentinel_system_certificates", {}).get(
        "idx_sentinel_one_active_certificate")
    expected_index = (
        "create unique index idx_sentinel_one_active_certificate on "
        "public.sentinel_system_certificates using btree ((1)) where "
        "(revoked_at is null)")
    if (index is None or _normal_sql(index[0]) != expected_index
            or index[1:] != (True, True, True, True)):
        raise _operator_refusal(
            "rollout certificate active-row index is missing or corrupt")


def _validate_rollout_defaults(columns) -> None:
    for table, expected in _ROLLOUT_DEFAULT_MANIFESTS.items():
        for name, default in expected.items():
            observed = _normal_sql(columns[table][name][2])
            if observed != default:
                raise _operator_refusal(
                    "rollout migration default fingerprint differs for "
                    f"{table}.{name}")


def _plan_witness(constraints) -> tuple[str, str, str, bool] | None:
    for item in constraints.get("sentinel_execution_plans", []):
        if item[0] == _PLAN_AUTHORITY_CHECK:
            return item
    return None


def _validate_reviewed_head_catalog(columns, constraints, indexes) -> None:
    _validate_common_authority_columns(columns)
    _validate_rollout_structure(constraints, indexes)
    _validate_rollout_defaults(columns)
    mode = _require_column(
        columns, "sentinel_execution_plans", "rollout_mode", "text",
        not_null=True)
    version = _require_column(
        columns, "sentinel_execution_plans", "rollout_version", "bigint",
        not_null=True)
    certificate = _require_column(
        columns, "sentinel_execution_plans",
        "rollout_certificate_sha256", "text", not_null=False)
    if _normal_sql(mode[2]) != "'PINNED_1_00'::text":
        raise _operator_refusal(
            "migration authority is missing and the rollout-mode default does "
            "not match the exact 6113 compatibility fingerprint")
    if _normal_sql(version[2]) != "1":
        raise _operator_refusal(
            "migration authority is missing and the rollout-version default "
            "does not match the exact 6113 compatibility fingerprint")
    if certificate[2] is not None:
        raise _operator_refusal(
            "migration authority is missing and the rollout-certificate "
            "default does not match the exact 6113 compatibility fingerprint")
    if _plan_witness(constraints) is not None:
        raise _operator_refusal(
            "migration authority is missing after the post-ledger structural "
            "witness was installed")


def _validate_ledger_catalog(columns, constraints) -> None:
    critical = (
        ("version", "integer", True), ("name", "text", True),
        ("migration_sha256", "text", True),
        ("bootstrap_kind", "text", True), ("source_git_oid", "text", False),
        ("applied_at", "timestamp with time zone", True),
    )
    for name, type_name, not_null in critical:
        _require_column(
            columns, _LEDGER_TABLE, name, type_name, not_null=not_null)
    if _constraint_manifest(
            constraints, _LEDGER_TABLE) != _LEDGER_CONSTRAINT_MANIFEST:
        raise _operator_refusal(
            "behavioral migration ledger constraint fingerprint is corrupt")
    if _normal_sql(columns[_LEDGER_TABLE]["applied_at"][2]) != "now()":
        raise _operator_refusal(
            "behavioral migration ledger applied-at default is corrupt")


def _validate_target_catalog(
        columns, constraints, indexes, *, bootstrap_kind: str) -> None:
    _validate_common_authority_columns(columns)
    _validate_rollout_structure(constraints, indexes)
    _validate_rollout_defaults(columns)
    mode = _require_column(
        columns, "sentinel_execution_plans", "rollout_mode", "text")
    version = _require_column(
        columns, "sentinel_execution_plans", "rollout_version", "bigint")
    certificate = _require_column(
        columns, "sentinel_execution_plans",
        "rollout_certificate_sha256", "text", not_null=False)
    if (mode[2] is not None or version[2] is not None
            or certificate[2] is not None):
        raise _operator_refusal(
            "migration ledger and execution-plan rollout defaults disagree")
    expected_not_null = bootstrap_kind != "LEGACY"
    if mode[1] != version[1] or mode[1] is not expected_not_null:
        raise _operator_refusal(
            "execution-plan rollout authority nullability disagrees with the "
            f"{bootstrap_kind} migration record")
    witness = _plan_witness(constraints)
    if witness is None or witness[1] != "c" or not witness[3]:
        raise _operator_refusal(
            "post-ledger execution-plan authority witness is missing or corrupt")
    if _normal_sql(witness[2]) != _PLAN_AUTHORITY_DEFINITION:
        raise _operator_refusal(
            "post-ledger execution-plan authority witness has unknown semantics")


def _validate_rollout_history(cur) -> None:
    cur.execute(
        "SELECT id,mode,version,certificate_sha256"
        " FROM public.sentinel_rollout_state ORDER BY id")
    states = cur.fetchall()
    if len(states) != 1 or int(states[0][0]) != 1:
        raise _operator_refusal(
            "the rollout singleton is missing or duplicated; it was not seeded")
    _id, raw_mode, raw_version, raw_certificate = states[0]
    mode = str(raw_mode)
    version = int(raw_version)
    certificate = str(raw_certificate) if raw_certificate else None
    if mode not in {"PINNED_1_00", "CONTROLLER"} or version < 1:
        raise _operator_refusal("the durable rollout singleton is corrupt")
    if ((mode == "PINNED_1_00" and certificate is not None)
            or (mode == "CONTROLLER" and certificate is None)):
        raise _operator_refusal(
            "the durable rollout singleton has incoherent certificate authority")

    cur.execute(
        "SELECT version,from_mode,to_mode,certificate_sha256,reason"
        " FROM public.sentinel_rollout_events ORDER BY version")
    events = cur.fetchall()
    if [int(row[0]) for row in events] != list(range(2, version + 1)):
        raise _operator_refusal(
            "rollout event versions are not the complete chain from 2 through "
            f"the singleton version {version}")

    snapshots: dict[int, tuple[str, str | None]] = {1: ("PINNED_1_00", None)}
    prior_mode, prior_certificate = snapshots[1]
    referenced_certificates: set[str] = set()
    signed_lineage: dict[str, tuple[str | None, int]] = {}
    cur.execute(
        "SELECT to_regclass('public.sentinel_signed_execution_certificates')")
    if cur.fetchone()[0] is not None:
        cur.execute(
            "SELECT certificate_sha256,supersedes_certificate_sha256,"
            " issuer_generation"
            " FROM public.sentinel_signed_execution_certificates")
        signed_lineage = {
            str(raw_sha): (
                str(raw_supersedes) if raw_supersedes else None,
                int(raw_generation))
            for raw_sha, raw_supersedes, raw_generation in cur.fetchall()
        }
    for raw_event_version, raw_from, raw_to, raw_cert, raw_reason in events:
        event_version = int(raw_event_version)
        from_mode, to_mode = str(raw_from), str(raw_to)
        event_certificate = str(raw_cert) if raw_cert else None
        # A renewal/rotation may keep CONTROLLER only when the durable
        # signed-certificate lineage proves it is the exact successor. Merely
        # changing a SHA would let unrelated or legacy certificates manufacture
        # rollout history that activate_signed_certificate() could never create.
        prior_signed = signed_lineage.get(prior_certificate or "")
        event_signed = signed_lineage.get(event_certificate or "")
        same_mode_rotation = (
            from_mode == to_mode == "CONTROLLER"
            and prior_certificate is not None
            and event_certificate is not None
            and event_certificate != prior_certificate
            and prior_signed is not None
            and event_signed is not None
            and event_signed[0] == prior_certificate
            and event_signed[1] > prior_signed[1])
        if (from_mode != prior_mode
                or to_mode not in {"PINNED_1_00", "CONTROLLER"}
                or (to_mode == from_mode and not same_mode_rotation)):
            raise _operator_refusal(
                f"rollout event version {event_version} breaks the mode chain")
        if not str(raw_reason).strip():
            raise _operator_refusal(
                f"rollout event version {event_version} has no reason")
        if ((to_mode == "PINNED_1_00" and event_certificate is not None)
                or (to_mode == "CONTROLLER" and event_certificate is None)):
            raise _operator_refusal(
                f"rollout event version {event_version} has incoherent "
                "certificate authority")
        if event_certificate is not None:
            referenced_certificates.add(event_certificate)
        prior_mode, prior_certificate = to_mode, event_certificate
        snapshots[event_version] = (prior_mode, prior_certificate)
    if (prior_mode, prior_certificate) != (mode, certificate):
        raise _operator_refusal(
            "rollout event history does not terminate at the durable singleton")

    if referenced_certificates:
        cur.execute(
            "SELECT certificate_sha256"
            " FROM public.sentinel_system_certificates")
        known = {str(row[0]) for row in cur.fetchall()}
        cur.execute(
            "SELECT to_regclass('public.sentinel_signed_execution_certificates')")
        if cur.fetchone()[0] is not None:
            cur.execute(
                "SELECT certificate_sha256"
                " FROM public.sentinel_signed_execution_certificates")
            known.update(str(row[0]) for row in cur.fetchall())
        missing = sorted(referenced_certificates - known)
        if missing:
            raise _operator_refusal(
                f"rollout history references missing certificate(s): {missing}")

    cur.execute(
        "SELECT plan_id,rollout_mode,rollout_version,"
        " rollout_certificate_sha256"
        " FROM public.sentinel_execution_plans ORDER BY plan_id")
    for plan_id, raw_plan_mode, raw_plan_version, raw_plan_cert in cur.fetchall():
        triple = (raw_plan_mode, raw_plan_version, raw_plan_cert)
        if triple == (None, None, None):
            continue
        if raw_plan_mode is None or raw_plan_version is None:
            raise _operator_refusal(
                f"execution plan {plan_id!r} has a partial rollout stamp")
        plan_version = int(raw_plan_version)
        plan_certificate = str(raw_plan_cert) if raw_plan_cert else None
        expected = snapshots.get(plan_version)
        if expected != (str(raw_plan_mode), plan_certificate):
            raise _operator_refusal(
                f"execution plan {plan_id!r} names rollout authority that "
                "does not exist in durable history")


def _read_and_validate_ledger(cur) -> str:
    cur.execute(
        "SELECT version,name,migration_sha256,bootstrap_kind,source_git_oid"
        " FROM public.sentinel_behavioral_schema_migrations"
        " ORDER BY version")
    rows = cur.fetchall()
    if len(rows) != 1:
        raise _operator_refusal(
            "behavioral migration authority is empty, gapped, future, or "
            f"duplicated (observed versions {[row[0] for row in rows]})")
    version, name, migration_sha, bootstrap_kind, source_oid = rows[0]
    if (int(version) != _MIGRATION_VERSION or str(name) != _MIGRATION_NAME
            or str(migration_sha) != _MIGRATION_SHA256):
        raise _operator_refusal(
            "behavioral migration authority has an unknown version, name, or "
            "checksum")
    kind = str(bootstrap_kind)
    source = str(source_oid) if source_oid else None
    if kind not in {"NEW", "LEGACY", "PR84_HEAD_BRIDGE"}:
        raise _operator_refusal(
            "behavioral migration authority has an unknown bootstrap kind")
    if ((kind == "PR84_HEAD_BRIDGE" and source != _REVIEWED_HEAD)
            or (kind != "PR84_HEAD_BRIDGE" and source is not None)):
        raise _operator_refusal(
            "behavioral migration authority has an invalid source fingerprint")
    return kind


def _classify_markerless(
        relations, columns, constraints, indexes, triggers) -> str:
    observed = _behavioral_relations(relations)
    if not observed:
        return "NEW"

    if observed == _PRE_ROLLOUT_TABLES:
        expected = dict(_PRE_ROLLOUT_COLUMNS)
        command_columns = frozenset(columns.get("sentinel_commands", {}))
        accepted_commands = {
            _PRE_ROLLOUT_COLUMNS["sentinel_commands"],
            (_PRE_ROLLOUT_COLUMNS["sentinel_commands"]
             | _COMMAND_AUTHORITY_COLUMNS),
        }
        if command_columns not in accepted_commands:
            raise _operator_refusal(
                "recognized pre-rollout relations have a partial or unknown "
                "command-authority fingerprint")
        expected["sentinel_commands"] = command_columns
        _require_exact_columns(
            relations, columns, expected, label="pre-rollout migration")
        if command_columns & _COMMAND_AUTHORITY_COLUMNS:
            _validate_common_legacy_command_columns(columns)
        catalog_sha = _semantic_catalog_sha256(
            relations, columns, constraints, indexes, triggers,
            _PRE_ROLLOUT_TABLES)
        if catalog_sha not in _PRE_ROLLOUT_CATALOG_SHA256:
            raise _operator_refusal(
                "pre-rollout behavioral catalog does not match a recognized "
                f"source fingerprint (observed {catalog_sha})")
        return "LEGACY"

    if observed == _CURRENT_NO_LEDGER_TABLES:
        expected = _expected_current_columns(ledger=False)
        _require_exact_columns(
            relations, columns, expected, label="6113 compatibility bridge")
        _validate_reviewed_head_catalog(columns, constraints, indexes)
        catalog_sha = _semantic_catalog_sha256(
            relations, columns, constraints, indexes, triggers,
            _CURRENT_NO_LEDGER_TABLES)
        if catalog_sha != _REVIEWED_HEAD_CATALOG_SHA256:
            raise _operator_refusal(
                "markerless current catalog is not the exact 6113 "
                f"compatibility fingerprint (observed {catalog_sha})")
        return "PR84_HEAD_BRIDGE"

    rollout_evidence = sorted(observed & _ROLLOUT_TABLES)
    unknown = sorted(observed - _CURRENT_NO_LEDGER_TABLES - {_LEDGER_TABLE})
    raise _operator_refusal(
        "markerless schema is not empty, a recognized pre-rollout schema, or "
        "the intact 6113 bridge; partial rollout evidence="
        f"{rollout_evidence}, unknown behavioral relations={unknown}, "
        f"observed relations={sorted(observed)}")


def _validate_common_legacy_command_columns(columns) -> None:
    for name, type_name in (
            ("deployment_id", "text"), ("broker", "text"),
            ("broker_account_id", "text"), ("takeover_epoch", "bigint")):
        _require_column(
            columns, "sentinel_commands", name, type_name, not_null=True)


def _validate_ledgered(cur, catalog) -> None:
    relations, columns, constraints, indexes, triggers = catalog
    observed = _behavioral_relations(relations)
    if observed != _CURRENT_TABLES:
        missing = sorted(_CURRENT_TABLES - observed)
        if "sentinel_rollout_state" in missing:
            raise _operator_refusal(
                "the rollout state table is missing after migration")
        raise _operator_refusal(
            "migration ledger and physical behavioral schema disagree: "
            f"missing={missing}, unexpected={sorted(observed - _CURRENT_TABLES)}")
    expected = _expected_current_columns(ledger=True)
    _require_exact_columns(
        relations, columns, expected, label="ledgered behavioral schema")
    _validate_ledger_catalog(columns, constraints)
    bootstrap_kind = _read_and_validate_ledger(cur)
    _validate_target_catalog(
        columns, constraints, indexes, bootstrap_kind=bootstrap_kind)
    catalog_sha = _semantic_catalog_sha256(
        relations, columns, constraints, indexes, triggers, _CURRENT_TABLES)
    if catalog_sha != _TARGET_CATALOG_SHA256[bootstrap_kind]:
        raise _operator_refusal(
            "migration ledger and complete behavioral catalog fingerprint "
            f"disagree (observed {catalog_sha})")
    _validate_rollout_history(cur)


def _validate_stage4_runtime(cur, catalog) -> None:
    relations, columns, _constraints, _indexes, _triggers = catalog
    missing = sorted(_STAGE4_TABLES - set(relations))
    if missing:
        raise _operator_refusal(
            "Stage-4 operational schema is not installed completely; "
            f"missing relations={missing}. Run the explicit schema migration "
            "before unattended automation")
    malformed = sorted(
        table for table in _STAGE4_TABLES
        if relations.get(table) != ("r", "p", False, False, False))
    if malformed:
        raise _operator_refusal(
            f"Stage-4 operational relations are not exact ordinary tables: "
            f"{malformed}")
    for table, required in _STAGE4_RUNTIME_REQUIRED_COLUMNS.items():
        absent = sorted(required - set(columns.get(table, {})))
        if absent:
            raise _operator_refusal(
                f"Stage-4 relation {table} is missing migration columns "
                f"{absent}; routine startup will not repair authority schema")
    for table in ("sentinel_automation_control", "sentinel_automation_lease"):
        cur.execute(f"SELECT COUNT(*) FROM public.{table} WHERE id=1")
        if int(cur.fetchone()[0]) != 1:
            raise _operator_refusal(
                f"Stage-4 singleton {table} is missing; routine startup will "
                "not guess or reseed authority-bearing state")


def _apply_v1(cur, bootstrap_kind: str) -> None:
    if bootstrap_kind in {"NEW", "LEGACY"}:
        for statement in DDL:
            cur.execute(statement)
        # A plain INSERT is intentional. Classification under the advisory lock
        # proved that seeding is authorized; conflict suppression would hide a
        # contradiction in that proof.
        cur.execute(_INITIAL_ROLLOUT_STATE)
    elif bootstrap_kind != "PR84_HEAD_BRIDGE":             # pragma: no cover
        raise AssertionError(bootstrap_kind)

    # These statements are deliberately after the seed. A late fault proves
    # PostgreSQL rolls seed, DDL, and witness back as one transaction.
    for statement in _MIGRATION_FINALIZE_DDL:
        cur.execute(statement)
    cur.execute(_MIGRATION_LEDGER_DDL)
    source_oid = _REVIEWED_HEAD if bootstrap_kind == "PR84_HEAD_BRIDGE" else None
    cur.execute(
        "INSERT INTO public.sentinel_behavioral_schema_migrations"
        " (version,name,migration_sha256,bootstrap_kind,source_git_oid)"
        " VALUES (%s,%s,%s,%s,%s)",
        (_MIGRATION_VERSION, _MIGRATION_NAME, _MIGRATION_SHA256,
         bootstrap_kind, source_oid))


def require_runtime_schema(conn) -> None:
    """Validate the established behavioral/Stage-4 schema without DDL.

    This is the unattended/runtime gate.  Missing migration evidence is an
    operator refusal, never permission to CREATE/ALTER a hot authority table.
    A local lock timeout bounds even catalog reads queued behind an explicit
    migration so status/heartbeat paths fail visibly rather than hang forever.
    """
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"SET LOCAL lock_timeout TO '{_SCHEMA_LOCK_TIMEOUT_MS}ms'")
            cur.execute("SET LOCAL search_path TO public, pg_temp")
            catalog = _read_catalog(cur)
            relations, columns, constraints, indexes, triggers = catalog
            _validate_backup_infrastructure(
                relations, columns, constraints, indexes, triggers)
            if _LEDGER_TABLE not in relations:
                raise _operator_refusal(
                    "behavioral schema migration is not installed; runtime "
                    "validation cannot bootstrap or migrate it")
            _validate_ledgered(cur, catalog)
            _validate_stage4_runtime(cur, catalog)
        # Read-only proof: leave no transaction open across scheduler sleeps.
        conn.rollback()
    except BaseException:
        conn.rollback()
        raise


def ensure_schema(conn) -> None:
    """Validate or atomically install behavioral migration authority.

    The transaction-scoped lock is acquired before *any* catalog or ledger
    read. New, recognized legacy, and exact reviewed-head bootstrap decisions
    therefore serialize with DDL, the one permitted rollout seed, the
    structural witness, and the ledger row. A missing current table/row/marker
    is durable-state corruption, never permission for routine startup to repair
    or reset it.
    """
    try:
        with conn.cursor() as cur:
            # Listing public before pg_temp keeps a temporary relation from
            # diverting historical unqualified DDL. Deliberately OMIT
            # pg_catalog: PostgreSQL then searches it implicitly *before* the
            # explicit path, so a public function/operator/type cannot shadow
            # built-ins while constraints/defaults are parsed or deparsed.
            cur.execute("SET LOCAL search_path TO public, pg_temp")
            # Explicit migration may need AccessExclusive DDL locks, but it may
            # never wait without bound and become the queue head for control,
            # heartbeat, status, or emergency fencing traffic.
            cur.execute(
                f"SET LOCAL lock_timeout TO '{_SCHEMA_LOCK_TIMEOUT_MS}ms'")
            cur.execute(
                "SELECT pg_advisory_xact_lock(%s,%s)", _SCHEMA_LOCK)
            catalog = _read_catalog(cur)
            relations, columns, constraints, indexes, triggers = catalog
            _validate_backup_infrastructure(
                relations, columns, constraints, indexes, triggers)
            automation_control_exists = (
                "sentinel_automation_control" in relations)
            automation_lease_exists = "sentinel_automation_lease" in relations

            if _LEDGER_TABLE in relations:
                _validate_ledgered(cur, catalog)
            else:
                bootstrap_kind = _classify_markerless(
                    relations, columns, constraints, indexes, triggers)
                if bootstrap_kind == "PR84_HEAD_BRIDGE":
                    _validate_rollout_history(cur)
                _apply_v1(cur, bootstrap_kind)
            # The behavioral core is now either freshly migrated or validated.
            # Only at this point may additive signed-authority/automation DDL
            # run. Table absence authorizes its inert singleton seed; row
            # absence in an existing table remains corruption and is not
            # repaired.
            for statement in DDL:
                cur.execute(statement)
            if not automation_control_exists:
                cur.execute(_INITIAL_AUTOMATION_CONTROL)
            if not automation_lease_exists:
                cur.execute(_INITIAL_AUTOMATION_LEASE)
            final_catalog = _read_catalog(cur)
            _validate_backup_infrastructure(*final_catalog)
            _validate_ledgered(cur, final_catalog)
            _validate_stage4_runtime(cur, final_catalog)
        conn.commit()
    except BaseException:
        # PostgreSQL DDL is transactional. Explicit rollback also releases the
        # xact advisory lock and leaves startup callers with a usable connection.
        conn.rollback()
        raise
