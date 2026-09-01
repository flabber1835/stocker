"""
Root conftest: ensures each service test package imports the right 'app' module.

All conftest.py files are loaded upfront before any test collection begins, so
module-level sys.path.insert() in child conftest files all accumulate. This root
conftest uses pytest_pycollect_makemodule — which fires immediately before each
test module is imported — to move the correct service path to sys.path[0].
"""
import importlib
import sys
import os
from pathlib import Path

_SERVICE_MAP = {
    "alpaca_sync":        "alpaca-sync",
    "api":                "api",
    "av_ingestor":        "av-ingestor",
    "backtester":         "backtester",
    "dashboard":          "dashboard",
    "delta_engine":       "pipeline",  # delta-engine consolidated into pipeline (Phase 7)
    "factor_engine":      "factor-engine",
    "llm_gateway":        "llm-gateway",
    "llm_vetter":         "llm-vetter",
    "pipeline":           "pipeline",
    "portfolio_builder":  "portfolio-builder",
    "ranker":             "ranker",
    "risk_service":       "risk-service",
    "scheduler":          "scheduler",
    "strategy_validator": "strategy-validator",
    "trade_executor":     "trade-executor",
}

_ROOT = Path(__file__).parent.parent


_NEEDS_SHARED = {"strategy-validator"}

def _activate_service(test_dir_name: str) -> None:
    """Clear cached app modules and move the right service path to sys.path[0]."""
    service = _SERVICE_MAP.get(test_dir_name)
    if service is None:
        return
    service_path = str(_ROOT / "services" / service)
    shared_path = str(_ROOT / "shared")
    for key in list(sys.modules.keys()):
        if key == "app" or key.startswith("app."):
            del sys.modules[key]

    # The backtester suite now tests two distinct things: the retained HTTP
    # service under services/backtester (imported as ``app``), and the
    # certification package at repository-root/backtester.  Putting only the
    # service/test directory first lets tests/backtester/__init__.py become the
    # top-level ``backtester`` package and silently tests the wrong module.
    if test_dir_name == "backtester":
        root_path = str(_ROOT)
        for path in (root_path, service_path):
            while path in sys.path:
                sys.path.remove(path)
        if Path(service_path).is_dir():
            sys.path.insert(0, service_path)
        sys.path.insert(0, root_path)
        loaded = sys.modules.get("backtester")
        expected = (_ROOT / "backtester" / "__init__.py").resolve()
        if loaded is not None:
            observed_file = getattr(loaded, "__file__", None)
            observed = Path(observed_file).resolve() if observed_file else None
            if observed != expected:
                for key in list(sys.modules):
                    if key == "backtester" or key.startswith("backtester."):
                        del sys.modules[key]
        runtime = importlib.import_module("backtester")
        observed = Path(runtime.__file__).resolve()
        if observed != expected:
            raise RuntimeError(
                f"backtester package shadowing: expected {expected}, imported {observed}"
            )
        return

    if service_path in sys.path:
        sys.path.remove(service_path)
    sys.path.insert(0, service_path)
    if service in _NEEDS_SHARED and shared_path not in sys.path:
        sys.path.insert(1, shared_path)


def pytest_pycollect_makemodule(module_path: Path, parent):
    """Fires immediately before pytest imports a test module.
    Activates the correct service so module-level imports resolve correctly."""
    _activate_service(module_path.parent.name)


def pytest_runtest_setup(item):
    """Before each test, re-activate the service in case a previous suite
    left a stale 'app' module in sys.modules."""
    _activate_service(Path(str(item.fspath)).parent.name)


# ── Playwright browser resolution (shared by every browser-tier suite) ────────
# `pip install playwright` alone is not enough: the wheel expects the browser
# build IT was pinned to. This environment ships Chromium 1194 at
# /opt/pw-browsers while a newer wheel looks for 1228, so a suite that only
# checked "does playwright import?" ERRORED instead of skipping the moment
# playwright was installed. Resolve an executable that actually exists, and let
# the caller skip cleanly when none does.

def playwright_chromium_path() -> str | None:
    """Path to a usable Chromium, or None to fall back to the bundled build."""
    import os as _os
    for cand in (_os.getenv("PW_CHROMIUM"), "/opt/pw-browsers/chromium"):
        if cand and _os.path.exists(cand):
            return cand
    return None


def launch_chromium(playwright, **kwargs):
    """chromium.launch() that prefers the bundled build and falls back to the
    preinstalled one. Raises the ORIGINAL error if neither works."""
    kwargs.setdefault("headless", True)
    kwargs.setdefault("args", ["--no-sandbox", "--disable-dev-shm-usage"])
    try:
        return playwright.chromium.launch(**kwargs)
    except Exception:
        path = playwright_chromium_path()
        if not path:
            raise
        return playwright.chromium.launch(executable_path=path, **kwargs)
