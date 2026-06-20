"""FIX A — risk-service must REJECT non-finite (NaN / +inf / -inf) qty/notional.

NaN fails every `<=` / `>` comparison, so without an explicit finiteness guard a
NaN qty/notional would slip past the `<=0` and `>max_order_notional` gates and
reach the final approve. inf would pass `>0` but break downstream sizing math.

Two layers are tested:
  1. _decide() rejects a request constructed bypassing validation (model_construct),
     proving the in-engine guard — the load-bearing safety check.
  2. The /check endpoint rejects a NaN/inf payload at the Pydantic boundary.
Normal finite values are unaffected (regression guard).
"""
import os as _os
import sys as _sys

_RISK_PATH = _os.path.abspath(
    _os.path.join(_os.path.dirname(__file__), "..", "..", "services", "risk-service")
)
_app = _sys.modules.get("app")
if _app is None or _RISK_PATH not in _os.path.abspath(getattr(_app, "__file__", "") or ""):
    for _k in list(_sys.modules.keys()):
        if _k == "app" or _k.startswith("app."):
            del _sys.modules[_k]
    if _RISK_PATH not in _sys.path:
        _sys.path.insert(0, _RISK_PATH)

import asyncio
import math

import pytest

from app import main as risk_main
from app.main import TradeCheckRequest


def _construct(**overrides):
    """Build a TradeCheckRequest BYPASSING Pydantic validation so we can feed
    _decide a non-finite value (the schema validator would otherwise reject it)."""
    base = dict(
        ticker="AAPL",
        action="entry",
        side="buy",
        qty=10.0,
        notional=1000.0,
        mode="immediate",
        trade_type="paper",
        sim_date=None,
    )
    base.update(overrides)
    return TradeCheckRequest.model_construct(**base)


@pytest.fixture(autouse=True)
def _no_engine(monkeypatch):
    # Force the in-memory path; non-finite gate runs before any DB control.
    monkeypatch.setattr(risk_main, "engine", None)
    yield


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_decide_rejects_non_finite_qty(bad):
    approved, reason, rule, _env = asyncio.run(risk_main._decide(_construct(qty=bad)))
    assert approved is False
    assert rule == "non_finite_qty"


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_decide_rejects_non_finite_notional(bad):
    approved, reason, rule, _env = asyncio.run(risk_main._decide(_construct(notional=bad)))
    assert approved is False
    assert rule == "non_finite_notional"


def test_decide_approves_finite_values():
    approved, reason, rule, _env = asyncio.run(risk_main._decide(_construct()))
    assert approved is True
    assert rule == "ok"
    assert math.isfinite(10.0)


def test_pydantic_rejects_non_finite():
    with pytest.raises(Exception):
        TradeCheckRequest(
            ticker="AAPL", action="entry", side="buy",
            qty=float("nan"), notional=1000.0, mode="immediate",
        )
    with pytest.raises(Exception):
        TradeCheckRequest(
            ticker="AAPL", action="entry", side="buy",
            qty=10.0, notional=float("inf"), mode="immediate",
        )
