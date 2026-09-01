from __future__ import annotations

from pathlib import Path
import sys

import pytest

from backtester.research_terminal_grace_overlay import (
    ResearchFinancialGradeError,
    capacity_guard,
    exact_terminal_economics,
)


def test_research_capacity_matches_production_prior20_10pct_rule() -> None:
    prior = [100_000.0] * 20
    assert capacity_guard(
        10_000.0, prior, security_id="sid", session="2020-01-02"
    ) == pytest.approx(0.10)
    with pytest.raises(ResearchFinancialGradeError, match="capacity ceiling exceeded"):
        capacity_guard(
            10_001.0, prior, security_id="sid", session="2020-01-02"
        )
    with pytest.raises(ResearchFinancialGradeError, match="capacity authority incomplete"):
        capacity_guard(
            1.0, prior[:19], security_id="sid", session="2020-01-02"
        )


def test_research_exact_terminal_cash_and_conversion_economics() -> None:
    cash = exact_terminal_economics(
        kind="CASH_MERGER", shares=100, cash_per_share=36.5
    )
    assert cash == {"cash": 3650.0, "delivered_shares": 0, "fraction": 0.0}

    mixed = exact_terminal_economics(
        kind="CASH_PLUS_STOCK",
        shares=101,
        cash_per_share=25.0,
        exchange_ratio=0.8367,
        cash_in_lieu_price=56.17,
    )
    exact_shares = 101 * 0.8367
    whole = int(exact_shares)
    fraction = exact_shares - whole
    assert mixed["delivered_shares"] == whole
    assert mixed["fraction"] == pytest.approx(fraction)
    assert mixed["cash"] == pytest.approx(101 * 25.0 + fraction * 56.17)


def test_corrected_production_wrapper_composes_with_fullstack_pit_step() -> None:
    import backtester.run_ldrc_corrected_warmup_cash as corrected

    # The corrected layer must capture the full-stack/progress wrapper. A later
    # strict-certification wrapper is allowed to sit above the corrected layer.
    assert corrected._pre_measurement_account_step is corrected.prod._emit_progress
    current = corrected.runner.OverlayAccount.step
    if current is not corrected._measured_account_step:
        strict = sys.modules.get("backtester.run_production_strict_pit_certification")
        assert strict is not None
        assert strict._real_step is corrected._measured_account_step
    source = Path(corrected.__file__).read_text(encoding="utf-8")
    measured = source[
        source.index("def _measured_account_step"):
        source.index("runner.OverlayAccount.step = _measured_account_step")
    ]
    assert "_pre_measurement_account_step" in measured
    assert "base._real_overlay_step" not in measured


def test_strict_research_generated_source_contains_exact_terms_and_capacity() -> None:
    import backtester.run_research_strict_pit_20y as research

    source = research.corrected.transformed_source(
        "fullpit", Path("/tmp/research-financial-grade-regression")
    )
    assert "load_frozen_terminal_terms(" in source
    assert "_research_exact_terminal_economics(" in source
    assert "_research_capacity_guard(s.qty" in source
    assert "_research_capacity_guard(s.pending_shares" in source
    assert "_capacity_volumes[int(_tid0)]" in source
    compile(source, "<strict-research-financial-grade>", "exec")
