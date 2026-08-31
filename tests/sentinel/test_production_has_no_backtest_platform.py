"""Architectural guard for the production/certification separation."""
from __future__ import annotations

import os
from pathlib import Path


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])
REMOVED = (
    "Dockerfile.base",
    "docker-compose.backtest.yml",
    "services/backtester",
    "services/bt-data",
    "services/bt-engine",
)
RECOVERY_PIN = (
    "research/backtester@7f12174273dfa071a25614d2c4a1be8ebfdfbc3a")


def _materially_present(path: Path) -> bool:
    if path.is_file():
        return True
    return path.is_dir() and any(
        item.is_file() and "__pycache__" not in item.parts
        for item in path.rglob("*"))


def test_the_legacy_backtest_platform_is_absent():
    present = [name for name in REMOVED if _materially_present(ROOT / name)]
    assert not present, f"legacy backtest platform returned: {present}"


def test_production_build_and_ci_do_not_name_legacy_surfaces():
    surface = "\n".join((ROOT / name).read_text() for name in (
        "Dockerfile.sentinel-test",
        ".github/workflows/sentinel-safety.yml",
        "Makefile",
    ))
    forbidden = (
        "docker-compose.backtest",
        "services/backtester",
        "services/bt-data",
        "services/bt-engine",
        "stocker-bt-engine",
        "stocker-bt-data",
    )
    found = [token for token in forbidden if token in surface]
    assert not found, f"production surface still names legacy platform: {found}"


def test_the_preserved_certification_source_is_documented_exactly():
    decision = (ROOT / "docs/production-certification-separation.md").read_text()
    assert RECOVERY_PIN in decision
