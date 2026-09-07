from __future__ import annotations

import csv
import gzip
import inspect
import json

import numpy as np

from research.synthetic_market_lab.config import MacroConfig
from research.synthetic_market_lab.macro import generate_macro
from research.synthetic_market_lab.pit import SyntheticPITWorld
from research.synthetic_market_lab.pricing import generate_bars
from research.synthetic_market_lab.rng import SeedLedger


def rows(path):
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def test_no_future_macro_state_leakage_by_prefix_invariance():
    ledger = SeedLedger("1.0.0", 7103)
    short = generate_macro(120, MacroConfig(), ledger.generator("macro"))
    long = generate_macro(240, MacroConfig(), ledger.generator("macro"))
    np.testing.assert_array_equal(short.regime_index, long.regime_index[:120])
    np.testing.assert_allclose(short.state, long.state[:120], rtol=0, atol=0)
    np.testing.assert_allclose(short.shocks, long.shocks[:120], rtol=0, atol=0)


def test_price_step_accepts_current_state_vectors_not_future_paths():
    params = inspect.signature(generate_bars).parameters
    assert "macro_state" in params and "factor_values" in params
    assert "macro_path" not in params and "factor_path" not in params
    assert "future" not in " ".join(params).lower()


def test_causal_dependency_graph_has_no_positive_lags(adversarial_world):
    world, _, _ = adversarial_world
    causal = json.loads((world / "ground_truth/causal_dependencies.json").read_text())
    assert all(rule.get("max_future_lag", 0) <= 0 for rule in causal["rules"].values())
    assert causal["rules"]["adapter"]["ground_truth_access"] is False


def test_future_fundamental_filings_and_revisions_do_not_leak_backward(adversarial_world):
    world, _, _ = adversarial_world
    disclosures = rows(world / "public/disclosures.csv.gz")
    by_period = {}
    for row in disclosures:
        by_period.setdefault((row["company_id"], row["period_end"]), []).append(row)
    restated = next(v for v in by_period.values() if len(v) >= 2)
    restated.sort(key=lambda r: (r["filed_at"], int(r["version"])))
    first, second = restated[0], restated[1]
    pit = SyntheticPITWorld(world / "public")

    before = [r for r in pit.fundamentals_as_of(first["period_end"]) if r["company_id"] == first["company_id"] and r["period_end"] == first["period_end"]]
    assert before == []

    visible_first = [r for r in pit.fundamentals_as_of(first["filed_at"]) if r["company_id"] == first["company_id"] and r["period_end"] == first["period_end"]]
    assert len(visible_first) == 1 and visible_first[0]["version"] == first["version"]

    visible_second = [r for r in pit.fundamentals_as_of(second["filed_at"]) if r["company_id"] == second["company_id"] and r["period_end"] == second["period_end"]]
    assert len(visible_second) == 1 and visible_second[0]["version"] == second["version"]


def test_filing_dates_are_after_period_end(adversarial_world):
    world, _, _ = adversarial_world
    disclosures = rows(world / "public/disclosures.csv.gz")
    assert disclosures
    assert all(row["filed_at"] > row["period_end"] for row in disclosures)


def test_actions_are_announced_no_later_than_effective_date(adversarial_world):
    world, _, _ = adversarial_world
    actions = rows(world / "public/actions.csv.gz")
    assert actions
    assert all(row["announced_at"] <= row["effective_date"] for row in actions)


def test_macro_allows_overlapping_shocks():
    ledger = SeedLedger("1.0.0", 45678)
    macro = generate_macro(500, MacroConfig(shock_daily_probability=0.05), ledger.generator("macro"))
    simultaneous = np.sum(np.abs(macro.shocks) > 1e-12, axis=1)
    assert simultaneous.max() >= 2


def test_reporting_calendars_are_heterogeneous_and_include_annual_reports(adversarial_world):
    world, _, _ = adversarial_world
    disclosures = rows(world / "public/disclosures.csv.gz")
    assert {row["report_type"] for row in disclosures} >= {"quarterly", "annual"}
    # Company-specific fiscal offsets yield many distinct period-end dates, not one synchronized calendar.
    assert len({row["period_end"] for row in disclosures}) > 12
