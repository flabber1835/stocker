"""Evaluator Phase 3 — POST /config/apply, the one-click human-approved apply.

Locks the safety contract: no write without confirm, without a literal value,
or without the strategy-validator's blessing (unreachable OR invalid → the
active file must be byte-identical afterwards). Happy path: atomic replace,
before/after artifacts archived, audit row attempted, next-run semantics noted.
Transport to strategy-validator is faked by patching main.httpx; the DB engine
is faked so no Postgres is needed.
"""
import os
import shutil
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
import yaml
from fastapi import HTTPException

from app import main

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
V2 = os.path.join(ROOT, "strategies", "momentum_rotation_v2.yaml")


class _Resp:
    def __init__(self, payload, status_code=200, text=""):
        self._p, self.status_code, self.text = payload, status_code, text

    def json(self):
        return self._p


class _FakeHttpx:
    """AsyncClient whose post() returns the canned validator response."""
    def __init__(self, resp=None, raise_exc=None):
        self._resp, self._raise = resp, raise_exc
        outer = self

        class _Client:
            def __init__(self, *a, **k): ...
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, url, json=None, **k):
                outer.last_posted = json
                if outer._raise:
                    raise outer._raise
                return outer._resp
        self.AsyncClient = _Client


class _FakeEngine:
    """engine.begin() ctx whose execute() records inserts."""
    def __init__(self):
        self.executed = []
        outer = self

        class _Conn:
            async def execute(self, stmt, params=None):
                outer.executed.append((str(stmt), params))
        self._conn = _Conn()

    @asynccontextmanager
    async def begin(self):
        yield self._conn


def _req(**kw):
    base = dict(config_field="portfolio_builder.max_positions",
                suggested_value="25", confirm=True,
                source_report_run_id=None, recommendation_index=0)
    base.update(kw)
    return main.ConfigApplyRequest(**base)


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    """A throwaway copy of the real active config + artifacts dir."""
    cfg = tmp_path / "active.yaml"
    shutil.copy(V2, cfg)
    monkeypatch.setattr(main, "STRATEGY_CONFIG_PATH", str(cfg))
    monkeypatch.setattr(main, "ARTIFACTS_PATH", str(tmp_path / "artifacts"))
    monkeypatch.setattr(main, "engine", _FakeEngine())
    return cfg


@pytest.mark.asyncio
async def test_apply_happy_path_atomic_archive_audit(sandbox, tmp_path):
    fake = _FakeHttpx(_Resp({"valid": True, "strategy_id": "x"}))
    with patch.object(main, "httpx", fake):
        res = await main.config_apply(_req())
    assert res["applied"] is True
    assert res["old_value"] != 25 and res["new_value"] == 25
    # the active file now carries the new value
    new_cfg = yaml.safe_load(open(sandbox))
    assert new_cfg["portfolio_builder"]["max_positions"] == 25
    # validator saw the WHOLE new config, not a diff
    assert fake.last_posted["portfolio_builder"]["max_positions"] == 25
    assert "strategy_id" in fake.last_posted
    # before/after archived; applied artifact hash matches the active file
    hist = os.listdir(tmp_path / "artifacts" / "config" / "history")
    appl = os.listdir(tmp_path / "artifacts" / "config" / "applied")
    assert len(hist) == 1 and res["config_hash_before"] in hist[0]
    assert len(appl) == 1 and res["config_hash_after"] in appl[0]
    applied_raw = open(tmp_path / "artifacts" / "config" / "applied" / appl[0]).read()
    assert applied_raw == open(sandbox).read()   # mirror-into-git verbatim
    # audit row attempted
    assert res["audit_row_written"] is True
    assert any("config_changes" in sql for sql, _ in main.engine.executed)


@pytest.mark.asyncio
async def test_no_confirm_no_write(sandbox):
    before = open(sandbox).read()
    with pytest.raises(HTTPException) as ei:
        await main.config_apply(_req(confirm=False))
    assert ei.value.status_code == 400
    assert open(sandbox).read() == before


@pytest.mark.asyncio
async def test_prose_value_rejected(sandbox):
    with pytest.raises(HTTPException) as ei:
        await main.config_apply(_req(suggested_value="reduce by half"))
    assert ei.value.status_code == 422


@pytest.mark.asyncio
async def test_already_set_is_409(sandbox):
    current = yaml.safe_load(open(sandbox))["portfolio_builder"]["max_positions"]
    with pytest.raises(HTTPException) as ei:
        await main.config_apply(_req(suggested_value=str(current)))
    assert ei.value.status_code == 409


@pytest.mark.asyncio
async def test_validator_reject_blocks_write(sandbox):
    before = open(sandbox).read()
    fake = _FakeHttpx(_Resp({"valid": False, "errors": ["max_position_weight > 1"]},
                            status_code=422))
    with patch.object(main, "httpx", fake):
        with pytest.raises(HTTPException) as ei:
            await main.config_apply(_req())
    assert ei.value.status_code == 422
    assert open(sandbox).read() == before          # byte-identical — no write


@pytest.mark.asyncio
async def test_validator_unreachable_fails_closed(sandbox):
    before = open(sandbox).read()
    fake = _FakeHttpx(raise_exc=ConnectionError("gateway down"))
    with patch.object(main, "httpx", fake):
        with pytest.raises(HTTPException) as ei:
            await main.config_apply(_req())
    assert ei.value.status_code == 503
    assert open(sandbox).read() == before


@pytest.mark.asyncio
async def test_paired_apply_atomic_where_singles_are_invalid(sandbox):
    """The W29 case (values reversed — the repo config now CARRIES the W29
    reweight, so the test pair goes the other way): near_high→0.06 and
    low_volatility→0.08 each break the weights-sum-to-1 invariant ALONE but
    validate TOGETHER. The batch path must apply both atomically; the audit
    gets one row per field."""
    fake = _FakeHttpx(_Resp({"valid": True}))
    with patch.object(main, "httpx", fake):
        res = await main.config_apply(main.ConfigApplyRequest(
            changes={"static_factor_weights.near_high": "0.06",
                     "static_factor_weights.low_volatility": "0.08"},
            confirm=True))
    assert res["applied"] is True
    assert res["changes"]["static_factor_weights.near_high"]["new"] == 0.06
    assert res["changes"]["static_factor_weights.low_volatility"]["new"] == 0.08
    new_cfg = yaml.safe_load(open(sandbox))
    w = new_cfg["static_factor_weights"]
    assert w["near_high"] == 0.06 and w["low_volatility"] == 0.08
    assert abs(sum(w.values()) - 1.0) < 1e-6
    # validator saw ONE whole config carrying BOTH edits
    posted = fake.last_posted["static_factor_weights"]
    assert posted["near_high"] == 0.06 and posted["low_volatility"] == 0.08
    # one audit row per field (INSERTs only — the status-finalize UPDATE also
    # touches config_changes but carries no field param)
    inserts = [p for sql, p in main.engine.executed
               if "INSERT INTO config_changes" in sql]
    assert {p["field"] for p in inserts} == {
        "static_factor_weights.near_high", "static_factor_weights.low_volatility"}


@pytest.mark.asyncio
async def test_single_field_of_a_coupled_pair_is_rejected_no_write(sandbox):
    """Locks WHY the batch path exists: one leg alone must be refused by the
    real schema (weights sum 0.94) and leave the file untouched."""
    from stock_strategy_shared.schemas.strategy import StrategyConfig
    before = open(sandbox).read()

    class _RealValidatorHttpx(_FakeHttpx):
        def __init__(self):
            super().__init__()
            outer = self

            class _Client:
                def __init__(self, *a, **k): ...
                async def __aenter__(self): return self
                async def __aexit__(self, *a): return False
                async def post(self, url, json=None, **k):
                    outer.last_posted = json
                    try:
                        StrategyConfig(**json)
                        return _Resp({"valid": True})
                    except Exception as exc:
                        return _Resp({"valid": False, "errors": [str(exc)]}, 422)
            self.AsyncClient = _Client

    with patch.object(main, "httpx", _RealValidatorHttpx()):
        with pytest.raises(HTTPException) as ei:
            await main.config_apply(_req(
                config_field="static_factor_weights.near_high",
                suggested_value="0.06"))
    assert ei.value.status_code == 422
    assert "sum" in str(ei.value.detail).lower()
    assert open(sandbox).read() == before


@pytest.mark.asyncio
async def test_null_literal_disables_nullable_knob(sandbox):
    fake = _FakeHttpx(_Resp({"valid": True}))
    with patch.object(main, "httpx", fake):
        res = await main.config_apply(_req(
            config_field="portfolio_builder.max_tickers_per_cluster",
            suggested_value="null"))
    assert res["applied"] is True and res["new_value"] is None
    assert yaml.safe_load(open(sandbox))["portfolio_builder"]["max_tickers_per_cluster"] is None


# ── transactional ordering (audit finding #4) ────────────────────────────────

class _FailingInsertEngine(_FakeEngine):
    """execute() raises on INSERT — simulates the DB being down at apply time."""
    def __init__(self):
        super().__init__()
        outer = self

        class _Conn:
            async def execute(self, stmt, params=None):
                outer.executed.append((str(stmt), params))
                if "INSERT INTO config_changes" in str(stmt):
                    raise RuntimeError("db down")
        self._conn = _Conn()


@pytest.mark.asyncio
async def test_audit_insert_failure_aborts_before_any_file_change(sandbox, monkeypatch):
    """No durable audit record → NO apply. The live file must be byte-identical
    and the applied/ artifact must not exist (pre-fix: file changed first,
    audit best-effort after)."""
    before = open(sandbox).read()
    monkeypatch.setattr(main, "engine", _FailingInsertEngine())
    with patch.object(main, "httpx", _FakeHttpx(_Resp({"valid": True}))):
        with pytest.raises(HTTPException) as ei:
            await main.config_apply(_req())
    assert ei.value.status_code == 503
    assert "NOT applied" in ei.value.detail
    assert open(sandbox).read() == before
    applied_dir = os.path.join(main.ARTIFACTS_PATH, "config", "applied")
    assert not os.path.isdir(applied_dir) or not os.listdir(applied_dir)


@pytest.mark.asyncio
async def test_happy_path_pending_then_applied(sandbox):
    """Rows go in as 'pending' BEFORE the file write and are finalized to
    'applied' after; the response reports audit_finalized."""
    with patch.object(main, "httpx", _FakeHttpx(_Resp({"valid": True}))):
        res = await main.config_apply(_req())
    assert res["applied"] is True
    assert res["audit_row_written"] is True and res["audit_finalized"] is True
    sqls = [s for s, _ in main.engine.executed]
    ins = [s for s in sqls if "INSERT INTO config_changes" in s]
    upd = [s for s in sqls if "SET status = 'applied'" in s]
    assert ins and "'pending'" in ins[0]
    assert upd and sqls.index(upd[0]) > sqls.index(ins[0])
    # applied/ artifact exists only because the replace succeeded
    assert res["applied_artifact"] and os.path.exists(res["applied_artifact"])
