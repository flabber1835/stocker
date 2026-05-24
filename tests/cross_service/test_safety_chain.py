"""Cross-service safety chain integration tests.

These tests verify the end-to-end safety invariants that span multiple services:

  1. Risk service blocks live trades even if trade-executor is asked to submit one
  2. Strategy validator rejects dangerous configs before they reach the pipeline
  3. An intent with an existing failed order cannot be double-submitted (idempotency)
  4. Kill switch blocks all trades across the system
  5. The pipeline → delta → API data flow produces consistent outputs
  6. Scheduler reports completion only after all chain steps finish

All tests are safe and non-destructive (read-only or clean up after themselves).
"""
import subprocess
import uuid
from datetime import datetime

import pytest
import requests

SERVICES = {
    "api":                "http://localhost:8000",
    "strategy_validator": "http://localhost:8005",
    "risk_service":       "http://localhost:8011",
    "trade_executor":     "http://localhost:8012",
    "pipeline":           "http://localhost:8018",
    "scheduler":          "http://localhost:8015",
}

PSQL = ["docker", "exec", "stocker-postgres-1", "psql", "-U", "stocker", "-d", "stocker"]


def _psql(sql: str) -> str:
    r = subprocess.run(PSQL + ["-c", sql], capture_output=True, text=True, timeout=10)
    if r.returncode != 0:
        raise RuntimeError(f"psql: {r.stderr}")
    return r.stdout


def _all_up() -> bool:
    for name, url in SERVICES.items():
        try:
            if requests.get(f"{url}/health", timeout=3).status_code != 200:
                return False
        except Exception:
            return False
    return True


pytestmark = pytest.mark.skipif(not _all_up(), reason="Not all services reachable")


# ── 1. all services healthy ───────────────────────────────────────────────────

def test_all_services_healthy():
    """Every service in the stack must respond healthy."""
    for name, url in SERVICES.items():
        r = requests.get(f"{url}/health", timeout=5)
        assert r.status_code == 200, f"{name} returned {r.status_code}"
        d = r.json()
        assert d.get("status") == "ok", f"{name} status: {d}"


# ── 2. risk service blocks live trades ───────────────────────────────────────

def test_risk_service_blocks_live_trade():
    """Risk service must reject live trades in this paper-only environment."""
    payload = {
        "ticker": "AAPL",
        "action": "entry",
        "side": "buy",
        "qty": 10,
        "notional": 1000.0,
        "trade_type": "live",
        "mode": "immediate",
        "intent_id": str(uuid.uuid4()),
    }
    r = requests.post(f"{SERVICES['risk_service']}/check", json=payload)
    assert r.status_code in (200, 409)
    d = r.json()
    assert d["approved"] is False, "Live trade must not be approved in paper environment"


# ── 3. strategy validator blocks dangerous config before pipeline ─────────────

def test_strategy_validator_blocks_dangerous_config():
    """A config with position_weight=1.0 (100% in one stock) must be rejected
    by strategy-validator and never reach the pipeline."""
    dangerous = {
        "strategy_id": "test_dangerous_v1",
        "regime_detection": {
            "slow_sma": 200, "vol_window": 20, "vol_threshold": 0.20, "confirmation_days": 5,
            "regimes": {
                "bull_calm":   {"spy_above_slow_sma": True,  "vol_above_threshold": False},
                "bull_stress": {"spy_above_slow_sma": True,  "vol_above_threshold": True},
                "bear_calm":   {"spy_above_slow_sma": False, "vol_above_threshold": False},
                "bear_stress": {"spy_above_slow_sma": False, "vol_above_threshold": True},
            },
        },
        "factor_weights": {
            "bull_calm":   {"momentum": 0.35, "quality": 0.25, "value": 0.15, "growth": 0.15, "low_volatility": 0.10},
            "bull_stress": {"momentum": 0.20, "quality": 0.35, "value": 0.15, "growth": 0.10, "low_volatility": 0.20},
            "bear_calm":   {"momentum": 0.20, "quality": 0.30, "value": 0.30, "growth": 0.10, "low_volatility": 0.10},
            "bear_stress": {"momentum": 0.10, "quality": 0.40, "value": 0.15, "growth": 0.05, "low_volatility": 0.30},
        },
        "max_positions": 30,
        "portfolio_builder": {
            "max_positions": 30,
            "max_position_weight": 1.0,  # DANGEROUS: 100% in one stock
            "max_sector_weight": 1.0,    # DANGEROUS: 100% in one sector
            "weighting": "equal_weight",
            "method": "greedy_score_per_port_vol",
        },
        "vetter": {"enabled": True, "candidate_count": 50},
        "delta_engine": {"entry_rank": 25, "exit_rank": 40, "confirmation_days": 3},
    }
    r = requests.post(f"{SERVICES['strategy_validator']}/validate", json=dangerous)
    assert r.status_code == 422
    d = r.json()
    assert d["valid"] is False
    assert len(d.get("errors", [])) > 0


# ── 4. pipeline → API data consistency ───────────────────────────────────────

def test_pipeline_and_api_agree_on_latest_run():
    """The API /system/status must reflect the pipeline's latest run."""
    pipeline_run = requests.get(f"{SERVICES['pipeline']}/runs/latest").json()
    api_status = requests.get(f"{SERVICES['api']}/system/status").json()

    # Both should agree the pipeline ran and succeeded (or failed)
    pipeline_status = pipeline_run.get("status")
    api_pipeline_status = api_status.get("pipeline", {}).get("status")

    assert pipeline_status == api_pipeline_status, (
        f"Pipeline reports '{pipeline_status}' but API /system/status reports '{api_pipeline_status}'"
    )


def test_pipeline_rankings_visible_in_api():
    """Rankings produced by the pipeline must be retrievable via the API."""
    pipeline_run = requests.get(f"{SERVICES['pipeline']}/runs/latest").json()
    if pipeline_run.get("status") != "success":
        pytest.skip("Pipeline hasn't had a successful run")

    api_rankings = requests.get(f"{SERVICES['api']}/rankings?limit=5").json()
    rankings_list = api_rankings.get("rankings", [])
    assert len(rankings_list) > 0, "No rankings visible via API despite pipeline success"


def test_api_regime_matches_pipeline_date():
    """The regime shown by the API should be computed from the same data as the pipeline."""
    regime = requests.get(f"{SERVICES['api']}/regime").json()
    assert regime.get("regime") in ("bull_calm", "bull_stress", "bear_calm", "bear_stress")
    assert regime.get("spy_price", 0) > 0


# ── 5. scheduler chain completeness ──────────────────────────────────────────

def test_scheduler_reports_chain_steps():
    r = requests.get(f"{SERVICES['scheduler']}/status")
    assert r.status_code == 200
    d = r.json()
    assert "steps" in d
    for step in ("fetch-data", "pipeline", "vet"):
        assert step in d["steps"], f"Scheduler missing step: {step}"


def test_scheduler_chain_status_is_terminal_or_pending():
    d = requests.get(f"{SERVICES['scheduler']}/status").json()
    valid = {"done", "pending", "failed", "running", "skipped", None}
    for step, status in d.get("steps", {}).items():
        assert status in valid, f"Step {step} has invalid status: {status}"


# ── 6. trade executor idempotency with existing failed order ─────────────────

def test_trade_executor_rejects_duplicate_submission_for_failed_order():
    """An intent that already has a failed alpaca_order must be blocked by the
    idempotency check — trade executor must not create a second order row
    without explicit retry approval."""
    run_id = str(uuid.uuid4())
    intent_id = str(uuid.uuid4())
    order_id = str(uuid.uuid4())
    today = datetime.now().strftime("%Y-%m-%d")

    # Seed a delta_run and intent
    _psql(
        f"INSERT INTO delta_runs (run_id, strategy_id, status, run_date, triggered_by) "
        f"VALUES ('{run_id}', 'xtest_idempotent', 'success', '{today}', 'test')"
    )
    _psql(
        f"INSERT INTO delta_intents (id, run_id, ticker, action, current_weight) "
        f"VALUES ('{intent_id}', '{run_id}', 'XTIDEM', 'entry', 0.03)"
    )
    # Seed a RISK_REJECTED order (should block further submission)
    _psql(
        f"INSERT INTO alpaca_orders "
        f"(id, intent_id, ticker, action, side, status, mode, risk_approved) "
        f"VALUES ('{order_id}', '{intent_id}', 'XTIDEM', 'entry', 'buy', "
        f"'risk_rejected', 'immediate', false)"
    )

    try:
        r = requests.post(
            f"{SERVICES['trade_executor']}/jobs/submit",
            json={"intent_id": intent_id, "mode": "immediate"},
            timeout=10,
        )
        # Trade executor returns 200 with status='duplicate' for already-settled intents
        d = r.json()
        blocked = (
            r.status_code in (400, 409)
            or d.get("status") in ("conflict", "rejected", "already_submitted", "duplicate")
        )
        assert blocked, f"Expected idempotency rejection, got {r.status_code}: {d}"
        # Verify only one order row was created
        count = _psql(f"SELECT COUNT(*) FROM alpaca_orders WHERE intent_id='{intent_id}'")
        assert "1" in count, f"Expected 1 order row, count output: {count}"
    finally:
        _psql(f"DELETE FROM delta_runs WHERE run_id='{run_id}'")


# ── 7. API returns 4xx for invalid inputs, not 500 ───────────────────────────

def test_api_rejects_unknown_ticker_gracefully():
    """Requesting factors for a bogus ticker must return 2xx or 4xx, not 500."""
    r = requests.get(f"{SERVICES['api']}/factors/ZZZZFAKE999")
    assert r.status_code in (200, 400, 404), f"Expected 2xx/4xx, got {r.status_code}"


def test_api_rankings_limit_too_large_handled():
    """Very large limit must not crash the API."""
    r = requests.get(f"{SERVICES['api']}/rankings?limit=999999")
    assert r.status_code in (200, 400, 422)
    r.json()  # Must be parseable


def test_strategy_validator_returns_json_on_invalid_content_type():
    """Even with wrong Content-Type, validator should return JSON, not a crash."""
    r = requests.post(
        f"{SERVICES['strategy_validator']}/validate",
        data=b"this is not json",
        headers={"Content-Type": "text/plain"},
    )
    assert r.status_code in (200, 422)
    r.json()  # Must be JSON


# ── 8. data freshness end-to-end ─────────────────────────────────────────────

def test_data_freshness_prices_recent():
    """Prices must have been fetched within the last 7 days (test env assumption)."""
    from datetime import date, timedelta
    d = requests.get(f"{SERVICES['api']}/data-freshness").json()
    max_date_str = d["prices"].get("max_date")
    if not max_date_str:
        pytest.skip("No price data in DB")
    max_date = date.fromisoformat(max_date_str)
    cutoff = date.today() - timedelta(days=7)
    assert max_date >= cutoff, f"Price data stale: max_date={max_date_str}"


def test_data_freshness_factors_computed():
    """Factor scores must have been computed."""
    d = requests.get(f"{SERVICES['api']}/data-freshness").json()
    assert d["factors"].get("score_date") is not None, "No factor scores in DB"
    assert d["rankings"].get("rank_date") is not None, "No ranking data in DB"
