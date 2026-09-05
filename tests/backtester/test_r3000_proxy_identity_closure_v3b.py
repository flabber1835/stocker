from __future__ import annotations

import importlib.util
import gzip
import csv
from pathlib import Path

from backtester.r3000_proxy_identity_closure_v3b import close_identity_v3b


def _load_v3a_fixture():
    path = Path(__file__).with_name("test_r3000_proxy_identity_closure_v3a.py")
    spec = importlib.util.spec_from_file_location("v3a_fixture", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module._fixture


def test_optimized_pass_matches_v3a_contract(tmp_path: Path) -> None:
    b2, canonical = _load_v3a_fixture()(tmp_path)
    out = tmp_path / "out"
    summary = close_identity_v3b(b2, canonical, out)
    assert summary["status"] == "PASS"
    assert summary["resolution_counts"] == {"RESOLVED": 2, "AMBIGUOUS": 2, "UNMATCHED": 1, "CONFLICT": 0}
    assert summary["methods_added"]["sec_normalized_name_plus_historical_price"] == 1
    assert summary["methods_added"]["duplicate_rows_demoted"] == 2
    assert summary["duplicate_security_assignments_after"] == 0
    assert summary["future_session_violations"] == 0
    assert summary["canonical_partitions_loaded"] == [2021]
    with gzip.open(out / "identity_ledger_v3b.csv.gz", "rt", encoding="utf-8", newline="") as handle:
        rows = {row["source_row_number"]: row for row in csv.DictReader(handle)}
    assert rows["2"]["normalized_security_id"] == "sid-getty"
    assert rows["3"]["identity_status"] == "AMBIGUOUS"
    assert rows["4"]["identity_status"] == "AMBIGUOUS"


def test_optimized_output_is_deterministic(tmp_path: Path) -> None:
    b2, canonical = _load_v3a_fixture()(tmp_path)
    one = close_identity_v3b(b2, canonical, tmp_path / "one")
    two = close_identity_v3b(b2, canonical, tmp_path / "two")
    assert one["identity_ledger_sha256"] == two["identity_ledger_sha256"]
    assert one["unresolved_worklist_sha256"] == two["unresolved_worklist_sha256"]
