from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path

from research.synthetic_market_lab.config import CompanyConfig, WorldConfig
from research.synthetic_market_lab.generator import generate_world
from research.synthetic_market_lab.io import sha256_file
from research.synthetic_market_lab.validate import validate_world


def rows(path):
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_identical_seed_and_config_reproduce_byte_for_byte(tmp_path):
    cfg = WorldConfig(seed=9191, years=1, companies=CompanyConfig(company_count=20, initially_listed_fraction=0.8))
    left = tmp_path / "left"; right = tmp_path / "right"
    generate_world(cfg, left); generate_world(cfg, right)
    left_files = sorted(p.relative_to(left) for p in left.rglob("*") if p.is_file())
    right_files = sorted(p.relative_to(right) for p in right.rglob("*") if p.is_file())
    assert left_files == right_files
    assert {str(p): sha256_file(left / p) for p in left_files} == {str(p): sha256_file(right / p) for p in right_files}


def test_different_seeds_create_materially_different_histories(tmp_path):
    cfg1 = WorldConfig(seed=1201, years=1, companies=CompanyConfig(company_count=20))
    cfg2 = WorldConfig(seed=1202, years=1, companies=CompanyConfig(company_count=20))
    left = tmp_path / "left"; right = tmp_path / "right"
    m1 = generate_world(cfg1, left); m2 = generate_world(cfg2, right)
    assert m1["world_id"] != m2["world_id"]
    assert sha256_file(left / "ground_truth/macro_daily.csv.gz") != sha256_file(right / "ground_truth/macro_daily.csv.gz")
    assert sha256_file(left / "public/prices.csv.gz") != sha256_file(right / "public/prices.csv.gz")


def test_accounting_identities_close_in_true_and_public_state(adversarial_world):
    world, _, _ = adversarial_world
    for path, cols in [
        (world / "ground_truth/company_quarterly.csv.gz", ("true_assets", "true_liabilities", "true_equity")),
        (world / "public/disclosures.csv.gz", ("assets", "liabilities", "equity")),
    ]:
        for row in rows(path):
            a, l, e = (float(row[c]) for c in cols)
            assert abs(a - (l + e)) <= max(1e-5, max(abs(a), abs(l), abs(e)) * 2e-10)


def test_manifest_hashes_match_generated_files(adversarial_world):
    world, _, manifest = adversarial_world
    for rel, rec in manifest["files"].items():
        path = world / rel
        assert sha256_file(path) == rec["sha256"]
        assert path.stat().st_size == rec["bytes"]


def test_world_validator_passes_all_invariants(adversarial_world):
    world, _, _ = adversarial_world
    report = validate_world(world, write_report=False)
    assert report["passed"], {k: v for k, v in report["checks"].items() if not v["passed"]}


def test_factor_premia_can_reverse_sign():
    from research.synthetic_market_lab.config import FactorConfig, MacroConfig
    from research.synthetic_market_lab.factors import FACTOR_NAMES, generate_factors
    from research.synthetic_market_lab.macro import generate_macro
    from research.synthetic_market_lab.rng import SeedLedger

    ledger = SeedLedger("1.0.0", 20260907)
    macro = generate_macro(1200, MacroConfig(), ledger.generator("macro"))
    factors = generate_factors(macro, FactorConfig(), ledger.generator("factors"))
    for i, _name in enumerate(FACTOR_NAMES):
        assert (factors.values[:, i] > 0).any()
        assert (factors.values[:, i] < 0).any()
