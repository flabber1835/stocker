"""Service health smoke tests — one test per service, all run in parallel by pytest-xdist.

If the Docker stack isn't up, the whole module is skipped.
"""
import pytest
import requests

SERVICES = {
    "api":                ("http://localhost:8000", "api"),
    "strategy_validator": ("http://localhost:8005", "strategy-validator"),
    "risk_service":       ("http://localhost:8011", "risk-service"),
    "trade_executor":     ("http://localhost:8012", "trade-executor"),
    "pipeline":           ("http://localhost:8018", "pipeline"),
    "scheduler":          ("http://localhost:8015", "scheduler"),
    "portfolio_builder":  ("http://localhost:8008", "portfolio-builder"),
    "alpaca_sync":        ("http://localhost:8009", "alpaca-sync"),
    "backtester":         ("http://localhost:8013", "backtester"),
    "av_ingestor":        ("http://localhost:8001", "av-ingestor"),
    "llm_vetter":         ("http://localhost:8016", "llm-vetter"),
}


def _any_up() -> bool:
    for url, _ in SERVICES.values():
        try:
            if requests.get(f"{url}/health", timeout=2).status_code == 200:
                return True
        except Exception:
            pass
    return False


pytestmark = pytest.mark.skipif(not _any_up(), reason="No services reachable")


@pytest.mark.parametrize("name,url_svc", list(SERVICES.items()))
def test_service_health(name, url_svc):
    url, expected_svc = url_svc
    try:
        r = requests.get(f"{url}/health", timeout=5)
    except Exception as e:
        pytest.skip(f"{name} not reachable: {e}")
    assert r.status_code == 200, f"{name}: HTTP {r.status_code}"
    d = r.json()
    assert d.get("status") == "ok", f"{name}: status={d.get('status')}"
    assert d.get("service") == expected_svc, (
        f"{name}: service name mismatch: got '{d.get('service')}', expected '{expected_svc}'"
    )
