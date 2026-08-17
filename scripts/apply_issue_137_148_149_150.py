#!/usr/bin/env python3
"""Apply the reviewed #137/#148/#149/#150 patch on the isolated feature branch.

Temporary branch bootstrap only.  The targeted GitHub Actions job removes this
file and its workflow before committing the tested product diff.
"""
from __future__ import annotations

from pathlib import Path
import textwrap

ROOT = Path(__file__).resolve().parents[1]


def replace(path: str, old: str, new: str, *, count: int = 1) -> None:
    target = ROOT / path
    data = target.read_text()
    observed = data.count(old)
    if observed != count:
        raise SystemExit(
            f"{path}: expected {count} occurrence(s), found {observed}: {old[:100]!r}")
    target.write_text(data.replace(old, new, count))


def replace_all(path: str, old: str, new: str, *, minimum: int = 1) -> None:
    target = ROOT / path
    data = target.read_text()
    observed = data.count(old)
    if observed < minimum:
        raise SystemExit(
            f"{path}: expected at least {minimum} occurrence(s), found {observed}")
    target.write_text(data.replace(old, new))


# ---------------------------------------------------------------------------
# Document the two operational decisions before changing executable code.
# ---------------------------------------------------------------------------
replace(
    "docs/sentinel-stage-4-automation.md",
    """therefore cannot make the kill command unavailable. It performs no broker
mutation and does not cancel an already-sent request.

Changing the binding takeover epoch, certificate, rollout version, or automation
""",
    """therefore cannot make the kill command unavailable. It performs no broker
mutation and does not cancel an already-sent request.

The supported emergency host path is `scripts/sentinel-emergency-kill.sh`. It
uses only the ordinary Sentinel runtime plus the behavioral PostgreSQL target;
it deliberately does **not** load the backup overlay, authorized-runtime
overlay, broker credentials, Git/image certification variables, backup-root
attestation, WAL write probes, or a leader lease. Database unavailability or a
corrupt/missing control singleton may still refuse because that row is the
fence authority. Ordinary startup and backup operations keep their existing
durability preflight unchanged.

Unattended runtime startup is also not a schema-migration surface. Once Stage 4
is installed, automation uses a read-only behavioral-schema validation gate.
Schema installation/upgrade remains explicit and serialized; its PostgreSQL
lock wait is bounded so an attempted migration fails visibly rather than
becoming an unbounded AccessExclusive queue head in front of heartbeat, status,
or emergency control traffic.

Changing the binding takeover epoch, certificate, rollout version, or automation
""",
)
replace(
    "docs/sentinel-paper-observation.md",
    """Candidate creation is database-read-only and broker-free. Omit
`--expires-at` for the 31-day default; an instant more than 35 days after
`--not-before` is refused.
""",
    """Candidate creation is database-read-only and broker-free. The command
captures one UTC lifecycle reference **before** readiness and the 253-session
warmup are computed; `issued_at` and the `not_before >= issued_at` check use
that same reference, so construction time cannot consume the operator's
validity margin. A correctly signed future-dated certificate may be installed
as `STAGED` before `not_before`, but activation and all ordinary authority remain
refused until `not_before` is reached. Omit `--expires-at` for the 31-day
default; an instant more than 35 days after `--not-before` is refused.
""",
)

# ---------------------------------------------------------------------------
# #148: make readiness depth bounded, and do not recompute full readiness on
# every preparation-time guarded broker read while the caller holds the
# publication shared pin.
# ---------------------------------------------------------------------------
replace(
    "sentinel/feed/readiness.py",
    """    total = _q1(conn, \"SELECT COUNT(DISTINCT session) FROM sentinel_bars b\"
                      f\" WHERE {_VISIBLE_BARS}\")
    r.add(\"sessions\", PASS, f\"{total:,} distinct sessions to {frontier}\", total)

    # A single valid bar used to establish the newest session and barely moved
""",
    """    # Session DEPTH is an operational warmup fact, not a lifetime corpus
    # statistic.  The old COUNT(DISTINCT session) filtered every visible bar in
    # the ~23M-row relation and was repeated by preparation guards.  Read only
    # the deliberately generous recent window that continuity already needs,
    # and reuse the same session axis below.  Publication visibility is kept
    # byte-for-byte identical, so rows from an unpublished ingest stay hidden.
    with conn.cursor() as cur:
        cur.execute(\"SELECT DISTINCT session FROM sentinel_bars b\"
                    \" WHERE session >= %s\"
                    f\"   AND {_VISIBLE_BARS} ORDER BY session\",
                    (_window_start(frontier),))
        actual = [str(x[0]) for x in cur.fetchall()]
    total = len(actual)
    r.add(\"sessions\", PASS,
          f\"{total:,} visible sessions in the bounded readiness window to \"
          f\"{frontier}\", total)

    # A single valid bar used to establish the newest session and barely moved
""",
)
replace(
    "sentinel/feed/readiness.py",
    """    with conn.cursor() as cur:
        cur.execute(\"SELECT DISTINCT session FROM sentinel_bars b\"
                    \" WHERE session >= %s\"
                    f\"   AND {_VISIBLE_BARS} ORDER BY session\",
                    (_window_start(frontier),))
        actual = [str(x[0]) for x in cur.fetchall()]

    try:
""",
    """    # `actual` was loaded once above and is intentionally reused here.
    # A preparation operation therefore has one bounded session-axis scan, not
    # a lifetime count followed by a second continuity scan.
    try:
""",
)
replace(
    "sentinel/paper.py",
    """    _readiness_or_refuse(conn, now_et=now_et)
    latest_closed = calendar.latest_closed_session(now_et)
""",
    """    # Full readiness was computed once by prepare_paper_plan while the
    # originating connection holds publication.pinned()'s session-level shared
    # advisory lock.  That lock excludes ingest/publication writers for the
    # whole preparation. Fresh guard connections still recheck the cheap
    # publication/frontier/calendar identity before every broker read, but must
    # not rescan the corpus just to prove a fact the retained pin cannot change.
    latest_closed = calendar.latest_closed_session(now_et)
""",
)

# Operational paper paths consume an already installed behavioral schema. They
# are not migration commands and must never issue hot authority-table DDL.
replace_all(
    "sentinel/paper.py", "schema.ensure_schema(conn)",
    "schema.require_runtime_schema(conn)", minimum=3)
replace_all(
    "sentinel/automation_runtime.py", "schema.ensure_schema(conn)",
    "schema.require_runtime_schema(conn)", minimum=4)

# ---------------------------------------------------------------------------
# #150: bounded explicit migration plus a read-only established-schema gate.
# ---------------------------------------------------------------------------
replace(
    "sentinel/schema.py",
    """_SCHEMA_LOCK = (1_397_050_964, 1_380_928_588)  # ASCII SENT / ROLL.

_MIGRATION_VERSION = 1
""",
    """_SCHEMA_LOCK = (1_397_050_964, 1_380_928_588)  # ASCII SENT / ROLL.
_SCHEMA_LOCK_TIMEOUT_MS = 2_000

_MIGRATION_VERSION = 1
""",
)
replace(
    "sentinel/schema.py",
    """_PLAN_AUTHORITY_CHECK = \"sentinel_execution_plan_rollout_authority_ck\"
""",
    """# Additive Stage-4 migrations that historically arrived through ALTER.
# Runtime validation requires these exact witnesses plus every Stage-4 table;
# it never tries to recreate them.  The core behavioral catalog continues to
# receive the stronger closed semantic fingerprint in _validate_ledgered().
_STAGE4_RUNTIME_REQUIRED_COLUMNS = {
    \"sentinel_automation_control\": frozenset({
        \"authority_verdict\", \"authority_detail\", \"authority_checked_at\"}),
    \"sentinel_automation_cycles\": frozenset({\"historical_state_only\"}),
    \"sentinel_automation_service_instances\": frozenset({
        \"authority_verdict\", \"authority_detail\", \"authority_checked_at\"}),
}

_PLAN_AUTHORITY_CHECK = \"sentinel_execution_plan_rollout_authority_ck\"
""",
)
replace(
    "sentinel/schema.py",
    """def _apply_v1(cur, bootstrap_kind: str) -> None:
""",
    """def _validate_stage4_runtime(cur, catalog) -> None:
    relations, columns, _constraints, _indexes, _triggers = catalog
    missing = sorted(_STAGE4_TABLES - set(relations))
    if missing:
        raise _operator_refusal(
            \"Stage-4 operational schema is not installed completely; \"
            f\"missing relations={missing}. Run the explicit schema migration \"
            \"before unattended automation\")
    malformed = sorted(
        table for table in _STAGE4_TABLES
        if relations.get(table) != (\"r\", \"p\", False, False, False))
    if malformed:
        raise _operator_refusal(
            f\"Stage-4 operational relations are not exact ordinary tables: \"
            f\"{malformed}\")
    for table, required in _STAGE4_RUNTIME_REQUIRED_COLUMNS.items():
        absent = sorted(required - set(columns.get(table, {})))
        if absent:
            raise _operator_refusal(
                f\"Stage-4 relation {table} is missing migration columns \"
                f\"{absent}; routine startup will not repair authority schema\")
    for table in (\"sentinel_automation_control\", \"sentinel_automation_lease\"):
        cur.execute(f\"SELECT COUNT(*) FROM public.{table} WHERE id=1\")
        if int(cur.fetchone()[0]) != 1:
            raise _operator_refusal(
                f\"Stage-4 singleton {table} is missing; routine startup will \"
                \"not guess or reseed authority-bearing state\")


def _apply_v1(cur, bootstrap_kind: str) -> None:
""",
)
replace(
    "sentinel/schema.py",
    """def ensure_schema(conn) -> None:
    \"\"\"Validate or atomically install behavioral migration authority.
""",
    """def require_runtime_schema(conn) -> None:
    \"\"\"Validate the established behavioral/Stage-4 schema without DDL.

    This is the unattended/runtime gate.  Missing migration evidence is an
    operator refusal, never permission to CREATE/ALTER a hot authority table.
    A local lock timeout bounds even catalog reads queued behind an explicit
    migration so status/heartbeat paths fail visibly rather than hang forever.
    \"\"\"
    try:
        with conn.cursor() as cur:
            cur.execute(
                f\"SET LOCAL lock_timeout TO '{_SCHEMA_LOCK_TIMEOUT_MS}ms'\")
            cur.execute(\"SET LOCAL search_path TO public, pg_temp\")
            catalog = _read_catalog(cur)
            relations, columns, constraints, indexes, triggers = catalog
            _validate_backup_infrastructure(
                relations, columns, constraints, indexes, triggers)
            if _LEDGER_TABLE not in relations:
                raise _operator_refusal(
                    \"behavioral schema migration is not installed; runtime \"
                    \"validation cannot bootstrap or migrate it\")
            _validate_ledgered(cur, catalog)
            _validate_stage4_runtime(cur, catalog)
        # Read-only proof: leave no transaction open across scheduler sleeps.
        conn.rollback()
    except BaseException:
        conn.rollback()
        raise


def ensure_schema(conn) -> None:
    \"\"\"Validate or atomically install behavioral migration authority.
""",
)
replace(
    "sentinel/schema.py",
    """            cur.execute(\"SET LOCAL search_path TO public, pg_temp\")
            cur.execute(
                \"SELECT pg_advisory_xact_lock(%s,%s)\", _SCHEMA_LOCK)
""",
    """            cur.execute(\"SET LOCAL search_path TO public, pg_temp\")
            # Explicit migration may need AccessExclusive DDL locks, but it may
            # never wait without bound and become the queue head for control,
            # heartbeat, status, or emergency fencing traffic.
            cur.execute(
                f\"SET LOCAL lock_timeout TO '{_SCHEMA_LOCK_TIMEOUT_MS}ms'\")
            cur.execute(
                \"SELECT pg_advisory_xact_lock(%s,%s)\", _SCHEMA_LOCK)
""",
)
replace(
    "sentinel/schema.py",
    """            final_catalog = _read_catalog(cur)
            _validate_backup_infrastructure(*final_catalog)
            _validate_ledgered(cur, final_catalog)
        conn.commit()
""",
    """            final_catalog = _read_catalog(cur)
            _validate_backup_infrastructure(*final_catalog)
            _validate_ledgered(cur, final_catalog)
            _validate_stage4_runtime(cur, final_catalog)
        conn.commit()
""",
)

# A leader proof owns a short read transaction.  It must not survive the call
# and hold AccessShare locks while the scheduler sleeps or performs broker work.
replace(
    "sentinel/automation/store.py",
    """def require_leader(conn, permit: LeaderPermit) -> LeaderPermit:
    \"\"\"Fresh database-time fence check for a control-sensitive boundary.\"\"\"
    with conn.cursor() as cur:
        cur.execute(
            \"SELECT l.acquired_at,l.expires_at\"
            \" FROM sentinel_automation_control AS c\"
            \" JOIN sentinel_automation_lease AS l ON l.id=1\"
            \" WHERE c.id=1 AND c.enabled AND NOT c.kill_switch_engaged\"
            \" AND c.generation=%s AND l.control_generation=c.generation\"
            \" AND l.holder_id=%s AND l.fence_token=%s\"
            \" AND l.expires_at > clock_timestamp()\",
            (permit.control_generation, permit.holder_id, permit.fence_token))
        row = cur.fetchone()
        if row is None:
            cur.execute(
                \"SELECT EXISTS(SELECT 1 FROM sentinel_automation_control\"
                \" WHERE id=1),EXISTS(SELECT 1 FROM sentinel_automation_lease\"
                \" WHERE id=1)\")
            control_exists, lease_exists = cur.fetchone()
            if not control_exists or not lease_exists:
                raise MissingAutomationState(
                    \"automation control or lease singleton is missing\")
            raise StaleLeaderRefused(
                \"caller does not hold the live automation fencing token\")
    return permit.model_copy(update={\"acquired_at\": row[0], \"expires_at\": row[1]})
""",
    """def require_leader(conn, permit: LeaderPermit) -> LeaderPermit:
    \"\"\"Fresh database-time fence check with no surviving read transaction.

    Callers use the returned permit only as a proof. Mutating store operations
    perform their own conditional SQL fence after this boundary, so this
    function deliberately owns and closes its read transaction instead of
    holding AccessShare locks across scheduler sleeps or broker work.
    \"\"\"
    try:
        with conn.cursor() as cur:
            cur.execute(
                \"SELECT l.acquired_at,l.expires_at\"
                \" FROM sentinel_automation_control AS c\"
                \" JOIN sentinel_automation_lease AS l ON l.id=1\"
                \" WHERE c.id=1 AND c.enabled AND NOT c.kill_switch_engaged\"
                \" AND c.generation=%s AND l.control_generation=c.generation\"
                \" AND l.holder_id=%s AND l.fence_token=%s\"
                \" AND l.expires_at > clock_timestamp()\",
                (permit.control_generation, permit.holder_id, permit.fence_token))
            row = cur.fetchone()
            if row is None:
                cur.execute(
                    \"SELECT EXISTS(SELECT 1 FROM sentinel_automation_control\"
                    \" WHERE id=1),EXISTS(SELECT 1 FROM sentinel_automation_lease\"
                    \" WHERE id=1)\")
                control_exists, lease_exists = cur.fetchone()
                if not control_exists or not lease_exists:
                    raise MissingAutomationState(
                        \"automation control or lease singleton is missing\")
                raise StaleLeaderRefused(
                    \"caller does not hold the live automation fencing token\")
        result = permit.model_copy(
            update={\"acquired_at\": row[0], \"expires_at\": row[1]})
        conn.rollback()
        return result
    except BaseException:
        conn.rollback()
        raise
""",
)

# ---------------------------------------------------------------------------
# #137: one lifecycle reference precedes expensive candidate work; installation
# authenticates and stages future authority, activation still enforces time.
# ---------------------------------------------------------------------------
replace(
    "sentinel/authority.py",
    """    if instant < not_before:
        raise AuthorityRefused(\"signed certificate is not yet valid\")
""",
    """    # Installation authenticates bytes and durable bindings; it does not
    # confer authority. Future-dated certificates may therefore be staged so
    # operators can complete review/rotation ahead of not_before. Every active
    # load/activation still calls this with for_install=False and refuses early.
    if instant < not_before and not for_install:
        raise AuthorityRefused(\"signed certificate is not yet valid\")
""",
)
replace(
    "sentinel/observation_authority.py",
    """    if not_before < now:
        raise AuthorityRefused(
            \"paper-observation not_before cannot precede candidate creation\")
""",
    """    if not_before < now:
        raise AuthorityRefused(
            \"paper-observation not_before \"
            f\"{_instant_text(not_before)} precedes lifecycle reference \"
            f\"{_instant_text(now)}\")
""",
)
replace(
    "sentinel/__main__.py",
    """    conn = feed_store.connect(config.database_url)
    try:
        schema.ensure_schema(conn)
        ready, _frontier = _closed_preview_frontier(conn)
""",
    """    # One reference is captured before any readiness/warmup work.  A
    # multi-minute candidate build must not consume its own not_before margin.
    lifecycle_reference = datetime.now(ZoneInfo(\"UTC\")).replace(microsecond=0)
    try:
        not_before = _utc_cli_instant(args.not_before, label=\"not_before\")
        expires_at = (_utc_cli_instant(args.expires_at, label=\"expires_at\")
                      if args.expires_at else None)
        if not_before < lifecycle_reference:
            raise ValueError(
                f\"not_before {args.not_before} precedes candidate lifecycle \"
                f\"reference {lifecycle_reference.strftime('%Y-%m-%dT%H:%M:%SZ')}\")
    except ValueError as exc:
        return _paper_refused(exc)

    conn = feed_store.connect(config.database_url)
    try:
        schema.require_runtime_schema(conn)
        ready, _frontier = _closed_preview_frontier(conn)
""",
)
replace(
    "sentinel/__main__.py",
    """            reviewer=args.reviewer, ticket=args.ticket,
            not_before=_utc_cli_instant(
                args.not_before, label=\"not_before\"),
            expires_at=(_utc_cli_instant(args.expires_at, label=\"expires_at\")
                        if args.expires_at else None))
""",
    """            reviewer=args.reviewer, ticket=args.ticket,
            not_before=not_before, expires_at=expires_at,
            now=lifecycle_reference)
""",
)

# Hot paper/automation CLI entrypoints validate rather than migrate.
for old in (
    """        feed_store.ensure_schema(conn)\n        schema.ensure_schema(conn)\n        resolve_security_id = paper.build_security_resolver(conn, args.through)\n""",
    """        feed_store.ensure_schema(conn)\n        schema.ensure_schema(conn)\n        result = paper.current_paper_plan(conn, base_url=config.base_url)\n""",
    """        feed_store.ensure_schema(conn)\n        schema.ensure_schema(conn)\n        resolve_security_id = paper.build_security_resolver(\n""",
):
    replace(
        "sentinel/__main__.py", old,
        old.replace("schema.ensure_schema(conn)",
                    "schema.require_runtime_schema(conn)"))
replace(
    "sentinel/__main__.py",
    """    conn = feed_store.connect(config.database_url)
    try:
        schema.ensure_schema(conn)
    finally:
        conn.close()
    stop = asyncio.Event()
""",
    """    conn = feed_store.connect(config.database_url)
    try:
        schema.require_runtime_schema(conn)
    finally:
        conn.close()
    stop = asyncio.Event()
""",
)

# #149: the emergency kill itself bypasses schema migration/validation; direct
# control-row mutation is the minimal durable fence. Deactivation remains
# validated but read-only with respect to schema.
replace(
    "sentinel/__main__.py",
    """    conn = feed_store.connect(config.database_url)
    try:
        schema.ensure_schema(conn)
        # Emergency fencing must remain available while an executor owns the
""",
    """    conn = feed_store.connect(config.database_url)
    try:
        if not kill:
            schema.require_runtime_schema(conn)
        # Emergency fencing must remain available while an executor owns the
""",
)

# ---------------------------------------------------------------------------
# Dedicated emergency host path: ordinary image, current database, no backup or
# authorized overlays and no broker/certification environment requirements.
# ---------------------------------------------------------------------------
emergency = ROOT / "scripts/sentinel-emergency-kill.sh"
emergency.write_text(textwrap.dedent(r'''\
    #!/usr/bin/env bash
    # Minimal risk-reducing automation fence. Deliberately bypasses backup and
    # authorized-runtime preflight; it does not contact a broker or mutate one.
    set -euo pipefail

    cd "$(dirname "$0")/.."

    CANONICAL="docker-compose.sentinel.yml"
    PYTHON="${SENTINEL_HOST_PYTHON:-${SENTINEL_PYTHON:-python3}}"
    GENERATED=""

    cleanup() {
      [ -z "$GENERATED" ] || rm -f "$GENERATED"
    }
    trap cleanup EXIT

    "$PYTHON" scripts/sentinel_host_python.py >/dev/null || {
      echo "REFUSED: host Python is incompatible; minimum Python is 3.8.15" >&2
      exit 1
    }
    [ -n "${SENTINEL_POSTGRES_PASSWORD:-}" ] || {
      echo "REFUSED: SENTINEL_POSTGRES_PASSWORD is required to reach the durable automation fence" >&2
      exit 2
    }
    if [ "${SENTINEL_FORCE_CPU_LIMITS:-0}" = "1" ] && \
       [ "${SENTINEL_FORCE_NO_CPU_LIMITS:-0}" = "1" ]; then
      echo "REFUSED: CPU-limit force modes are mutually exclusive" >&2
      exit 2
    fi

    COMPOSE_ARGS=(-f "$CANONICAL")
    if [ "${SENTINEL_FORCE_NO_CPU_LIMITS:-0}" = "1" ]; then
      GENERATED="$(mktemp "${TMPDIR:-/tmp}/sentinel-emergency-nocpu.XXXXXX.yml")"
      "$PYTHON" scripts/sentinel_strip_cpu_limits.py "$CANONICAL" "$GENERATED" >&2
      COMPOSE_ARGS=(--project-directory "$(pwd -P)" -f "$GENERATED")
    elif [ "${SENTINEL_FORCE_CPU_LIMITS:-0}" != "1" ]; then
      CAPS="$("$PYTHON" scripts/sentinel_host_capabilities.py --json 2>/dev/null || echo '{}')"
      USABLE="$(printf '%s' "$CAPS" | "$PYTHON" -c \
        'import json,sys
    try: d=json.load(sys.stdin)
    except ValueError: d={}
    print("1" if d.get("cpu_limits_usable", True) else "0")' \
        2>/dev/null || echo 1)"
      if [ "$USABLE" != "1" ]; then
        GENERATED="$(mktemp "${TMPDIR:-/tmp}/sentinel-emergency-nocpu.XXXXXX.yml")"
        "$PYTHON" scripts/sentinel_strip_cpu_limits.py "$CANONICAL" "$GENERATED" >&2
        COMPOSE_ARGS=(--project-directory "$(pwd -P)" -f "$GENERATED")
      fi
    fi

    # --no-deps is intentional: an emergency fence may use only the already
    # running behavioral PostgreSQL service. Starting/recreating deployment or
    # backup services would add exactly the dependencies this path removes.
    docker compose "${COMPOSE_ARGS[@]}" --profile cli run --rm --no-deps sentinel \
      engage-paper-automation-kill-switch "$@"
'''))
emergency.chmod(0o755)

# ---------------------------------------------------------------------------
# Focused regression/falsifier coverage for all four issues.
# ---------------------------------------------------------------------------
test_path = ROOT / "tests/sentinel/test_runtime_regressions_137_148_149_150.py"
test_path.write_text(textwrap.dedent(r'''\
    from __future__ import annotations

    import hashlib
    import inspect
    import os
    from datetime import date, datetime, timezone
    from pathlib import Path
    from types import SimpleNamespace
    import subprocess

    import pytest

    from sentinel import authority, binding, paper, schema
    import sentinel.__main__ as sentinel_cli
    from sentinel.automation import store as automation_store
    import sentinel.automation_runtime as automation_runtime
    from sentinel.execution.guarded import BrokerOperation, PaperPreparationGrant
    from sentinel.feed import readiness
    from sentinel.feed import store as feed_store
    from tests.support.postgres import _EphemeralPostgres, drop_public_tables
    from tests.sentinel import test_signed_authority as signed_fx


    ROOT = Path(__file__).resolve().parents[2]


    @pytest.fixture(scope="module")
    def pg():
        try:
            server = _EphemeralPostgres()
            server.start()
        except Exception as exc:  # noqa: BLE001
            pytest.skip(f"ephemeral Postgres unavailable: {exc}")
        try:
            yield server
        finally:
            server.stop()


    @pytest.fixture()
    def behavioral(pg):
        conn = feed_store.connect(pg.sync_dsn)
        drop_public_tables(conn)
        schema.ensure_schema(conn)
        try:
            yield conn
        finally:
            conn.rollback()
            conn.close()
            cleanup = feed_store.connect(pg.sync_dsn)
            try:
                drop_public_tables(cleanup)
            finally:
                cleanup.close()


    def _enable(conn):
        config = automation_runtime.config_from_env({})
        control_binding = SimpleNamespace(
            deployment_id="sentinel-a", broker="alpaca-paper",
            broker_account_id="paper-account-1", takeover_epoch=1,
            certificate_sha256="c" * 64, rollout_mode="PINNED_1_00",
            rollout_version=1, config_sha256=config.fingerprint)
        # Store wants the pydantic model, but keeping construction local makes
        # the regression independent of other test modules.
        from sentinel.automation.model import ControlBinding
        exact = ControlBinding(**control_binding.__dict__)
        automation_store.activate(
            conn, binding=exact, actor="operator", reason="regression")
        automation_store.release_kill(
            conn, expected_binding=exact, actor="operator", reason="regression")
        return automation_store.acquire_lease(
            conn, holder_id="worker-a", lease_seconds=30)


    def test_148_readiness_session_scan_is_bounded_and_visibility_preserved():
        source = inspect.getsource(readiness.check_readiness)
        assert "COUNT(DISTINCT session)" not in source
        assert "session >= %s" in source
        assert "_VISIBLE_BARS" in source
        assert source.count("SELECT DISTINCT session FROM sentinel_bars b") == 1


    def test_148_preparation_guard_rechecks_boundary_without_full_readiness(monkeypatch):
        grant = PaperPreparationGrant(
            expected_account="paper-account-1",
            decision_session=date(2026, 8, 14))
        fake_binding = SimpleNamespace(
            broker_account_id="paper-account-1", takeover_epoch=1,
            identity=SimpleNamespace(matches_account=lambda _value: True))
        monkeypatch.setattr("sentinel.handover.assert_no_legacy_path",
                            lambda _conn: fake_binding)
        monkeypatch.setattr(paper, "load_rollout_state", lambda _conn: object())
        monkeypatch.setattr(paper.publication, "require_current",
                            lambda _conn: object())
        monkeypatch.setattr(paper.feed_store, "latest_visible_session",
                            lambda _conn: "2026-08-14")
        monkeypatch.setattr(paper, "load_controller", lambda: object())
        monkeypatch.setattr(paper, "runtime_strategy_identity",
                            lambda _controller: {})
        monkeypatch.setattr(paper.calendar, "latest_closed_session",
                            lambda _now: "2026-08-14")
        monkeypatch.setattr(
            paper, "_readiness_or_refuse",
            lambda *_a, **_k: (_ for _ in ()).throw(
                AssertionError("preparation guard rescanned readiness")))
        paper._validate_broker_grant(
            object(), grant, BrokerOperation.ACCOUNT_SNAPSHOT, None,
            now_provider=lambda: datetime(
                2026, 8, 14, 17, tzinfo=timezone.utc))


    def test_149_emergency_cli_does_not_enter_schema_preflight(monkeypatch, capsys):
        fake_conn = SimpleNamespace(close=lambda: None)
        monkeypatch.setattr(feed_store, "connect", lambda _dsn: fake_conn)
        monkeypatch.setattr(
            schema, "ensure_schema",
            lambda _conn: (_ for _ in ()).throw(
                AssertionError("emergency kill entered schema migration")))
        monkeypatch.setattr(
            schema, "require_runtime_schema",
            lambda _conn: (_ for _ in ()).throw(
                AssertionError("emergency kill entered schema validation")))
        killed = SimpleNamespace(
            enabled=True, kill_switch_engaged=True, generation=9)
        monkeypatch.setattr(automation_store, "engage_kill",
                            lambda _conn, **_kw: killed)
        config = SimpleNamespace(database_url="postgresql://fixture")
        args = SimpleNamespace(actor="operator", reason="emergency")
        assert sentinel_cli._remove_automation_authority(
            config, args, kill=True) == sentinel_cli.EXIT_OK
        assert '"kill_switch_engaged": true' in capsys.readouterr().out


    def test_149_host_emergency_path_needs_no_backup_or_authorized_environment(
            tmp_path):
        fakebin = tmp_path / "bin"
        fakebin.mkdir()
        argv_file = tmp_path / "docker-argv"
        docker = fakebin / "docker"
        docker.write_text(
            "#!/usr/bin/env bash\nprintf '%s\\n' \"$@\" > \"$DOCKER_ARGV_FILE\"\n")
        docker.chmod(0o755)
        env = os.environ.copy()
        for name in (
                "SENTINEL_BACKUP_DIR", "SENTINEL_GIT_COMMIT",
                "SENTINEL_RUNTIME_IMAGE_DIGEST", "SENTINEL_TEST_IMAGE_DIGEST",
                "SENTINEL_AUTHORITY_ARTIFACTS_DIR", "ALPACA_API_KEY",
                "ALPACA_SECRET_KEY", "SENTINEL_AUTHORIZED_RUNTIME"):
            env.pop(name, None)
        env.update({
            "PATH": f"{fakebin}:{env['PATH']}",
            "DOCKER_ARGV_FILE": str(argv_file),
            "SENTINEL_POSTGRES_PASSWORD": "fixture-only",
            "SENTINEL_FORCE_CPU_LIMITS": "1",
        })
        subprocess.run(
            ["bash", str(ROOT / "scripts/sentinel-emergency-kill.sh"),
             "--actor", "operator", "--reason", "emergency"],
            cwd=ROOT, env=env, check=True)
        argv = argv_file.read_text().splitlines()
        joined = " ".join(argv)
        assert "docker-compose.sentinel-backup.yml" not in joined
        assert "docker-compose.sentinel-automation.yml" not in joined
        assert "--no-deps" in argv
        assert "sentinel" in argv
        assert "engage-paper-automation-kill-switch" in argv


    def test_150_require_leader_leaves_backend_idle_not_idle_in_transaction(
            behavioral, pg):
        permit = _enable(behavioral)
        with behavioral.cursor() as cur:
            cur.execute("SELECT pg_backend_pid()")
            pid = int(cur.fetchone()[0])
        behavioral.rollback()

        automation_store.require_leader(behavioral, permit)

        observer = feed_store.connect(pg.sync_dsn)
        try:
            with observer.cursor() as cur:
                cur.execute("SELECT state FROM pg_stat_activity WHERE pid=%s", (pid,))
                assert cur.fetchone()[0] == "idle"
        finally:
            observer.rollback()
            observer.close()


    def test_150_runtime_schema_is_read_only_and_does_not_repair(behavioral):
        schema.require_runtime_schema(behavioral)
        with behavioral.cursor() as cur:
            cur.execute(
                "ALTER TABLE sentinel_automation_control "
                "DROP COLUMN authority_detail")
        behavioral.commit()

        with pytest.raises(schema.SchemaMigrationRefused, match="missing migration columns"):
            schema.require_runtime_schema(behavioral)
        with behavioral.cursor() as cur:
            cur.execute(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_schema='public' "
                "AND table_name='sentinel_automation_control' "
                "AND column_name='authority_detail'")
            assert cur.fetchone() is None
        behavioral.rollback()


    def test_150_runtime_validation_coexists_with_idle_reader(behavioral, pg):
        blocker = feed_store.connect(pg.sync_dsn)
        runtime = feed_store.connect(pg.sync_dsn)
        try:
            with blocker.cursor() as cur:
                cur.execute("SELECT * FROM sentinel_automation_control WHERE id=1")
                cur.fetchone()
            # Keep blocker intentionally idle in transaction. Runtime validation
            # uses only compatible reads, so it must not introduce queued DDL.
            schema.require_runtime_schema(runtime)
        finally:
            blocker.rollback()
            blocker.close()
            runtime.rollback()
            runtime.close()


    def test_150_explicit_schema_ddl_has_bounded_lock_wait(behavioral, pg):
        blocker = feed_store.connect(pg.sync_dsn)
        migrator = feed_store.connect(pg.sync_dsn)
        try:
            with blocker.cursor() as cur:
                cur.execute("SELECT * FROM sentinel_automation_control WHERE id=1")
                cur.fetchone()
            with pytest.raises(Exception, match="lock timeout"):
                schema.ensure_schema(migrator)
        finally:
            blocker.rollback()
            blocker.close()
            migrator.rollback()
            migrator.close()


    def test_150_automation_composition_uses_read_only_runtime_schema_gate():
        source = inspect.getsource(automation_runtime.ProductionAutomation)
        assert "schema.ensure_schema(conn)" not in source
        assert source.count("schema.require_runtime_schema(conn)") >= 4
        cli_source = inspect.getsource(sentinel_cli._automation_run)
        assert "schema.require_runtime_schema(conn)" in cli_source
        assert "schema.ensure_schema(conn)" not in cli_source


    @pytest.fixture()
    def signed_conn(pg):
        conn = feed_store.connect(pg.sync_dsn)
        drop_public_tables(conn)
        schema.ensure_schema(conn)
        binding.bind(
            conn, deployment_id="nas-01", broker="alpaca",
            broker_account_id="paper-123")
        try:
            yield conn
        finally:
            conn.rollback()
            conn.close()
            cleanup = feed_store.connect(pg.sync_dsn)
            try:
                drop_public_tables(cleanup)
            finally:
                cleanup.close()


    def test_137_future_certificate_stages_before_not_before_but_activation_waits(
            signed_conn):
        document = signed_fx.claims(
            not_before="2026-08-14T00:00:00Z",
            expires_at="2026-08-20T00:00:00Z")
        payload = signed_fx.signed(document)
        digest = hashlib.sha256(payload).hexdigest()
        installed = authority.install_signed_certificate(
            signed_conn, certificate_bytes=payload, confirm_sha256=digest,
            context=signed_fx.context(document), now=signed_fx.NOW,
            trust_roots=signed_fx.ROOTS)
        assert installed.status == "STAGED"

        with pytest.raises(authority.AuthorityRefused, match="not yet valid"):
            authority.activate_signed_certificate(
                signed_conn, certificate_sha256=digest,
                context=signed_fx.context(document), reason="too early",
                now=signed_fx.NOW, trust_roots=signed_fx.ROOTS,
                confirm_controller_rollout=True)

        active = authority.activate_signed_certificate(
            signed_conn, certificate_sha256=digest,
            context=signed_fx.context(document), reason="window opened",
            now=datetime(2026, 8, 14, tzinfo=timezone.utc),
            trust_roots=signed_fx.ROOTS,
            confirm_controller_rollout=True)
        assert active.status == "ACTIVE"


    def test_137_candidate_cli_captures_lifecycle_reference_before_warmup(
            monkeypatch, tmp_path):
        events = []
        reference = datetime(2026, 8, 16, 20, 42, tzinfo=timezone.utc)

        class Clock:
            @classmethod
            def now(cls, _tz=None):
                events.append("clock")
                return reference

        class Conn:
            def close(self):
                events.append("close")

        monkeypatch.setattr(sentinel_cli, "datetime", Clock)
        monkeypatch.setattr(feed_store, "connect", lambda _dsn: Conn())
        monkeypatch.setattr(schema, "require_runtime_schema",
                            lambda _conn: events.append("schema"))
        monkeypatch.setattr(sentinel_cli, "_closed_preview_frontier",
                            lambda _conn: (SimpleNamespace(ready=True), "2026-08-14"))
        monkeypatch.setattr(sentinel_cli, "_current_system_identities",
                            lambda: ({"runtime": 1}, {"strategy": 1}))
        monkeypatch.setattr(
            automation_runtime, "config_from_env",
            lambda: SimpleNamespace(fingerprint="a" * 64))

        import sentinel.observation_authority as observation
        monkeypatch.setattr(
            observation, "current_warmup_evidence",
            lambda _conn, starting_cash: events.append("warmup") or {"ok": True})

        def candidate(_conn, **kwargs):
            events.append("candidate")
            assert kwargs["now"] == reference
            assert kwargs["not_before"] == reference
            return {"schema": "fixture", "claims": {}, "retained_evidence": {}}

        monkeypatch.setattr(observation, "build_candidate", candidate)
        args = SimpleNamespace(
            certificate_id="cert-1", issuer_generation=1,
            deployment_id="nas-01", expect_account="paper-123",
            not_before="2026-08-16T20:42:00Z", expires_at=None,
            maximum_exposure="1", cash=100000.0,
            reviewer="reviewer", ticket="ticket")
        config = SimpleNamespace(database_url="postgresql://fixture")
        assert sentinel_cli.cmd_create_paper_observation_candidate(
            config, args) == sentinel_cli.EXIT_OK
        assert events.index("clock") < events.index("warmup")
        assert events.index("warmup") < events.index("candidate")
'''))

print("applied #137/#148/#149/#150 patch")
