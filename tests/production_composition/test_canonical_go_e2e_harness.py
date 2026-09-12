from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "tools" / "production_go_e2e_harness.py"
SPEC = importlib.util.spec_from_file_location("production_go_e2e_harness", PATH)
assert SPEC is not None and SPEC.loader is not None
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)


def test_canonical_entrypoint_is_real_production_go():
    assert harness.ENTRYPOINT == ("bash", "scripts/sentinel-go-validate.sh")
    assert harness.REQUIRED_PHASES[-3:] == (
        "CERTIFICATION + FINANCIAL READINESS",
        "PROMOTE EXACT CERTIFIED RUNTIME",
        "POST-VALIDATION HANDOFF",
    )


def test_fixture_pages_satisfy_consumed_sharadar_protocol():
    required = {
        "SEP": {"ticker", "date", "open", "close", "closeunadj", "volume", "lastupdated"},
        "SFP": {"ticker", "date", "open", "close", "closeadj", "closeunadj"},
        "ACTIONS": {"date", "action", "ticker", "name", "value", "contraticker", "contraname"},
        "TICKERS": {"table", "permaticker", "ticker", "category", "relatedtickers",
                    "firstpricedate", "lastpricedate", "sector", "isdelisted", "exchange"},
    }
    for table in required:
        page = harness._payload(table, {})
        names = [item["name"] for item in page["datatable"]["columns"]]
        assert required[table].issubset(names)
        assert page["meta"] == {"next_cursor_id": None}
        assert all(len(row) == len(names) for row in page["datatable"]["data"])


def test_fixture_supplies_seed_reference_tickers():
    page = harness._payload("SFP", {"ticker": ["SPY,BIL"]})
    assert {row[0] for row in page["datatable"]["data"]} == {"SPY", "BIL"}


def test_fixture_is_large_enough_for_readiness_history():
    page = harness._payload("SEP", {})
    by_spy = [row for row in page["datatable"]["data"] if row[0] == "SPY"]
    assert len(by_spy) >= 252
    assert len({row[1] for row in by_spy}) >= 252


def test_phase_parser_is_stage_sensitive():
    output = "\n=== HOST COMPATIBILITY ===\n[GO] ok\n=== RUNTIME SELECTION PREFLIGHT ===\n"
    assert harness._phase_names(output) == [
        "HOST COMPATIBILITY", "RUNTIME SELECTION PREFLIGHT"
    ]