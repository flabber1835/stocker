"""
Service contract tests — guard against response schema drift between services.

The scheduler reads `/runs/latest` from 5 services to advance the daily chain.
If any service drops, renames, or changes the type of a field the scheduler
depends on, the chain silently stalls. These tests prevent that.

Strategy:
  Each service's FastAPI app is imported directly (no Docker needed).
  The DB engine is mocked to return one valid DB row, matching what the real
  table would contain.  The endpoint is called via TestClient and the response
  is validated against the expected schema.

  This exercises the actual serialization code (isoformat, str(uuid), JSON
  encoding) — exactly where format bugs hide — without needing a real database.

Contracts tested:
  1. av-ingestor   GET /runs/latest
  2. pipeline      GET /runs/latest
  3. pipeline      GET /runs/delta-latest
  4. llm-vetter    GET /runs/latest
  5. portfolio-builder  GET /runs/latest
  6. alpaca-sync   GET /runs/latest
  7. risk-service  POST /check
  8. trade-executor POST /jobs/submit (response shape)

IMPORTANT: if you add a field to a /runs/latest response that the scheduler
reads, add it to the contract below.  If you rename a field, update both the
service and the contract — the test failing is the signal.
"""
from __future__ import annotations

import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
SHARED = os.path.join(ROOT, "shared")


def _add_service(name: str) -> None:
    p = os.path.join(ROOT, "services", name)
    if p not in sys.path:
        sys.path.insert(0, p)
    if SHARED not in sys.path:
        sys.path.insert(0, SHARED)


def _clear_app_modules() -> None:
    for k in list(sys.modules.keys()):
        if k == "app" or k.startswith("app."):
            del sys.modules[k]


def _now() -> datetime:
    return datetime.now(timezone.utc)


class _FakeRow(dict):
    """Dict that also supports attribute access, ._mapping, and SQL row protocol.

    Services access DB rows in different ways:
      - dict-style: result["field"]         (av-ingestor /runs/latest via mappings())
      - attribute:  result.field            (pipeline, vetter, alpaca-sync via fetchone())
      - _mapping:   dict(result._mapping)   (pipeline _format_pipeline_run)
    """
    def __getattr__(self, name: str):
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return self[name]
        except KeyError:
            raise AttributeError(name)

    @property
    def _mapping(self):
        return self


def _mock_engine_returning(row: dict | None):
    """Async engine mock that returns `row` for every query."""
    fake_row = _FakeRow(row) if row else None

    async def _exec(sql, params=None):
        result = MagicMock()
        m = MagicMock()
        m.first = MagicMock(return_value=fake_row)
        result.mappings = MagicMock(return_value=m)
        result.fetchone = MagicMock(return_value=fake_row)
        result.fetchall = MagicMock(return_value=[fake_row] if fake_row else [])
        result.rowcount = 1 if fake_row else 0
        return result

    conn = AsyncMock()
    conn.execute = _exec

    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=None)

    engine = MagicMock()
    engine.connect = MagicMock(return_value=ctx)
    engine.begin = MagicMock(return_value=ctx)
    return engine


def _assert_fields(body: dict, required: list[tuple[str, type]], context: str) -> None:
    """Assert that body contains all required fields with correct types."""
    for field, expected_type in required:
        assert field in body, (
            f"{context}: missing required field '{field}' in response {list(body.keys())}"
        )
        if body[field] is not None:
            assert isinstance(body[field], expected_type), (
                f"{context}: field '{field}' expected {expected_type.__name__}, "
                f"got {type(body[field]).__name__} = {body[field]!r}"
            )


# ── Contract 1: av-ingestor GET /runs/latest ────────────────────────────────

def test_av_ingestor_runs_latest_contract():
    """Scheduler reads: run_id, job_type, status, started_at, session_date from /runs/latest.

    session_date is the trading session the fetch advanced to — the scheduler keys
    the fetch-data step on it (SESSION anchor)."""
    _clear_app_modules()
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    os.environ.setdefault("AV_API_KEY", "demo")
    os.environ.setdefault("MOCK_DATA", "true")
    _add_service("av-ingestor")

    from app.main import app  # type: ignore
    import app.main as av_main  # type: ignore

    run_id = str(uuid.uuid4())
    fake_row = {
        "run_id": uuid.UUID(run_id),
        "job_type": "fetch-data",
        "status": "success",
        "ticker_count": 3000,
        "price_rows": 90000,
        "fund_rows": 0,
        "error_count": 0,
        "error_message": None,
        "session_date": _now().date(),
        "started_at": _now(),
        "completed_at": _now(),
        # progress/degraded columns the endpoint reads since the coverage-gate
        # work — the fake row must track the real SELECT list
        "tickers_done": 3000,
        "tickers_total": 3000,
        "degraded": False,
    }
    engine = _mock_engine_returning(fake_row)

    with patch.object(av_main, "engine", engine):
        from fastapi.testclient import TestClient
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/runs/latest")

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()

    _assert_fields(body, [
        ("run_id",       str),
        ("job_type",     str),
        ("status",       str),
        ("started_at",   str),
        ("session_date", str),
    ], "av-ingestor /runs/latest")

    # Scheduler uses these exact status values
    assert body["status"] in ("success", "running", "failed", "partial"), (
        f"av-ingestor status '{body['status']}' not in expected set"
    )


# ── Contract 2: pipeline GET /runs/latest ────────────────────────────────────

def test_pipeline_runs_latest_contract():
    """Scheduler reads: run_id, status, run_date from /runs/latest."""
    _clear_app_modules()
    for k in ("DATABASE_URL", "REDIS_URL"):
        os.environ.setdefault(k, "postgresql+asyncpg://x:x@localhost/x")
    _add_service("pipeline")

    from app.main import app  # type: ignore
    import app.main as pl_main  # type: ignore

    run_id = str(uuid.uuid4())
    today = "2026-05-25"
    fake_row = {
        "run_id": uuid.UUID(run_id),
        "trace_id": uuid.UUID(str(uuid.uuid4())),
        "status": "success",
        "run_date": today,
        "chain_date": today,
        "factor_run_id": None,
        "ranking_run_id": None,
        "delta_run_id": None,
        "factor_status": "success",
        "ranking_status": "success",
        "delta_status": None,
        "started_at": _now(),
        "completed_at": _now(),
        "error_message": None,
        "triggered_by": "scheduler",
    }
    engine = _mock_engine_returning(fake_row)

    # pipeline declares `engine: AsyncEngine` without a default, so create=True is needed
    with patch.object(pl_main, "engine", engine, create=True):
        from fastapi.testclient import TestClient
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/runs/latest")

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()

    _assert_fields(body, [
        ("run_id",   str),
        ("status",   str),
    ], "pipeline /runs/latest")

    # run_date should be present and either a date string or null
    assert "run_date" in body, "pipeline /runs/latest missing run_date"


# ── Contract 3: pipeline GET /runs/delta-latest ──────────────────────────────

def test_pipeline_delta_latest_contract():
    """Scheduler reads: run_id, status, run_date from /runs/delta-latest."""
    _clear_app_modules()
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    _add_service("pipeline")

    from app.main import app  # type: ignore
    import app.main as pl_main  # type: ignore

    run_id = str(uuid.uuid4())
    fake_row = {
        "run_id": uuid.UUID(run_id),
        "status": "success",
        "run_date": "2026-05-25",
        "started_at": _now(),
        "completed_at": _now(),
        "entries_count": 5,
        "exits_count": 2,
        "holds_count": 20,
        "watches_count": 3,
        "triggered_by": "scheduler",
        "manual": False,
    }
    engine = _mock_engine_returning(fake_row)

    with patch.object(pl_main, "engine", engine, create=True):
        from fastapi.testclient import TestClient
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/runs/delta-latest")

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()

    _assert_fields(body, [
        ("run_id", str),
        ("status", str),
    ], "pipeline /runs/delta-latest")

    # manual flag must surface so the dashboard can gate auto-approve on it.
    assert body.get("manual") is False, "pipeline /runs/delta-latest missing manual flag"


# ── Contract 4: llm-vetter GET /runs/latest ──────────────────────────────────

def test_vetter_runs_latest_contract():
    """Scheduler reads: run_id, status, source_rank_date from /runs/latest.

    source_rank_date is the rank_date of the ranking this run vetted (JOINed from
    ranking_runs) — the scheduler keys the vet step on it (UPSTREAM_RANK anchor)."""
    _clear_app_modules()
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    os.environ.setdefault("OPENAI_API_KEY", "")
    os.environ.setdefault("OLLAMA_URL", "http://localhost:11434")
    _add_service("llm-vetter")

    from app.main import app  # type: ignore
    import app.main as vt_main  # type: ignore

    run_id = str(uuid.uuid4())
    fake_row = {
        "run_id": uuid.UUID(run_id),
        "trace_id": uuid.UUID(str(uuid.uuid4())),
        "status": "success",
        "candidate_count": 50,
        "flagged_count": 3,
        "started_at": _now(),
        "completed_at": _now(),
        "source_rank_date": _now().date(),
    }
    engine = _mock_engine_returning(fake_row)

    with patch.object(vt_main, "engine", engine):
        from fastapi.testclient import TestClient
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/runs/latest")

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()

    _assert_fields(body, [
        ("run_id",   str),
        ("status",   str),
    ], "llm-vetter /runs/latest")

    # source_rank_date must surface so the scheduler can anchor vet on the ranking
    # it vetted (UPSTREAM_RANK) rather than wall-clock started_at.
    assert "source_rank_date" in body, "llm-vetter /runs/latest missing source_rank_date"


# ── Contract 5: portfolio-builder GET /runs/latest ───────────────────────────

def test_portfolio_builder_runs_latest_contract():
    """Scheduler reads: run_id, status, portfolio_date from /runs/latest."""
    _clear_app_modules()
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    _add_service("portfolio-builder")

    from app.main import app  # type: ignore
    import app.main as pb_main  # type: ignore

    run_id = str(uuid.uuid4())
    fake_row = {
        "run_id": uuid.UUID(run_id),
        "status": "success",
        "portfolio_date": "2026-05-25",
        "error_message": None,
        "started_at": _now(),
        "completed_at": _now(),
    }
    engine = _mock_engine_returning(fake_row)

    with patch.object(pb_main, "engine", engine, create=True):
        from fastapi.testclient import TestClient
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/runs/latest")

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()

    _assert_fields(body, [
        ("run_id",         str),
        ("status",         str),
        ("portfolio_date", str),
    ], "portfolio-builder /runs/latest")


# ── Contract 6: alpaca-sync GET /runs/latest ─────────────────────────────────

def test_alpaca_sync_runs_latest_contract():
    """Scheduler reads: run_id, status, position_count from /runs/latest."""
    _clear_app_modules()
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    os.environ.setdefault("ALPACA_API_KEY", "")
    os.environ.setdefault("ALPACA_SECRET_KEY", "")
    _add_service("alpaca-sync")

    from app.main import app  # type: ignore
    import app.main as as_main  # type: ignore

    run_id = str(uuid.uuid4())
    # alpaca-sync uses SessionLocal (not engine) for /runs/latest
    # The row is accessed via attribute syntax (row.run_id, row.status, etc.)
    fake_row = _FakeRow({
        "run_id": uuid.UUID(run_id),
        "status": "success",
        "position_count": 28,
        "account_value": 500_000.0,
        "buying_power": 250_000.0,
        "cash": 100_000.0,
        "started_at": _now(),
        "completed_at": _now(),
        "error_message": None,
    })

    result_mock = MagicMock()
    result_mock.fetchone = MagicMock(return_value=fake_row)

    db_mock = AsyncMock()
    db_mock.execute = AsyncMock(return_value=result_mock)
    db_mock.__aenter__ = AsyncMock(return_value=db_mock)
    db_mock.__aexit__ = AsyncMock(return_value=None)

    session_factory = MagicMock(return_value=db_mock)

    with patch.object(as_main, "SessionLocal", session_factory):
        from fastapi.testclient import TestClient
        client = TestClient(app, raise_server_exceptions=False)
        resp = client.get("/runs/latest")

    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    body = resp.json()

    _assert_fields(body, [
        ("run_id",         str),
        ("status",         str),
    ], "alpaca-sync /runs/latest")


# ── Contract 7: risk-service POST /check ─────────────────────────────────────

def test_risk_service_check_response_contract():
    """trade-executor reads: approved (bool), check_id (str UUID), rule_triggered (str)."""
    _clear_app_modules()
    os.environ.setdefault("KILL_SWITCH", "false")
    os.environ.setdefault("PAPER_ONLY", "true")
    os.environ.setdefault("LIVE_TRADING_ENABLED", "false")
    os.environ.setdefault("MAX_ORDER_NOTIONAL", "50000.0")
    _add_service("risk-service")

    from app.main import app  # type: ignore
    import app.main as rs_main  # type: ignore

    async def _fake_persist(req, *, approved, reason, rule, env):
        return str(uuid.uuid4())

    with patch.object(rs_main, "_persist_decision", _fake_persist):
        from fastapi.testclient import TestClient
        client = TestClient(app)
        resp = client.post("/check", json={
            "ticker": "AAPL", "action": "entry", "side": "buy",
            "qty": 10, "notional": 1500.0,
            "mode": "immediate", "trade_type": "paper",
        })

    assert resp.status_code == 200
    body = resp.json()

    _assert_fields(body, [
        ("approved",       bool),
        ("reason",         str),
        ("check_id",       str),
        ("rule_triggered", str),
    ], "risk-service /check")

    # check_id must be a valid UUID (trade-executor stores it as a FK)
    try:
        uuid.UUID(body["check_id"])
    except ValueError:
        pytest.fail(f"risk-service /check: check_id '{body['check_id']}' is not a valid UUID")

    # rule_triggered must be one of the known values
    valid_rules = {"kill_switch", "live_disabled", "paper_only", "qty",
                   "notional_zero", "notional_limit", "ok"}
    assert body["rule_triggered"] in valid_rules, (
        f"risk-service /check: rule_triggered '{body['rule_triggered']}' not in {valid_rules}"
    )


# ── Contract 8: trade-executor POST /jobs/submit response shape ───────────────

def test_trade_executor_submit_response_contract():
    """API layer and dashboard read: status, order_id, trace_id from /jobs/submit."""
    _clear_app_modules()
    os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://x:x@localhost/x")
    os.environ.setdefault("ALPACA_API_KEY", "")
    os.environ.setdefault("ALPACA_SECRET_KEY", "")
    os.environ.setdefault("RISK_SERVICE_URL", "http://risk-service:8000")
    _add_service("trade-executor")

    from app.main import app  # type: ignore
    import app.main as te_main  # type: ignore

    # Send a request with an invalid UUID — the endpoint validates this early
    # and returns 400 before touching the DB.
    from fastapi.testclient import TestClient
    client = TestClient(app, raise_server_exceptions=False)
    resp = client.post("/jobs/submit", json={"intent_id": "not-a-uuid", "mode": "immediate"})

    assert resp.status_code == 400
    body = resp.json()
    assert "detail" in body, "Trade-executor 400 response must have 'detail' field"

    # Valid UUID path: mock engine to short-circuit at intent not found
    intent_id = str(uuid.uuid4())
    run_id_uuid = str(uuid.uuid4())

    async def _exec(sql, params=None):
        result = MagicMock()
        m = MagicMock()
        m.first = MagicMock(return_value=None)
        result.mappings = MagicMock(return_value=m)
        result.rowcount = 0
        return result

    conn = AsyncMock()
    conn.execute = _exec
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=conn)
    ctx.__aexit__ = AsyncMock(return_value=None)
    engine = MagicMock()
    engine.begin = MagicMock(return_value=ctx)
    engine.connect = MagicMock(return_value=ctx)

    with patch.object(te_main, "engine", engine):
        # Intent not found → 404 with 'detail' field
        resp2 = client.post("/jobs/submit", json={"intent_id": intent_id, "mode": "immediate"})

    # Whether 200 (duplicate/failed) or 4xx, response must be JSON with known shape
    assert resp2.status_code in (200, 404, 422, 502)
    body2 = resp2.json()
    assert isinstance(body2, dict), "trade-executor response must be a JSON object"

    if resp2.status_code == 200:
        assert "status" in body2
        assert body2["status"] in ("submitted", "risk_rejected", "failed", "duplicate")
