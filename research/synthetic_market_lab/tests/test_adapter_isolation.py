from __future__ import annotations

import csv
import gzip

import pytest

from research.synthetic_market_lab.adapter import export_backtester_tables
from research.synthetic_market_lab.pit import SyntheticPITWorld


def header(path):
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return next(csv.reader(handle))


def test_adapter_accepts_only_public_namespace(adversarial_world, tmp_path):
    world, cfg, _ = adversarial_world
    with pytest.raises(ValueError):
        export_backtester_tables(world / "ground_truth", tmp_path / "bad")
    with pytest.raises(ValueError):
        SyntheticPITWorld(world / "ground_truth")


def test_adapter_exports_backtester_contract_without_latent_columns(adversarial_world, tmp_path):
    world, cfg, _ = adversarial_world
    out = tmp_path / "adapter"
    counts = export_backtester_tables(world / "public", out, benchmark_alias=cfg.benchmark_adapter_alias)
    assert all(value > 0 for value in counts.values())
    assert header(out / "bt_prices.csv.gz")[:8] == ["ticker", "date", "open", "high", "low", "close", "adj_close", "volume"]
    assert "datekey" in header(out / "bt_fundamentals.csv.gz")
    forbidden = {"regime", "health", "distress_probability", "latent_value", "shock_id", "true_assets", "true_revenue"}
    for path in out.glob("*.csv.gz"):
        assert not (set(header(path)) & forbidden)


def test_adapter_benchmark_alias_is_spy_by_default_contract(adversarial_world, tmp_path):
    world, cfg, _ = adversarial_world
    out = tmp_path / "adapter"
    export_backtester_tables(world / "public", out, benchmark_alias=cfg.benchmark_adapter_alias)
    with gzip.open(out / "bt_prices.csv.gz", "rt", encoding="utf-8", newline="") as handle:
        seen = {row["ticker"] for row in csv.DictReader(handle)}
    assert cfg.benchmark_adapter_alias in seen


def test_lab_python_modules_do_not_import_production_strategy_or_runtime_packages():
    import ast
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    forbidden_roots = {"sentinel", "wealth_core", "champion", "caesar", "median5", "services"}
    violations = []
    for path in sorted(root.glob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module.split(".")[0]]
            else:
                continue
            if forbidden_roots & set(names):
                violations.append((path.name, names))
    assert violations == []
