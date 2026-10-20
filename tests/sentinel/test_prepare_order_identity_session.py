"""Attended CLI identity dates through a published source and real Alpaca decoder.

This isolates the CLI-to-adapter handoff. Its preparation callback only performs
an exact-order GET; it is not a signed preparation or deployment qualification.
"""
from __future__ import annotations

import asyncio
import inspect
import os
from pathlib import Path
import textwrap
from types import SimpleNamespace
import uuid
from datetime import datetime, timezone

import httpx
import pytest

from sentinel import backup_runtime_authority, identity, paper, schema
from sentinel.cli import _shared, paper as paper_cli
from sentinel.config import DEFAULT_BASE_URL, SentinelConfig
from sentinel.execution.states import CommandState
from sentinel.feed import operational_snapshot, rolling_publisher, store
from sentinel.feed.alpaca_source import AlpacaSource
from sentinel.feed.alpaca_transport import ASSETS
from sentinel.feed.rolling_contract import digest, PriceWindow
from tests.sentinel.test_alpaca_operational_snapshot import FakeClient, FakeClassifier
from tests.support.postgres import _EphemeralPostgres


MONDAY = "2026-10-19"
TUESDAY = "2026-10-20"
WEDNESDAY = "2026-10-21"
IDS = {"PBR": "22abbcb7-8fb0-4e83-89f8-31433a6839c8",
       "PBR.A": "1b98d78e-fda5-47f5-ad2f-4557a3963fe1"}
KEYS = {"PBR": "sntl-30ec882eb7d541bba107",
        "PBR.A": "sntl-d97a4212e732e9d11e39"}
NOW = datetime(2026, 10, 20, 4, tzinfo=timezone.utc)


class LocalPrices(FakeClient):
    def get(self, endpoint, params=None, *, text=False):
        assert endpoint == ASSETS
        # Keep the production 500-security admission floor intact.
        assets = [dict(id=str(uuid.UUID(int=index + 1)), symbol=f"T{index:03}",
            name=f"Fixture {index}", **{"class": "us_equity"},
            status="active", tradable=True, exchange="NASDAQ")
            for index in range(498)]
        assets.extend(dict(id=value, symbol=symbol, name=symbol,
            **{"class": "us_equity"}, status="active", tradable=True,
            exchange="NYSE") for symbol, value in IDS.items())
        return assets, {"endpoint": endpoint, "observed_at": NOW.isoformat(),
                        "sha256": digest([endpoint, params])}

    def pages(self, endpoint, params, *, key):
        for payload, proof in super().pages(endpoint, params, key=key):
            yield payload, {**proof, "observed_at": NOW.isoformat()}


class LocalClassifier(FakeClassifier):
    def mapping(self, assets):
        values, proof = super().mapping(assets)
        return values, {**proof, "observed_at": NOW.isoformat()}


@pytest.fixture(scope="module")
def published_database(tmp_path_factory):
    server = _EphemeralPostgres()
    server.start()
    connection = store.connect(server.sync_dsn)
    with pytest.MonkeyPatch.context() as patch:
        # This synthetic component database has no deployment backup media.
        # Keep the backup validator intact and make the environment explicitly
        # a developer fixture; exact-image campaigns retain their baked marker
        # and real private backup horizon. This test grants no backup authority.
        patch.setattr(backup_runtime_authority, "POLICY_MARKER",
            tmp_path_factory.mktemp("order-date-policy") / "absent-policy-marker")
        patch.delenv(backup_runtime_authority.AUTHORITY_ENV, raising=False)
        patch.setenv("SENTINEL_STATE_DIR", str(tmp_path_factory.mktemp("order-date-state")))
        # These are explicit local producer inputs, not validator replacements.
        revision = os.environ.get("SENTINEL_IMAGE_SOURCE_REVISION", "a" * 40)
        image = "sha256:" + "b" * 64
        for key, value in {
                "SENTINEL_GIT_COMMIT": revision,
                "SENTINEL_IMAGE_SOURCE_REVISION": revision,
                "SENTINEL_RUNTIME_IMAGE_DIGEST": image,
                "SENTINEL_FEED_GIT_COMMIT": revision,
                "SENTINEL_FEED_RUNTIME_IMAGE_DIGEST": image,
                "SENTINEL_FEED_AUTHORIZED": identity.FEED_AUTHORIZATION_VALUE,
                "SENTINEL_PUBLICATION_RECEIPT_KEY": "order-date-unit-receipt-" * 4,
        }.items():
            patch.setenv(key, value)
        patch.delenv("SENTINEL_FEED_SERVICE_MODE", raising=False)
        prices, classifier = LocalPrices(window=PriceWindow.through(MONDAY)), LocalClassifier()

        def source(window, conn, lease, **kwargs):
            prices.window = window
            return AlpacaSource(window, conn, lease, client=prices,
                classifier=classifier,
                verify_during_coverage=kwargs["verify_during_coverage"])

        patch.setattr(rolling_publisher, "_operational_source", source)
        patch.setattr(operational_snapshot, "_now", lambda: NOW)
        try:
            store.migrate_schema(connection)
            schema.ensure_schema(connection)
            job = operational_snapshot.enqueue(connection,
                strategy_sha256=digest("order-date-component-source"),
                dependencies_sha256=digest("local-provider-only"), budget_seconds=600)
            connection.commit()
            result = operational_snapshot.prepare(connection, job)
            assert result["scope"] == "DATA_ONLY"
            connection.commit()
            yield server.sync_dsn
        finally:
            connection.close()
            server.stop()


@pytest.fixture
def authorized_cli(monkeypatch, tmp_path):
    marker = tmp_path / "authorized-runtime-v1"
    marker.write_bytes(_shared.AUTHORIZED_RUNTIME_MARKER_BYTES)
    capability = tmp_path / "authorized-capability-v1"
    capability.write_text("#!/bin/sh\nprintf 'sentinel-authorized-capability/1\\n'\n")
    capability.chmod(0o755)
    monkeypatch.setattr(_shared, "AUTHORIZED_RUNTIME_MARKER", marker)
    monkeypatch.setattr(_shared, "AUTHORIZED_RUNTIME_CAPABILITY", capability)
    monkeypatch.setenv(_shared.AUTHORIZED_RUNTIME_ENV, _shared.AUTHORIZED_RUNTIME_VALUE)


def _wire(symbol, submitted):
    native_id, quantity, average, limit, time = {
        "PBR": ("2b9706f9-e1a6-407d-af08-33a1d6467690", "65", "25.53", "25.54",
                "T13:36:52.337821Z"),
        "PBR.A": ("7495e5a2-1ecd-4e95-a69d-a6c1d654951e", "72", "22.938611", "22.94",
                  "T13:36:31.265764Z"),
    }[symbol]
    return dict(id=native_id, client_order_id=KEYS[symbol], symbol=symbol,
        asset_id=IDS[symbol], side="buy", status="filled", qty=quantity,
        filled_qty=quantity, filled_avg_price=average,
        limit_price=limit, submitted_at=submitted + time,
        type="limit", time_in_force="day", order_class="simple", extended_hours=False)


def _exercise(monkeypatch, dsn, *, symbol="PBR", submitted=TUESDAY,
              through=MONDAY, handler=None):
    calls, orders = [], []

    def response(request):
        calls.append((request.method, request.url.path))
        assert request.method == "GET", "component fixture attempted broker mutation"
        if request.url.path == "/v2/account":
            return httpx.Response(200, json={"id": "paper-date-fixture", "status": "ACTIVE"})
        assert request.url.path == "/v2/orders:by_client_order_id"
        assert request.url.params["client_order_id"] == KEYS[symbol]
        return httpx.Response(200, json=_wire(symbol, submitted))

    real_client = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs:
        real_client(transport=httpx.MockTransport(response), **kwargs))

    async def read_preparation(**kwargs):
        assert kwargs["through"] == through
        lookup = await kwargs["broker"].find_by_client_key(KEYS[symbol])
        assert lookup.order is not None
        orders.append(lookup.order)
        return SimpleNamespace(to_dict=lambda: {"scope": "CLI_ORDER_DATE_COMPONENT_ONLY"})

    monkeypatch.setattr(paper, "prepare_paper_plan", read_preparation)
    config = SentinelConfig(alpaca_key="PKLOCALDATE", alpaca_secret="unit-secret",
        base_url=DEFAULT_BASE_URL, database_url=dsn, state_dir=Path("/tmp/order-date"),
        max_cycles=1, poll_seconds=0)
    args = SimpleNamespace(through=through, expect_account="paper-date-fixture", warmup_sessions=252)
    code = asyncio.run((handler or paper_cli._prepare_paper_plan)(config, args))
    return code, orders, calls


@pytest.mark.parametrize("symbol", ["PBR", "PBR.A"])
def test_attended_prepare_decodes_tuesday_order_from_monday_source(
        published_database, authorized_cli, monkeypatch, symbol):
    code, orders, calls = _exercise(monkeypatch, published_database, symbol=symbol)
    assert code == _shared.EXIT_OK
    assert len(orders) == 1 and orders[0].state is CommandState.FILLED
    assert orders[0].instrument.security_id == IDS[symbol]
    assert orders[0].instrument.broker_id == IDS[symbol]
    assert calls and all(method == "GET" for method, _ in calls)


def test_wednesday_native_order_does_not_borrow_tuesday_projection(
        published_database, authorized_cli, monkeypatch, capsys):
    code, orders, calls = _exercise(monkeypatch, published_database, submitted=WEDNESDAY)
    assert code == _shared.EXIT_NOT_ESTABLISHED and not orders
    assert "no permanent security identity" in capsys.readouterr().err
    assert calls and all(method == "GET" for method, _ in calls)


def test_requested_wednesday_refuses_before_broker_construction(
        published_database, authorized_cli, monkeypatch, capsys):
    code, orders, calls = _exercise(monkeypatch, published_database, through=TUESDAY)
    assert code == _shared.EXIT_NOT_ESTABLISHED and not orders and not calls
    assert "BEYOND_NEXT_SESSION" in capsys.readouterr().err


def test_former_monday_handler_fails_actual_tuesday_wire_assertion(
        published_database, authorized_cli, monkeypatch, capsys):
    source = textwrap.dedent(inspect.getsource(paper_cli._prepare_paper_plan.__wrapped__))
    source = source.replace('@authorized_handler("prepare-paper-plan")\n', "")
    needle = "calendar.next_session(args.through)"
    assert source.count(needle) == 1
    namespace = {}
    exec(compile(source.replace(needle, "args.through"),
        "former-prepare-date-falsifier", "exec"), paper_cli.__dict__, namespace)
    code, orders, calls = _exercise(monkeypatch, published_database,
        handler=namespace["_prepare_paper_plan"])
    assert code == _shared.EXIT_NOT_ESTABLISHED and not orders
    assert "instrument 'PBR' has no permanent security identity" in capsys.readouterr().err
    assert calls and all(method == "GET" for method, _ in calls)
    with pytest.raises(AssertionError):
        assert code == _shared.EXIT_OK and len(orders) == 1
