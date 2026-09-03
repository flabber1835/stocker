from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_official_production_runtime_checkouts_include_frozen_controller_rule() -> None:
    paths = (
        ROOT / ".github/workflows/backtester-financial-causality-gate.yml",
        ROOT / ".github/workflows/backtester-pit-certification-suite.yml",
        ROOT / ".github/workflows/backtester-production-strict-pit-year-worker.yml",
    )
    for path in paths:
        text = path.read_text(encoding="utf-8")
        assert "docs/sentinel-handoff/00_README" in text, path.name
