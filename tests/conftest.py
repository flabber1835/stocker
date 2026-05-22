"""
Root conftest: ensures each service test package imports the right 'app' module.

All conftest.py files are loaded upfront before any test collection begins, so
module-level sys.path.insert() in child conftest files all accumulate. This root
conftest uses pytest_pycollect_makemodule — which fires immediately before each
test module is imported — to move the correct service path to sys.path[0].
"""
import sys
import os
from pathlib import Path

_SERVICE_MAP = {
    "alpaca_sync":      "alpaca-sync",
    "api":              "api",
    "av_ingestor":      "av-ingestor",
    "backtester":       "backtester",
    "dashboard":        "dashboard",
    "delta_engine":     "pipeline",  # delta-engine consolidated into pipeline (Phase 7)
    "factor_engine":    "factor-engine",
    "llm_gateway":      "llm-gateway",
    "llm_vetter":       "llm-vetter",
    "pipeline":         "pipeline",
    "portfolio_builder":"portfolio-builder",
    "ranker":           "ranker",
    "risk_service":     "risk-service",
    "scheduler":        "scheduler",
    "trade_executor":   "trade-executor",
}

_ROOT = Path(__file__).parent.parent


def _activate_service(test_dir_name: str) -> None:
    """Clear cached app modules and move the right service path to sys.path[0]."""
    service = _SERVICE_MAP.get(test_dir_name)
    if service is None:
        return
    service_path = str(_ROOT / "services" / service)
    for key in list(sys.modules.keys()):
        if key == "app" or key.startswith("app."):
            del sys.modules[key]
    if service_path in sys.path:
        sys.path.remove(service_path)
    sys.path.insert(0, service_path)


def pytest_pycollect_makemodule(module_path: Path, parent):
    """Fires immediately before pytest imports a test module.
    Activates the correct service so module-level imports resolve correctly."""
    _activate_service(module_path.parent.name)


def pytest_runtest_setup(item):
    """Before each test, re-activate the service in case a previous suite
    left a stale 'app' module in sys.modules."""
    _activate_service(Path(str(item.fspath)).parent.name)
