from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
from pathlib import Path

from backtester.r3000_proxy_identity_closure_v3a import close_identity_v3a, sha256_file


def _write_gz(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=fields, lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)


def _row(*, n: int, fund: str, source_type: str, name: str, price: str, status: str, sid: str = "", ticker: str = "", issuer_id: str = "") -> dict[str, str]:
    return {
        "snapshot_date": "2021-06-30",
        "holdings_effective_date": "2021-06-30",
        "source_publication_date": "",
        "available_to_model_date": "",
        "fund": fund,
        "source_type": source_type,
        "source_id": "fixture",
        "source_sha256": hashlib.sha256(f"row-{n}".encode()).hexdigest(),
        "source_row_number": str(n),
        "reported_ticker": ticker,
        "reported_issuer_name": name,
        "reported_cusip": "",
        "reported_isin": "",
        "reported_asset_class": "Equity",
        "reported_shares": "100",
        "reported_market_value": str(float(price) * 100),
        "reported_weight": "",
        "currency": "USD",
        "normalized_security_id": sid,
        "normalized_ticker_on_snapshot_date": ticker if sid else "",
        "normalized_issuer_id": issuer_id if sid else "",
        "identity_authority": "B2" if sid else "",
        "identity_status": status,
        "identity_evidence_refs": "{}",
        "identity_target_session": "2021-06-30",
        "reported_sedol": "",
        "reported_exchange": "",
        "reported_country_of_risk": "",
        "reported_unit_price": price,
        "identity_method": "B2" if sid else "",
        "identity_candidate_count": "1" if sid else "0",
        "identity_reason": "" if sid else "OPEN",
        "identity_price_candidate_count": "1",
        "identity_price_match_cents": price,
        "identity_path_support": "",
        "identity_canonical_security_type": "common_stock" if sid else "",
        "identity_canonical_issuer_source": "TEST" if sid else "",
        "identity_canonical_identity_source": "TEST" if sid else "",
        "identity_canonical_listing_active": "1" if sid else "",
        "identity_canonical_tradeable": "1" if sid else "",
    }


def _obs(sid: str, ticker: str, issuer_id: str, price: str) -> dict[str, str]:
    return {
        "session": "2021-06-30",
        "security_id": sid,
        "ticker": ticker,
        "issuer_id": issuer_id,
        "issuer_source": "TEST",
        "security_type": "common_stock",
        "listing_active": "1",
        "tradeable": "1",
        "identity_source": "TEST",
        "raw_close": price,
        "exchange": "NYSE",
    }


def _fixture(root: Path) -> tuple[Path, Path]:
    b2 = root / "b2"
    canonical = root / "canonical"
    b2.mkdir()
    canonical.mkdir()
    rows = [
        _row(n=1, fund="IWB", source_type="blackrock_product_data_v2", name="Getty Images Inc", price="10.00", status="RESOLVED", sid="sid-getty", ticker="GYI", issuer_id="SEC_CIK:100"),
        _row(n=2, fund="IWM", source_type="sec_n-q", name="Getty Images Inc.(1)", price="10.00", status="UNMATCHED"),
        _row(n=3, fund="IWM", source_type="blackrock_product_data_v2", name="RPT Realty", price="12.98", status="RESOLVED", sid="sid-dupe", ticker="RPT", issuer_id="SEC_CIK:400"),
        _row(n=4, fund="IWM", source_type="blackrock_product_data_v2", name="Great Ajax Corp", price="12.98", status="RESOLVED", sid="sid-dupe", ticker="AJX", issuer_id="SEC_CIK:400"),
        _row(n=5, fund="IWM", source_type="sec_n-q", name="No Authority Corp", price="50.00", status="UNMATCHED"),
    ]
    fields = list(rows[0])
    _write_gz(b2 / "identity_ledger_v2.csv.gz", fields, rows)
    summary = {
        "schema": "stocker.r3000-proxy.identity-closure/2",
        "status": "PASS",
        "source_rows": len(rows),
        "canonical_dataset_hash": "a" * 64,
        "resolution_counts": {"RESOLVED": 3, "AMBIGUOUS": 0, "UNMATCHED": 2, "CONFLICT": 0},
    }
    (b2 / "identity_summary_v2.json").write_text(json.dumps(summary) + "\n", encoding="utf-8")
    (b2 / "SHA256SUMS.txt").write_text(
        f"{sha256_file(b2 / 'identity_ledger_v2.csv.gz')}  identity_ledger_v2.csv.gz\n"
        f"{sha256_file(b2 / 'identity_summary_v2.json')}  identity_summary_v2.json\n",
        encoding="utf-8",
    )

    with (canonical / "session-hashes.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["session", "input_sha256"], lineterminator="\n")
        writer.writeheader()
        writer.writerow({"session": "2021-06-30", "input_sha256": "0" * 64})
    observations = [
        _obs("sid-getty", "GYI", "SEC_CIK:100", "10.00"),
        _obs("sid-dupe", "AJX", "SEC_CIK:400", "12.98"),
        _obs("sid-none", "NONE", "SEC_CIK:500", "50.00"),
    ]
    _write_gz(canonical / "observations-2021.csv.gz", list(observations[0]), observations)
    (canonical / "manifest.json").write_text(json.dumps({"dataset_hash": "a" * 64}) + "\n", encoding="utf-8")
    return b2, canonical


def test_offline_footnote_closure_and_duplicate_fail_closed(tmp_path: Path) -> None:
    b2, canonical = _fixture(tmp_path)
    out = tmp_path / "out"
    summary = close_identity_v3a(b2, canonical, out)
    assert summary["status"] == "PASS"
    assert summary["resolution_counts"] == {"RESOLVED": 2, "AMBIGUOUS": 2, "UNMATCHED": 1, "CONFLICT": 0}
    assert summary["methods_added"]["sec_normalized_name_plus_historical_price"] == 1
    assert summary["methods_added"]["duplicate_rows_demoted"] == 2
    assert summary["duplicate_security_assignments_before"] == 1
    assert summary["duplicate_security_assignments_after"] == 0
    assert summary["future_session_violations"] == 0

    with gzip.open(out / "identity_ledger_v3a.csv.gz", "rt", encoding="utf-8", newline="") as handle:
        rows = {row["source_row_number"]: row for row in csv.DictReader(handle)}
    assert rows["2"]["normalized_security_id"] == "sid-getty"
    assert rows["3"]["identity_status"] == "AMBIGUOUS"
    assert rows["4"]["identity_status"] == "AMBIGUOUS"
    assert rows["5"]["identity_status"] == "UNMATCHED"


def test_offline_output_is_deterministic(tmp_path: Path) -> None:
    b2, canonical = _fixture(tmp_path)
    one = tmp_path / "one"
    two = tmp_path / "two"
    a = close_identity_v3a(b2, canonical, one)
    b = close_identity_v3a(b2, canonical, two)
    assert a["identity_ledger_sha256"] == b["identity_ledger_sha256"]
    assert a["unresolved_worklist_sha256"] == b["unresolved_worklist_sha256"]
