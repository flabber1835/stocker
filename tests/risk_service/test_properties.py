"""
Property-based tests for the risk-service /check endpoint.

Properties under test:
  P1. Any structurally valid request always returns HTTP 200 (never 4xx/5xx from the service itself).
  P2. The response is always a dict with bool `approved` and str `check_id` (valid UUID) / `reason` / `rule_triggered`.
  P3. qty ≤ 0 is ALWAYS rejected with rule_triggered = "qty".
  P4. notional ≤ 0 is ALWAYS rejected with rule_triggered = "notional_zero".
  P5. notional > MAX_ORDER_NOTIONAL is ALWAYS rejected with rule_triggered = "notional_limit".
  P6. kill_switch=True ALWAYS rejects with rule_triggered = "kill_switch" regardless of other fields.
  P7. trade_type="live" with live_trading_enabled=False ALWAYS rejects.
  P8. paper_only=True + trade_type="live" ALWAYS rejects.
  P9. check_id in every response is a valid UUID v4.
  P10. approved=True implies rule_triggered = "ok".
"""
import os
import sys
import uuid

import pytest
from fastapi.testclient import TestClient
from hypothesis import given, settings, HealthCheck
from hypothesis import strategies as st

# ── path bootstrap ────────────────────────────────────────────────────────────

_RISK_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "services", "risk-service")
)


def _activate() -> object:
    """Clear all cached app.* modules, ensure risk-service is at sys.path[0], reimport.

    Returns a fresh reference to risk-service's app.main module.
    This is called once per test (via fixture) to guard against cross-service
    module pollution when running multiple service test suites in the same process.
    """
    for k in list(sys.modules.keys()):
        if k == "app" or k.startswith("app."):
            del sys.modules[k]
    if _RISK_PATH in sys.path:
        sys.path.remove(_RISK_PATH)
    sys.path.insert(0, _RISK_PATH)
    import app.main as _m
    return _m


# ── fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def risk_module():
    """Fresh reference to risk-service's app.main, isolated per test."""
    return _activate()


@pytest.fixture()
def risk_client(risk_module):
    """TestClient bound to the fresh risk-service app."""
    from app.main import app
    return TestClient(app)


@pytest.fixture(autouse=True)
def _patch_persist(monkeypatch, risk_module):
    """Replace DB persistence so tests run without Postgres."""
    async def _fake(req, *, approved, reason, rule, env):
        return str(uuid.uuid4())
    monkeypatch.setattr(risk_module, "_persist_decision", _fake)


@pytest.fixture(autouse=True)
def _default_env(monkeypatch, risk_module):
    """Safe defaults: paper-only, no kill switch, no control file."""
    monkeypatch.setenv("KILL_SWITCH", "false")
    monkeypatch.setenv("PAPER_ONLY", "true")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
    monkeypatch.setenv("MAX_ORDER_NOTIONAL", "50000.0")
    monkeypatch.setattr(risk_module, "_KILL_SWITCH_FILE",
                        "/tmp/_prop_test_no_kill_switch_NONEXISTENT")


# ── Hypothesis strategies ─────────────────────────────────────────────────────

_VALID_TICKERS = st.from_regex(r"[A-Z0-9.\-]{1,20}", fullmatch=True)
_ACTIONS = st.sampled_from(["entry", "exit", "buy_add", "sell_trim"])
_SIDES = st.sampled_from(["buy", "sell"])
_MODES = st.sampled_from(["immediate", "scheduled"])
_TRADE_TYPES = st.sampled_from(["paper", "live"])

_POSITIVE_QTY = st.floats(min_value=0.001, max_value=1_000_000,
                           allow_nan=False, allow_infinity=False)
_POSITIVE_NOTIONAL = st.floats(min_value=0.01, max_value=49_999.99,
                                allow_nan=False, allow_infinity=False)


def _valid_payload(**overrides):
    base = {
        "ticker": "AAPL",
        "action": "entry",
        "side": "buy",
        "qty": 10.0,
        "notional": 1000.0,
        "mode": "immediate",
        "trade_type": "paper",
    }
    base.update(overrides)
    return base


def _check_shape(data: dict) -> None:
    assert isinstance(data["approved"], bool), f"approved must be bool, got {data['approved']!r}"
    assert isinstance(data["reason"], str)
    assert isinstance(data["rule_triggered"], str)
    uuid.UUID(data["check_id"])


# ── P1 & P2: valid inputs always return 200 with correct shape ────────────────

@given(
    ticker=_VALID_TICKERS,
    action=_ACTIONS,
    side=_SIDES,
    qty=_POSITIVE_QTY,
    notional=_POSITIVE_NOTIONAL,
    mode=_MODES,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_valid_input_always_200(risk_client, ticker, action, side, qty, notional, mode):
    """Any valid paper request returns 200 with well-formed response."""
    resp = risk_client.post("/check", json=_valid_payload(
        ticker=ticker, action=action, side=side,
        qty=qty, notional=notional, mode=mode,
    ))
    assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
    _check_shape(resp.json())


# ── P3: qty ≤ 0 always rejected ───────────────────────────────────────────────

@given(qty=st.floats(max_value=0.0, allow_nan=False, allow_infinity=False))
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_nonpositive_qty_always_rejected(risk_client, qty):
    """qty ≤ 0 must always trigger the qty rule."""
    resp = risk_client.post("/check", json=_valid_payload(qty=qty))
    assert resp.status_code == 200
    data = resp.json()
    assert data["approved"] is False
    assert data["rule_triggered"] == "qty", (
        f"qty={qty} expected rule_triggered='qty', got {data['rule_triggered']!r}"
    )


# ── P4: notional ≤ 0 always rejected ─────────────────────────────────────────

@given(notional=st.floats(max_value=0.0, allow_nan=False, allow_infinity=False))
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_nonpositive_notional_always_rejected(risk_client, notional):
    """notional ≤ 0 must always trigger the notional_zero rule."""
    resp = risk_client.post("/check", json=_valid_payload(notional=notional))
    assert resp.status_code == 200
    data = resp.json()
    assert data["approved"] is False
    assert data["rule_triggered"] == "notional_zero", (
        f"notional={notional} expected 'notional_zero', got {data['rule_triggered']!r}"
    )


# ── P5: notional > limit always rejected ─────────────────────────────────────

@given(notional=st.floats(min_value=50_000.01, max_value=1e12,
                           allow_nan=False, allow_infinity=False))
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_notional_over_limit_always_rejected(risk_client, notional):
    """notional > 50000 must always trigger the notional_limit rule."""
    resp = risk_client.post("/check", json=_valid_payload(notional=notional))
    assert resp.status_code == 200
    data = resp.json()
    assert data["approved"] is False
    assert data["rule_triggered"] == "notional_limit", (
        f"notional={notional} expected 'notional_limit', got {data['rule_triggered']!r}"
    )


# ── P6: kill switch always wins ───────────────────────────────────────────────

@given(
    qty=_POSITIVE_QTY,
    notional=_POSITIVE_NOTIONAL,
    trade_type=_TRADE_TYPES,
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_kill_switch_always_wins(monkeypatch, risk_client, qty, notional, trade_type):
    """kill_switch=True must reject every request regardless of other fields."""
    monkeypatch.setenv("KILL_SWITCH", "true")
    resp = risk_client.post("/check", json=_valid_payload(
        qty=qty, notional=notional, trade_type=trade_type,
    ))
    assert resp.status_code == 200
    data = resp.json()
    assert data["approved"] is False
    assert data["rule_triggered"] == "kill_switch", (
        f"Expected 'kill_switch', got {data['rule_triggered']!r}"
    )


# ── P7: live trade blocked when LIVE_TRADING_ENABLED=false ───────────────────

@given(qty=_POSITIVE_QTY, notional=_POSITIVE_NOTIONAL)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_live_trade_blocked_without_enable(monkeypatch, risk_client, qty, notional):
    """trade_type='live' with LIVE_TRADING_ENABLED=false must be rejected."""
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "false")
    monkeypatch.setenv("PAPER_ONLY", "false")
    resp = risk_client.post("/check", json=_valid_payload(
        qty=qty, notional=notional, trade_type="live",
    ))
    assert resp.status_code == 200
    data = resp.json()
    assert data["approved"] is False
    assert data["rule_triggered"] in {"live_disabled", "paper_only"}, (
        f"Expected live blocking rule, got {data['rule_triggered']!r}"
    )


# ── P8: paper_only blocks live regardless of live_trading_enabled ─────────────

@given(qty=_POSITIVE_QTY, notional=_POSITIVE_NOTIONAL)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_paper_only_blocks_live_trade(monkeypatch, risk_client, qty, notional):
    """PAPER_ONLY=true must reject live trades even if LIVE_TRADING_ENABLED=true."""
    monkeypatch.setenv("PAPER_ONLY", "true")
    monkeypatch.setenv("LIVE_TRADING_ENABLED", "true")
    resp = risk_client.post("/check", json=_valid_payload(
        qty=qty, notional=notional, trade_type="live",
    ))
    assert resp.status_code == 200
    data = resp.json()
    assert data["approved"] is False
    assert data["rule_triggered"] in {"live_disabled", "paper_only"}, (
        f"Expected live blocking rule, got {data['rule_triggered']!r}"
    )


# ── P9: check_id always a valid UUID ─────────────────────────────────────────

@given(qty=st.one_of(_POSITIVE_QTY, st.just(-1.0), st.just(0.0)))
@settings(max_examples=80, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_check_id_always_valid_uuid(risk_client, qty):
    """Every response — approval or rejection — contains a valid UUID check_id."""
    resp = risk_client.post("/check", json=_valid_payload(qty=qty))
    assert resp.status_code == 200
    data = resp.json()
    try:
        uuid.UUID(data["check_id"])
    except (ValueError, KeyError) as exc:
        pytest.fail(f"check_id is not a valid UUID: {data.get('check_id')!r} — {exc}")


# ── P10: approved=True implies rule_triggered='ok' ───────────────────────────

@given(
    ticker=_VALID_TICKERS,
    qty=_POSITIVE_QTY,
    notional=_POSITIVE_NOTIONAL,
    mode=_MODES,
)
@settings(max_examples=100, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_approved_implies_ok_rule(risk_client, ticker, qty, notional, mode):
    """When a request is approved, rule_triggered must always be 'ok'."""
    resp = risk_client.post("/check", json=_valid_payload(
        ticker=ticker, qty=qty, notional=notional, mode=mode, trade_type="paper",
    ))
    assert resp.status_code == 200
    data = resp.json()
    if data["approved"]:
        assert data["rule_triggered"] == "ok", (
            f"approved=True but rule_triggered={data['rule_triggered']!r}"
        )


# ── Rule priority: kill_switch beats qty/notional checks ─────────────────────

@given(
    qty=st.floats(max_value=0.0, allow_nan=False, allow_infinity=False),
    notional=st.floats(max_value=0.0, allow_nan=False, allow_infinity=False),
)
@settings(max_examples=50, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_kill_switch_beats_qty_notional(monkeypatch, risk_client, qty, notional):
    """kill_switch is checked first — it should fire even for invalid qty/notional."""
    monkeypatch.setenv("KILL_SWITCH", "true")
    resp = risk_client.post("/check", json=_valid_payload(qty=qty, notional=notional))
    assert resp.status_code == 200
    data = resp.json()
    assert data["approved"] is False
    assert data["rule_triggered"] == "kill_switch"
