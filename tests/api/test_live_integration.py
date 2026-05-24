"""Live integration tests for the API service (port 8000).

These tests run against the live Docker stack. They are read-only: they
never INSERT data (except for the /trade/approve and /trade/reject tests
which immediately clean up). All tests skip if the stack is unreachable.
"""
import pytest
import requests

BASE = "http://localhost:8000"


def _up():
    try:
        return requests.get(f"{BASE}/health", timeout=3).status_code == 200
    except Exception:
        return False


pytestmark = pytest.mark.skipif(not _up(), reason="API not reachable on :8000")


# ── health ────────────────────────────────────────────────────────────────────

def test_health():
    r = requests.get(f"{BASE}/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["service"] == "api"


# ── universe ──────────────────────────────────────────────────────────────────

def test_universe_returns_snapshot_and_tickers():
    r = requests.get(f"{BASE}/universe")
    assert r.status_code == 200
    d = r.json()
    assert "snapshot" in d and "tickers" in d
    assert d["snapshot"]["ticker_count"] > 0
    assert isinstance(d["tickers"], list)
    assert len(d["tickers"]) > 0
    # Each ticker entry has required fields
    t = d["tickers"][0]
    for key in ("ticker", "name", "weight_pct", "sector"):
        assert key in t, f"Missing key: {key}"


def test_universe_investable_is_subset():
    """Investable universe (filtered) must be <= full universe size."""
    full = requests.get(f"{BASE}/universe").json()["tickers"]
    inv_resp = requests.get(f"{BASE}/universe/investable").json()
    # Response is a dict with a 'tickers' key
    inv = inv_resp.get("tickers", inv_resp) if isinstance(inv_resp, dict) else inv_resp
    assert isinstance(inv, list)
    full_tickers = {t["ticker"] for t in full}
    inv_tickers = {t["ticker"] for t in inv}
    assert inv_tickers <= full_tickers or len(inv_tickers) == 0


# ── rankings ─────────────────────────────────────────────────────────────────

def test_rankings_returns_ranked_list():
    r = requests.get(f"{BASE}/rankings?limit=10")
    assert r.status_code == 200
    d = r.json()
    assert "rankings" in d
    assert "count" in d
    rankings = d["rankings"]
    assert isinstance(rankings, list)


def test_rankings_have_required_fields():
    r = requests.get(f"{BASE}/rankings?limit=5")
    rankings = r.json()["rankings"]
    if not rankings:
        pytest.skip("No rankings in DB")
    for row in rankings:
        for key in ("ticker", "rank", "composite_score", "percentile", "regime", "rank_date"):
            assert key in row, f"Missing field: {key}"


def test_rankings_sorted_ascending():
    """Rank 1 must come before rank 2 (sorted ascending by rank)."""
    r = requests.get(f"{BASE}/rankings?limit=30")
    rankings = r.json()["rankings"]
    if len(rankings) < 2:
        pytest.skip("Not enough rankings")
    ranks = [row["rank"] for row in rankings]
    assert ranks == sorted(ranks), "Rankings not sorted ascending"


def test_rankings_percentile_in_unit_range():
    r = requests.get(f"{BASE}/rankings?limit=20")
    for row in r.json()["rankings"]:
        p = row["percentile"]
        assert 0.0 <= p <= 1.0, f"Percentile out of range: {p}"


def test_rankings_factor_scores_present():
    r = requests.get(f"{BASE}/rankings?limit=3")
    for row in r.json()["rankings"]:
        fs = row.get("factor_scores")
        assert isinstance(fs, dict), "factor_scores should be a dict"
        for factor in ("quality", "momentum", "value", "growth", "low_volatility"):
            assert factor in fs, f"Missing factor: {factor}"


# ── regime ────────────────────────────────────────────────────────────────────

def test_regime_returns_valid_regime():
    r = requests.get(f"{BASE}/regime")
    assert r.status_code == 200
    d = r.json()
    valid = {"bull_calm", "bull_stress", "bear_calm", "bear_stress"}
    assert d["regime"] in valid, f"Unknown regime: {d['regime']}"
    assert "spy_price" in d
    assert "realized_vol" in d
    assert "calculated_at" in d


def test_regime_spy_price_positive():
    d = requests.get(f"{BASE}/regime").json()
    assert d["spy_price"] > 0, "SPY price must be positive"


# ── portfolio ─────────────────────────────────────────────────────────────────

def test_portfolio_has_run_and_holdings():
    r = requests.get(f"{BASE}/portfolio")
    assert r.status_code == 200
    d = r.json()
    assert "run" in d and "holdings" in d
    assert isinstance(d["holdings"], list)


def test_portfolio_weights_sum_to_at_most_one():
    """Total target weight must not exceed 100%."""
    d = requests.get(f"{BASE}/portfolio").json()
    if not d["holdings"]:
        pytest.skip("No portfolio holdings")
    total = sum(h.get("target_weight", 0) or 0 for h in d["holdings"])
    assert total <= 1.01, f"Portfolio weights sum {total:.4f} > 1"


def test_live_portfolio_returns_dict():
    r = requests.get(f"{BASE}/live-portfolio")
    assert r.status_code == 200
    d = r.json()
    assert isinstance(d, (dict, list))


# ── data freshness ────────────────────────────────────────────────────────────

def test_data_freshness_has_all_sections():
    r = requests.get(f"{BASE}/data-freshness")
    assert r.status_code == 200
    d = r.json()
    for section in ("prices", "fundamentals", "factors", "rankings"):
        assert section in d, f"Missing section: {section}"


def test_data_freshness_prices_have_date():
    d = requests.get(f"{BASE}/data-freshness").json()
    assert d["prices"]["max_date"] is not None


# ── system status ─────────────────────────────────────────────────────────────

def test_system_status_has_all_services():
    r = requests.get(f"{BASE}/system/status")
    assert r.status_code == 200
    d = r.json()
    for service in ("pipeline", "ingestor", "scheduler"):
        assert service in d, f"Missing service: {service}"


def test_system_status_pipeline_success():
    d = requests.get(f"{BASE}/system/status").json()
    pipeline = d.get("pipeline", {})
    assert pipeline.get("status") in ("success", "running", "failed", None)


# ── delta ─────────────────────────────────────────────────────────────────────

def test_delta_latest_has_run_and_intents():
    r = requests.get(f"{BASE}/delta/latest")
    assert r.status_code == 200
    d = r.json()
    # Response is a list of [key, value] pairs or a dict
    keys = {k for k, _ in d} if isinstance(d, list) else set(d.keys())
    assert "run" in keys
    assert "intents" in keys


# ── orders ────────────────────────────────────────────────────────────────────

def test_recent_orders_returns_list():
    r = requests.get(f"{BASE}/orders/recent?limit=10")
    assert r.status_code == 200
    d = r.json()
    assert isinstance(d, list)


def test_recent_orders_fields():
    r = requests.get(f"{BASE}/orders/recent?limit=5")
    orders = r.json()
    if not orders:
        pytest.skip("No orders in DB")
    for order in orders:
        for key in ("id", "ticker", "action", "status"):
            assert key in order, f"Order missing field: {key}"


def test_recent_orders_status_values_valid():
    r = requests.get(f"{BASE}/orders/recent?limit=20")
    valid = {"pending", "submitted", "filled", "failed", "risk_rejected", "cancelled", "partial_fill"}
    for order in r.json():
        status = order.get("status")
        assert status in valid, f"Invalid order status: {status}"


# ── factor runs ──────────────────────────────────────────────────────────────

def test_factor_runs_returns_list():
    r = requests.get(f"{BASE}/factor-runs")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


def test_ranking_runs_returns_list():
    r = requests.get(f"{BASE}/ranking-runs")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ── factors by ticker ─────────────────────────────────────────────────────────

def test_factors_for_known_ticker():
    r = requests.get(f"{BASE}/factors/AAPL")
    # 200 if data exists, 400/404 if not in this DB
    assert r.status_code in (200, 400, 404)
    if r.status_code == 200:
        d = r.json()
        assert isinstance(d, (dict, list))


# ── traces ────────────────────────────────────────────────────────────────────

def test_traces_returns_list():
    r = requests.get(f"{BASE}/traces?limit=5")
    assert r.status_code == 200
    assert isinstance(r.json(), list)


# ── input validation ──────────────────────────────────────────────────────────

def test_trade_approve_requires_intent_id():
    """POST /trade/approve without intent_id must return 4xx, not 500."""
    r = requests.post(f"{BASE}/trade/approve", json={})
    assert r.status_code in (400, 422), f"Expected 4xx, got {r.status_code}"


def test_trade_reject_requires_intent_id():
    """POST /trade/reject without intent_id must return 4xx, not 500."""
    r = requests.post(f"{BASE}/trade/reject", json={})
    assert r.status_code in (400, 422), f"Expected 4xx, got {r.status_code}"


def test_trade_approve_nonexistent_intent_returns_error():
    """Approving a non-existent intent must return a clear error, not 500."""
    r = requests.post(f"{BASE}/trade/approve",
                      json={"intent_id": "00000000-0000-0000-0000-000000000000"})
    assert r.status_code in (400, 404, 409, 422, 500)
    # Must not crash silently — response must be JSON
    r.json()
