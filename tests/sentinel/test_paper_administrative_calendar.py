"""Administrative CLI dates meet the actual rolling identity reader."""
import asyncio
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

from sentinel import binding, empty_account, guarded_administration, paper, schema
from sentinel.cli import authority as authority_cli, paper as paper_cli
from sentinel.cli._shared import EXIT_NOT_ESTABLISHED, EXIT_OK
from sentinel.feed import calendar, operational_snapshot as snapshots, store
from sentinel.feed.rolling_contract import PriceWindow, digest
from tests.sentinel.test_operational_snapshot import operational_source  # noqa: F401
from tests.sentinel.test_paper_cli import (
    _authorized_runtime_surface, _config, _inspection_result,  # noqa: F401
)
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source  # noqa: F401


DATES = [
    ("2026-09-12T16:00:00Z", "2026-09-11", "2026-09-11"),
    ("2026-09-13T16:00:00Z", "2026-09-11", "2026-09-11"),
    ("2026-09-14T03:59:59Z", "2026-09-11", "2026-09-11"),
    ("2026-09-14T04:00:00Z", "2026-09-11", "2026-09-14"),
    ("2026-09-14T12:00:00Z", "2026-09-11", "2026-09-14"),
    ("2026-09-07T16:00:00Z", "2026-09-04", "2026-09-04"),
    ("2025-11-27T17:00:00Z", "2025-11-26", "2025-11-26"),
    ("2025-11-28T13:00:00Z", "2025-11-26", "2025-11-28"),
]
DATE_IDS = ["saturday", "sunday", "utc-monday-ny-sunday", "ny-midnight",
            "preopen", "labor-day", "thanksgiving", "early-close-preopen"]


@pytest.fixture
def administrative_publication(conn, operational_source, monkeypatch, published_end):
    window = PriceWindow.through(published_end)
    for table in ("SEP", "SFP"):
        rows = operational_source[table]
        first = min(row["date"] for row in rows)
        templates = [dict(row) for row in rows if row["date"] == first]
        rows[:] = [{**row, "date": str(day)}
                   for day in window.sessions for row in templates]
    for row in operational_source["TICKERS"]:
        row.update(firstpricedate=str(window.start), lastpricedate=published_end)
    operational_source["ACTIONS"][:] = [row for row in operational_source["ACTIONS"]
                                        if row["date"] <= published_end]
    final = datetime.fromisoformat(published_end + "T23:59:59").replace(
        tzinfo=ZoneInfo(calendar.EXCHANGE_TZ))
    monkeypatch.setattr(snapshots, "_now", lambda: final)
    monkeypatch.setattr(snapshots.calendar, "latest_closed_session", lambda now=None: published_end)
    job = snapshots.enqueue(conn, strategy_sha256=digest("administrative-fixture"),
                            dependencies_sha256=digest("calendar"), budget_seconds=120)
    conn.commit()
    snapshots.prepare(conn, job)
    schema.ensure_schema(conn)
    assert binding.load(conn) is None
    return conn


def freeze(monkeypatch, instant):
    now = datetime.fromisoformat(instant.replace("Z", "+00:00"))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return now.astimezone(tz) if tz is not None else now.replace(tzinfo=None)

    monkeypatch.setattr(paper_cli, "datetime", Clock)


def wire(monkeypatch, conn):
    """Keep authorization/transport outside this identity regression's scope."""
    class Connection:
        closed = False

        def __getattr__(self, name):
            return getattr(conn, name)

        def close(self):
            self.closed = True

    connection = Connection()
    monkeypatch.setattr(store, "connect", lambda _: connection)
    monkeypatch.setattr(authority_cli, "_administrative_epoch", lambda *a, **kw: 1)
    monkeypatch.setattr(authority_cli, "_authorized_administrative_access",
                        lambda *a, **kw: (object(), object()))
    monkeypatch.setattr(guarded_administration, "GuardedAdministrativeExecutionBroker",
                        lambda *, inner, **kw: inner)
    monkeypatch.setattr(empty_account, "GuardedEmptyAccountBroker", lambda *, inner, **kw: inner)
    calls = []

    def broker(config, *, resolve_security_id):
        # Neither the resolver nor its publication binding is mocked.
        assert resolve_security_id("AAA") == "1"
        assert resolve_security_id("BIL") == "SENTINEL:BIL"
        assert resolve_security_id("UNKNOWN") is None
        calls.append("broker")
        return object()

    async def inspect(**kwargs):
        calls.append("inspect")
        return _inspection_result()

    async def inspect_empty(**kwargs):
        calls.append("inspect-empty")
        return SimpleNamespace(to_dict=lambda: {"approval_ready": True})

    async def bind_empty(**kwargs):
        calls.append("bind-empty")
        return SimpleNamespace(to_dict=lambda: {"binding_state": "OWNED"})

    monkeypatch.setattr(paper_cli, "build_execution_broker", broker)
    monkeypatch.setattr(paper, "inspect_paper_account", inspect)
    monkeypatch.setattr(empty_account, "inspect", inspect_empty)
    monkeypatch.setattr(empty_account, "bind_empty_account", bind_empty)
    return connection, calls


@pytest.mark.parametrize("handler,operation", [
    (paper_cli._inspect_paper_account, "inspect"),
    (paper_cli._inspect_empty_paper_account, "inspect-empty"),
    (paper_cli._bind_empty_paper_account, "bind-empty"),
])
@pytest.mark.parametrize("instant,published_end,expected", DATES, ids=DATE_IDS)
def test_administrative_cli_uses_exchange_session_with_real_snapshot(
        monkeypatch, administrative_publication, handler, operation, instant,
        published_end, expected):
    conn = administrative_publication
    freeze(monkeypatch, instant)
    connection, calls = wire(monkeypatch, conn)
    args = SimpleNamespace(deployment_id="local-paper", expect_account="paper-123", notes="")
    assert asyncio.run(handler(_config(), args)) == EXIT_OK
    assert paper_cli._administrative_identity_session() == expected
    assert calls == ["broker", operation]
    assert connection.closed
    assert conn.execute("SELECT count(*) FROM sentinel_commands").fetchone()[0] == 0
    assert binding.load(conn) is None  # Transport and enrollment are not exercised here.


@pytest.mark.parametrize("handler", [paper_cli._inspect_paper_account,
    paper_cli._inspect_empty_paper_account, paper_cli._bind_empty_paper_account])
@pytest.mark.parametrize("published_end", ["2026-09-04"])
def test_weekend_mapping_cannot_admit_a_genuinely_stale_publication(
        monkeypatch, administrative_publication, handler, capsys):
    freeze(monkeypatch, "2026-09-13T16:00:00Z")
    connection, calls = wire(monkeypatch, administrative_publication)
    args = SimpleNamespace(deployment_id="local-paper", expect_account="paper-123", notes="")
    assert asyncio.run(handler(_config(), args)) == EXIT_NOT_ESTABLISHED
    assert "ROLLING_IDENTITY_BEYOND_NEXT_SESSION" in capsys.readouterr().err
    assert calls == []
    assert connection.closed


@pytest.mark.parametrize("published_end,instant", [
    ("2026-09-11", "2026-09-13T16:00:00Z"),
    ("2026-09-04", "2026-09-07T16:00:00Z"),
])
@pytest.mark.parametrize("changed_account", [False, True])
def test_weekend_cli_composes_real_empty_binding_and_authority_consumption(
        administrative_publication, monkeypatch, published_end, instant,
        changed_account):
    # Real rolling resolver, read facade, stable-empty proof, writer transaction,
    # certificate consumption and durable binding. External account transport and
    # admission-context construction remain explicit test fixtures.
    from sentinel import administrative_authority
    from sentinel.execution.alpaca import AlpacaExecutionBroker
    from sentinel.execution.certification import certify_adapter
    from sentinel.guarded_administration import (
        AdministrativeAccessGrant, AdministrativeBrokerGuard,
    )
    from functools import partial
    from tests.sentinel.test_empty_account_binding import NOW, ROOTS, activate, flat_broker

    conn = administrative_publication
    _, certificate_sha256 = activate(conn)
    monkeypatch.setattr(administrative_authority, "consume_empty_binding_authority",
                        partial(administrative_authority.consume_empty_binding_authority,
                                now=NOW, trust_roots=ROOTS))
    freeze(monkeypatch, instant)

    class Connection:
        def __getattr__(self, name):
            return getattr(conn, name)

        def close(self):
            pass  # The fixture owns the real connection's teardown.

    monkeypatch.setattr(store, "connect", lambda _: Connection())
    grant = AdministrativeAccessGrant(operation="ADMIN_BIND_EMPTY", deployment_id="nas-01",
                                      broker_account_id="paper-123", takeover_epoch=1)
    guard = AdministrativeBrokerGuard(check=lambda *args: None)
    monkeypatch.setattr(authority_cli, "_authorized_administrative_access",
                        lambda *a, **kw: (grant, guard))
    monkeypatch.setattr(authority_cli, "_require_administrative_access",
                        lambda *a, **kw: SimpleNamespace(certificate_sha256=certificate_sha256))
    broker = flat_broker()
    reads = []

    def adapter(config, *, resolve_security_id):
        assert resolve_security_id("AAA") == "1"
        inner = AlpacaExecutionBroker(api_key="test", secret_key="test",
                                     base_url=config.base_url)

        async def account():
            reads.append("account")
            if changed_account and reads.count("account") == 2:
                broker.cash -= 1
            return await broker.account_snapshot()

        monkeypatch.setattr(inner, "account_snapshot", account)
        monkeypatch.setattr(inner, "observe", broker.observe)
        certify_adapter(inner, name="alpaca", mode="ALPACA_PAPER")
        return inner

    monkeypatch.setattr(paper_cli, "build_execution_broker", adapter)
    args = SimpleNamespace(deployment_id="nas-01", expect_account="paper-123", notes="")
    result = asyncio.run(paper_cli._bind_empty_paper_account(_config(), args))
    assert result == (EXIT_NOT_ESTABLISHED if changed_account else EXIT_OK)
    bound = binding.load(conn)
    assert (bound is not None) is (not changed_account)
    if bound is not None:
        assert bound.broker_account_id == "paper-123" and bound.takeover_epoch == 1
    status = conn.execute(
        "SELECT status FROM sentinel_signed_administrative_certificates WHERE certificate_sha256=%s",
        (certificate_sha256,),
    ).fetchone()[0]
    assert status == ("ACTIVE" if changed_account else "REVOKED")
    assert conn.execute("SELECT count(*) FROM sentinel_commands").fetchone()[0] == 0
