"""Target tab surfaces sleeve β, effective (cash-inclusive) β, and target cash %."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DASH_JS = (ROOT / "services" / "dashboard" / "static" / "dashboard.js").read_text()


def test_target_renders_sleeve_and_effective_beta():
    assert "sleeve &beta;" in DASH_JS
    assert "eff &beta;" in DASH_JS
    assert "pr.effective_beta" in DASH_JS


def test_target_renders_cash_pct():
    assert "pr.cash_pct" in DASH_JS
    assert "cash " in DASH_JS  # the rendered label
