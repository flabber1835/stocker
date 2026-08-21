import inspect
from pathlib import Path

from tools import sentinel_concordance_differential as diff


def test_reference_is_code_not_an_oracle_tape():
    source = Path(diff.__file__).read_text(encoding="utf-8")
    assert "sentinel.controller.ldrc" not in source
    assert "sentinel.controller.recent_leadership" not in source
    assert "sentinel.controller.concordance import" not in source
    assert ".csv" not in source
    assert diff.STRATEGY == "sentinel-concordance-simplified-ldrc"
    assert diff.STRATEGY_VERSION == 3


def test_reference_pins_exact_simplified_three_signal_constants():
    assert (
        diff.DIVERGENCE_CEILING,
        diff.WC_DRAWDOWN_TRIGGER,
        diff.RECENT_R20_TRIGGER,
        diff.SPY_R20_FLOOR,
        diff.RECOVERY_SESSIONS,
        diff.SPY_V_REBOUND,
    ) == (0.55, -0.10, -0.08, 0.00, 7, 0.11)


def test_production_audit_seam_is_observational_only():
    from sentinel.core import production
    signature = inspect.signature(production.advance_state)
    assert signature.parameters["concordance_audit"].default is None
    source = inspect.getsource(production.advance_state)
    assert "concordance_audit(" in source
    assert "= concordance_audit(" not in source


def test_reference_detects_wrong_effective_native_source():
    reference = diff.ReferenceConcordance()
    candidates = [
        type("Candidate", (), {
            "security_id": f"S{i:02d}", "momentum": float(100 - i),
            "recent": float(i),
        })()
        for i in range(30)
    ]
    closes = {f"S{i:02d}": 100.0 for i in range(30)}
    witness, _state = reference._witness(  # noqa: SLF001
        session="2026-01-02", candidate_rows=candidates,
        eligible_universe_count=30, signal_closes=closes)
    try:
        reference._ldrc(  # noqa: SLF001
            session="2026-01-02", native_allocation=1.0,
            effective_native_allocation=0.65, wc_drawdown=-0.05,
            recent_r20=witness["recent_r20"], recent_r40=witness["recent_r40"],
            spy_r20=0.01)
    except diff.DifferentialMismatch as exc:
        assert exc.detail["field"] == "effective_native_allocation"
    else:
        raise AssertionError("wrong effective-native source was accepted")
