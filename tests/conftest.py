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

import pytest


@pytest.fixture(autouse=True)
def isolated_image_backup_policy(tmp_path, monkeypatch):
    """Unit fixtures are developer environments, even inside the CI image.

    A synthetic database has no deployed backup media. Substitute only that
    filesystem identity; explicit REQUIRED_V1 flags still enforce every real
    media/lock check. Dedicated policy tests install the production marker bytes.
    Container/process boundary probes run outside this in-process fixture.
    """
    from sentinel import backup_runtime_authority
    monkeypatch.setattr(backup_runtime_authority, "POLICY_MARKER",
                        tmp_path / "absent-production-backup-policy")

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
