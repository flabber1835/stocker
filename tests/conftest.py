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


_PAPER_DECOMPOSITION_LEGACY_MODULES = {
    "test_issue223_bil_evidence",
    "test_paper_activation",
    "test_paper_close_nav_gate",
    "test_preopen_paper_gate",
    "test_runtime_regressions_137_148_149_150",
}


@pytest.fixture(autouse=True)
def _paper_decomposition_legacy_test_seams(request, monkeypatch):
    """Route pre-Step-4 paper test doubles to their canonical module owners.

    The production package remains a declarative export surface. These older
    characterization tests still patch names that lived in the former monolith,
    so keep their doubles attached to the exact moved dependency during Step 4.
    """
    module_name = request.module.__name__.rsplit(".", 1)[-1]
    if module_name not in _PAPER_DECOMPOSITION_LEGACY_MODULES:
        return

    from sentinel import paper
    from sentinel.paper import (
        execution as paper_execution,
        finalization as paper_finalization,
        inspection as paper_inspection,
        preparation as paper_preparation,
        reconciliation as paper_reconciliation,
        recovery as paper_recovery,
        targets as paper_targets,
        validation as paper_validation,
    )

    # Names used directly by legacy tests but intentionally absent from the
    # public Step-4 compatibility surface.
    for name, owner in (
        ("SessionState", paper_preparation),
        ("advance_and_persist", paper_preparation),
        ("catchup", paper_preparation),
        ("load_rollout_state", paper_validation),
        ("load_window", paper_preparation),
    ):
        monkeypatch.setattr(paper, name, getattr(owner, name), raising=False)

    def forward(owner, name):
        """Make an old package-level patch drive the moved canonical seam."""
        if not hasattr(paper, name):
            monkeypatch.setattr(paper, name, getattr(owner, name), raising=False)

        def call(*args, **kwargs):
            return getattr(paper, name)(*args, **kwargs)

        monkeypatch.setattr(owner, name, call)

    # Direct imports retained by AST-equivalent moved functions need their test
    # doubles routed from the old monolithic patch location.
    for owner, names in (
        (paper_inspection, ("require_certified",)),
        (paper_preparation, (
            "advance_and_persist", "load_controller", "load_window",
            "require_current_authority", "runtime_strategy_identity",
            "shadow_target",
        )),
        (paper_validation, (
            "load_rollout_state", "require_current_authority",
            "runtime_strategy_identity", "shadow_target",
        )),
        (paper_execution, (
            "load_rollout_state", "require_current_authority",
        )),
        (paper_recovery, (
            "load_rollout_state", "require_current_authority",
        )),
        (paper_targets, ("shadow_target",)),
    ):
        for name in names:
            if hasattr(owner, name):
                forward(owner, name)

    # The old monolith exposed these private helpers at the same object patched
    # by the tests. Route the moved owner calls through that explicit seam.
    original_close_nav = paper_finalization._record_due_close_nav_or_refuse
    monkeypatch.setattr(
        paper, "_record_due_close_nav_or_refuse", original_close_nav,
        raising=False)

    def close_nav(*args, **kwargs):
        return paper._record_due_close_nav_or_refuse(*args, **kwargs)

    monkeypatch.setattr(
        paper_finalization, "_record_due_close_nav_or_refuse", close_nav)

    # Reconciliation deliberately exposes `reconcile` as its canonical test
    # dependency. Ensure the internal module reference observes that alias.
    canonical_reconciliation = paper_reconciliation.reconciliation

    class _ReconcileProxy:
        def __getattr__(self, name):
            if name == "reconcile":
                return paper_reconciliation.reconcile
            return getattr(canonical_reconciliation, name)

    monkeypatch.setattr(
        paper_reconciliation, "reconciliation", _ReconcileProxy())
