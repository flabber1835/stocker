"""The parity manifest.

`turnover_penalty` proved the factor-coverage contract was one instance of a
general problem: live passed `current_holdings`/`turnover_penalty` into
greedy_select and the simulator did not, so any nonzero penalty was scored as
zero. Nothing announced it — the tunnel returned a perfectly ordinary number.

The manifest declares, per config field, whether the tunnel honours it, and
refuses a config that SETS an ignored field. These tests keep it honest in both
directions: it must refuse what it cannot model, and must not refuse everything.
"""
import ast
import os

import pytest
import yaml
from stock_strategy_shared.schemas.strategy import StrategyConfig

from app.parity import (
    HONOURED,
    IGNORED,
    PARITY,
    PARTIAL,
    check_config_parity,
    enforcement_enabled,
    unclassified_fields,
    verdict_for,
)

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")


def _cfg(name):
    with open(os.path.join(ROOT, "strategies", f"{name}.yaml")) as f:
        return StrategyConfig(**yaml.safe_load(f))


# ── the declaration ─────────────────────────────────────────────────────────

def test_every_schema_field_is_classified():
    """A NEW config field must fail CI until someone decides whether the tunnel
    honours it. Every defect in this batch was something nobody had to decide
    about."""
    assert unclassified_fields() == []


def test_verdicts_are_from_the_known_set():
    for path, (verdict, why) in PARITY.items():
        assert verdict in (HONOURED, PARTIAL, IGNORED), path
        # A reason, not a length. "documentation only" says everything needed;
        # an arbitrary character floor would just push people to pad it.
        assert why and why.strip(), f"{path}: a verdict without a reason is a guess"


def test_a_more_specific_declaration_beats_the_section():
    """vetter.* is IGNORED as a section, but the falling-knife veto IS modelled."""
    assert verdict_for("vetter.falling_knife")[0] == HONOURED
    assert verdict_for("vetter.max_searches_per_ticker")[0] == IGNORED


def test_an_undeclared_path_defaults_to_ignored():
    """Fail-closed: an unknown field is assumed unmodelled, not assumed fine."""
    assert verdict_for("something.nobody.declared")[0] == IGNORED


# ── the gate ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", ["momentum_rotation_v2", "quality_core_v1",
                                  "challenger_lowvol_v1"])
def test_real_configs_pass(name):
    """A gate that refuses everything is a gate someone switches off."""
    assert check_config_parity(_cfg(name)) == []


def test_the_turnover_penalty_that_motivated_this_is_now_honoured():
    assert PARITY["portfolio_builder.turnover_penalty"][0] == HONOURED
    d = _cfg("momentum_rotation_v2").model_dump()
    d["portfolio_builder"]["turnover_penalty"] = 0.3
    assert check_config_parity(StrategyConfig(**d)) == [], (
        "a nonzero turnover penalty must now be scorable, not refused")


def test_setting_an_ignored_field_is_refused():
    d = _cfg("momentum_rotation_v2").model_dump()
    d["universe"]["require_fundamentals"] = True     # declared IGNORED
    v = check_config_parity(StrategyConfig(**d))
    assert len(v) == 1 and "require_fundamentals" in v[0]


def test_an_ignored_field_left_at_its_default_is_not_a_violation():
    """A field nobody set is not a claim about behaviour. Refusing on defaults
    would refuse every config ever written."""
    d = _cfg("momentum_rotation_v2").model_dump()
    assert d["universe"]["require_fundamentals"] is False
    assert check_config_parity(StrategyConfig(**d)) == []


def test_sections_themselves_are_never_violations():
    """Only LEAVES are settings. Flagging the section dict would report one
    violation per section on every config."""
    v = check_config_parity(_cfg("speculative_growth_v1"))
    assert all("'universe'" not in x and "'vetter'" not in x for x in v), v


def test_vetter_llm_knobs_are_inert_under_drawdown_only():
    """Every real config sets a prompt file and search budgets, and every real
    config runs mode: drawdown_only, where none of them are consulted. Firing on
    a field that cannot affect the run is noise, and noise gets switched off."""
    cfg = _cfg("momentum_rotation_v2")
    assert cfg.vetter.mode == "drawdown_only"
    assert cfg.vetter.system_prompt_file          # it IS set
    assert check_config_parity(cfg) == []


def test_vetter_llm_knobs_DO_bite_in_llm_mode():
    """The mirror case — otherwise the inertness rule would be a blanket exemption."""
    d = _cfg("momentum_rotation_v2").model_dump()
    d["vetter"]["mode"] = "llm"
    d["vetter"]["max_searches_per_ticker"] = 9
    v = check_config_parity(StrategyConfig(**d))
    assert any("max_searches_per_ticker" in x for x in v), v


def test_violation_messages_state_the_consequence():
    d = _cfg("momentum_rotation_v2").model_dump()
    d["universe"]["require_fundamentals"] = True
    msg = check_config_parity(StrategyConfig(**d))[0]
    assert "does not model it" in msg
    assert "differs from the one described" in msg


# ── enforcement flag ────────────────────────────────────────────────────────

@pytest.mark.parametrize("val,expected", [
    ("false", False), ("0", False), ("off", False), ("no", False),
    ("true", True), ("", True)])
def test_enforcement_flag(monkeypatch, val, expected):
    monkeypatch.setenv("BT_PARITY_ENFORCE", val)
    assert enforcement_enabled() is expected


def test_violations_are_computed_even_when_enforcement_is_off(monkeypatch):
    """The flag governs whether a violation is FATAL, never whether it is seen."""
    monkeypatch.setenv("BT_PARITY_ENFORCE", "false")
    d = _cfg("momentum_rotation_v2").model_dump()
    d["universe"]["require_fundamentals"] = True
    assert check_config_parity(StrategyConfig(**d)) != []


# ── the AST check that would have caught the original gap ───────────────────

def test_live_and_tunnel_selection_call_sites_agree_on_kwargs():
    """THE regression for turnover_penalty. Live and the tunnel call the SAME
    shared functions; the gap was purely in which kwargs each passed. Comparing
    the call sites catches the next such divergence the day it appears."""
    def kwargs_of(path, fname):
        with open(os.path.join(ROOT, path)) as f:
            tree = ast.parse(f.read())
        found = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
                if name == fname:
                    found |= {k.arg for k in node.keywords if k.arg}
        return found

    for fname in ("greedy_select", "compute_weights"):
        live = kwargs_of("services/portfolio-builder/app/main.py", fname)
        tunnel = kwargs_of("services/bt-engine/app/sim.py", fname)
        assert live, f"no live {fname} call site found — did the code move?"
        assert not (live - tunnel), (
            f"{fname}: live passes {sorted(live - tunnel)} that the wind tunnel "
            f"does not — the config would be scored as if those were unset")


def test_crash_brake_is_not_claimed_HONOURED_without_a_live_path():
    """A verdict is a claim about LIVE, not about the simulator.

    crash_brake was declared HONOURED while the live pipeline never called the
    brake and the trade-executor had no path for risk_reduce/risk_restore — so a
    tunnel result described behaviour the live book could not reproduce. That is
    precisely the lie this manifest exists to prevent, and the identical error had
    already been corrected once for portfolio_drawdown_guard.

    The check is mechanical: HONOURED requires the live chain to actually invoke
    the shared module. Promote the verdict when that call exists, not before.
    """
    import os

    from app.parity import HONOURED, verdict_for

    verdict, reason = verdict_for("crash_brake.enabled")
    root = os.path.join(os.path.dirname(__file__), "..", "..")
    live = open(os.path.join(root, "services", "pipeline", "app", "main.py")).read()
    live_calls_it = "evaluate_crash_state" in live

    if verdict == HONOURED:
        assert live_calls_it, (
            "crash_brake is declared HONOURED but services/pipeline never calls "
            "evaluate_crash_state — the tunnel would be scoring behaviour live "
            "cannot reproduce")
    else:
        assert not live_calls_it, (
            "the live chain now evaluates the crash brake — promote the parity "
            "verdict to HONOURED (and check the executor accepts risk_reduce / "
            "risk_restore)")
    assert reason
