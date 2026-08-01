"""Auto-promotion watcher — the ONLY path by which a config reaches the live
strategy (the human one-click POST /config/apply was removed).

Locks the safety contract: the WHOLE candidate config goes through the
strategy-validator before any write (unreachable → retry, rejected → recorded so
it never loops), the replace is atomic, an audit row is written, and a second
pass is a no-op. Transport is faked; the DB engine is faked so no Postgres is
needed.
"""
import os
import shutil
from contextlib import asynccontextmanager
from unittest.mock import patch

import pytest
import yaml

from app import main

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
V2 = os.path.join(ROOT, "strategies", "momentum_rotation_v2.yaml")


class _Resp:
    def __init__(self, payload, status_code=200, text=""):
        self._p, self.status_code, self.text = payload, status_code, text

    def json(self):
        return self._p


class _FakeHttpx:
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


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    cfg = tmp_path / "active.yaml"
    shutil.copy(V2, cfg)
    monkeypatch.setattr(main, "STRATEGY_CONFIG_PATH", str(cfg))
    monkeypatch.setattr(main, "ARTIFACTS_PATH", str(tmp_path / "artifacts"))
    monkeypatch.setattr(main, "engine", _FakeEngine())
    return cfg


# ── Phase 6d: auto-promotion watcher (paper mode) ─────────────────────────────

def _write_promotion(tmp_path, cfg: dict, ph="abcd1234abcd1234"):
    import json as _json
    d = tmp_path / "artifacts" / "bt"
    d.mkdir(parents=True, exist_ok=True)
    (d / "promotion.json").write_text(_json.dumps({
        "config": cfg, "config_hash": ph,
        "hypothesis": "test thesis", "diff_vs_active": {"max_positions": {"from": 30, "to": 20}},
        "evidence": {"gate": "CAGR edge +0.02"}, "promoted_at": "2026-07-24T22:30",
    }))
    return ph


@pytest.mark.asyncio
async def test_promotion_applied_validator_gated_and_audited(sandbox, tmp_path):
    cand = yaml.safe_load(open(sandbox))
    cand["portfolio_builder"]["max_positions"] = 20
    ph = _write_promotion(tmp_path, cand)
    fake = _FakeHttpx(_Resp({"valid": True}))
    with patch.object(main, "httpx", fake):
        await main._check_promotion()
    # config replaced atomically
    assert yaml.safe_load(open(sandbox))["portfolio_builder"]["max_positions"] == 20
    # validator saw the WHOLE candidate
    assert fake.last_posted["portfolio_builder"]["max_positions"] == 20
    # state recorded → a second pass is a no-op (idempotent)
    state = main._read_promo_state()
    assert state["last_hash"] == ph and state["status"] == "applied"
    before = open(sandbox).read()
    with patch.object(main, "httpx", fake):
        await main._check_promotion()
    assert open(sandbox).read() == before
    # audit row attempted with the auto_promotion marker
    assert any("auto_promotion" in sql for sql, _ in main.engine.executed)


@pytest.mark.asyncio
async def test_promotion_rejected_by_validator_never_applies_never_loops(sandbox, tmp_path):
    cand = yaml.safe_load(open(sandbox))
    cand["portfolio_builder"]["max_positions"] = 20
    ph = _write_promotion(tmp_path, cand)
    before = open(sandbox).read()
    fake = _FakeHttpx(_Resp({"valid": False, "errors": ["bad"]}, status_code=422))
    with patch.object(main, "httpx", fake):
        await main._check_promotion()
    assert open(sandbox).read() == before                     # untouched
    assert main._read_promo_state()["status"] == "rejected"   # recorded → no loop


@pytest.mark.asyncio
async def test_promotion_validator_unreachable_fails_closed_and_retries(sandbox, tmp_path):
    cand = yaml.safe_load(open(sandbox))
    cand["portfolio_builder"]["max_positions"] = 20
    _write_promotion(tmp_path, cand)
    before = open(sandbox).read()
    fake = _FakeHttpx(raise_exc=RuntimeError("validator down"))
    with patch.object(main, "httpx", fake):
        await main._check_promotion()
    assert open(sandbox).read() == before                     # untouched
    assert main._read_promo_state() == {}                     # NOT recorded → retried


# ── PROTECTED_PATHS gate on the promotion path ───────────────────────────────
# /validate checks schema and hard safety limits but knows nothing about the
# LLM-tunable partition. Without a second gate, an automated promotion could write
# a protected field — strategy_id, universe.source, the falling-knife thresholds,
# or trailing_stop.enabled — into the live config with no human involved. That made
# the partition decorative on the one path that reaches production: the evaluator
# is forbidden from PROPOSING those fields while promotion was free to APPLY them.

class _UrlAwareHttpx:
    """Distinguishes the two validator calls, which the shared fake cannot."""

    def __init__(self, llm_change, validate):
        self.calls = []
        outer = self

        class _Client:
            def __init__(self, *a, **k): ...
            async def __aenter__(self): return self
            async def __aexit__(self, *a): return False
            async def post(self, url, json=None, **k):
                outer.calls.append(url)
                if "validate-llm-change" in url:
                    if isinstance(llm_change, Exception):
                        raise llm_change
                    return llm_change
                return validate
        self.AsyncClient = _Client


@pytest.mark.asyncio
async def test_promotion_touching_a_protected_field_is_refused(sandbox, tmp_path,
                                                               monkeypatch):
    cand = yaml.safe_load(open(sandbox))
    cand.setdefault("trailing_stop", {})["enabled"] = True
    ph = _write_promotion(tmp_path, cand)
    before = open(sandbox).read()

    fake = _UrlAwareHttpx(
        llm_change=_Resp({"valid": False,
                          "changed_protected_fields": ["trailing_stop.enabled"]},
                         status_code=422),
        validate=_Resp({"valid": True, "strategy_id": "x"}))
    monkeypatch.setattr(main, "httpx", fake)

    await main._check_promotion()

    assert open(sandbox).read() == before, "the live config was rewritten"
    state = main._read_promo_state()
    assert state["last_hash"] == ph and state["status"] == "rejected"
    assert "protected" in state["reason"].lower()
    assert not any("/validate" in c and "llm-change" not in c for c in fake.calls), (
        "schema validation ran anyway — the protected check must short-circuit")


@pytest.mark.asyncio
async def test_a_tunable_only_promotion_still_applies(sandbox, tmp_path, monkeypatch):
    """The gate must not block ordinary candidates — a gate that refuses
    everything is a gate someone switches off."""
    cand = yaml.safe_load(open(sandbox))
    cand["max_positions"] = 20
    cand["portfolio_builder"]["max_positions"] = 20
    _write_promotion(tmp_path, cand)

    fake = _UrlAwareHttpx(
        llm_change=_Resp({"valid": True, "changed_protected_fields": []}),
        validate=_Resp({"valid": True, "strategy_id": "x"}))
    monkeypatch.setattr(main, "httpx", fake)

    await main._check_promotion()

    applied = yaml.safe_load(open(sandbox))
    assert applied["max_positions"] == 20
    assert main._read_promo_state()["status"] == "applied"


@pytest.mark.asyncio
async def test_protected_check_unreachable_fails_closed(sandbox, tmp_path, monkeypatch):
    """Fail-closed, like the schema gate beside it: no state write, so the next
    poll retries rather than the candidate being lost or silently applied."""
    cand = yaml.safe_load(open(sandbox))
    cand["max_positions"] = 20
    _write_promotion(tmp_path, cand)
    before = open(sandbox).read()

    monkeypatch.setattr(main, "httpx", _UrlAwareHttpx(
        llm_change=RuntimeError("connection refused"),
        validate=_Resp({"valid": True})))

    await main._check_promotion()

    assert open(sandbox).read() == before
    assert main._read_promo_state() == {} or "status" not in main._read_promo_state(), (
        "a definitive state was recorded for a transient outage — the candidate "
        "would never be retried")
