from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
LAUNCHER = ROOT / "backtester" / "run_production_current_main_strict_pit_20y.py"
CURRENT_MAIN_SHA = "6d07c2b76066121906e50b4c11876c48849144a0"


def _load_launcher():
    spec = importlib.util.spec_from_file_location("current_main_launcher_test", LAUNCHER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_launcher_pins_current_main_and_forbids_source_patch() -> None:
    text = LAUNCHER.read_text(encoding="utf-8")
    assert CURRENT_MAIN_SHA in text
    assert '"sentinel/core/production.py": "e4ebfebae2fa1a737c52063af63003a82b6e19cf"' in text
    assert '"shared/stock_strategy_shared/wealth_core/state.py": "1921399aca503ae5e2cbfd6125792c09464ba22b"' in text
    assert "status\", \"--porcelain" in text
    assert "patched=false" in text
    assert "apply_production_cooldown_age_zero" not in text


def test_launcher_requires_experiment_start_origin_main_equality() -> None:
    text = LAUNCHER.read_text(encoding="utf-8")
    assert "verify_experiment_start_origin_main(root)" in text
    assert "+refs/heads/main:refs/remotes/origin/main" in text
    assert '"rev-parse", "refs/remotes/origin/main"' in text
    assert "resolved != CURRENT_MAIN_SHA" in text


def test_current_main_kernel_is_the_production_advance_state_target() -> None:
    import sentinel.core.production as production
    import sentinel.core.kernel as kernel

    source = Path(production.__file__).read_text(encoding="utf-8")
    assert "from sentinel.core.kernel import advance_session" in source
    assert "result = advance_session(" in source
    assert callable(kernel.advance_session)


def test_current_main_kernel_executes_prior_orders_before_close_decision() -> None:
    from stock_strategy_shared.wealth_core import adapter

    import inspect
    source = inspect.getsource(adapter.step_session)
    fill_index = min(source.index("apply_exit("), source.index("apply_entry("))
    decision_index = source.index("decide(")
    assert fill_index < decision_index
    assert "execute orders decided BEFORE this session" in source


def test_strict_pit_stack_bridges_plan_session_to_current_kernel_owner() -> None:
    code = (
        "import backtester.run_production_strict_pit_20y as replay; "
        "import sentinel.core.kernel as kernel; "
        "import sentinel.core.production as production; "
        "assert kernel.plan_session is replay._current_plan_session_proxy; "
        "assert production.plan_session is replay.strict._plan_session_with_boundary_evidence; "
        "assert replay.strict._real_plan_session is replay._exact_plan_session"
    )
    proc = subprocess.run(
        [sys.executable, "-c", code],
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    assert proc.returncode == 0, proc.stdout


def test_launcher_rejects_nonmatching_or_dirty_production_checkout(tmp_path: Path) -> None:
    launcher = _load_launcher()
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "config", "user.name", "test"], check=True)
    (tmp_path / "README").write_text("x", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "README"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-q", "-m", "fixture"], check=True)
    with pytest.raises(RuntimeError, match="not the certified current-main revision"):
        launcher.verify_unmodified_current_main(tmp_path)