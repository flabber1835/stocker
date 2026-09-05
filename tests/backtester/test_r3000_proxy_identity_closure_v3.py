from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
import zipfile
from pathlib import Path

from backtester.r3000_proxy_identity_closure_v3 import _name_variants, close_identity_v3, sha256_file


def _write_gz(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=fields, lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)


def _row(*, source_row: int, source_type: str, name: str, price: str, status: str, sid: str = "", ticker: str = "", issuer_id: str = "") -> dict[str, str]:
    return {
        "snapshot_date": "2021-06-30",
        "holdings_effective_date": "2021-06-30",
        "source_publication_date": "",
        "available_to_model_date": "",
        "fund": "IWM",
        "source_type": source_type,
        "source_id": "fixture",
        "source_sha256": hashlib.sha256(f"row-{source_row}".encode()).hexdigest(),
        "source_row_number": str(source_row),
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


def _fixture(root: Path) -> tuple[Path, Path, Path]:
    b2 = root / "b2"
    canonical = root / "canonical"
    b2.mkdir()
    canonical.mkdir()

    rows = [
        _row(source_row=1, source_type="blackrock_product_data_v2", name="Getty Images Inc", price="10.00", status="RESOLVED", sid="sid-getty", ticker="GYI", issuer_id="SEC_CIK:100"),
        _row(source_row=2, source_type="sec_n-q", name="Getty Images Inc.(1)", price="10.00", status="UNMATCHED"),
        _row(source_row=3, source_type="sec_n-q", name="Old Corporation(2)", price="20.00", status="UNMATCHED"),
        _row(source_row=4, source_type="blackrock_product_data_v2", name="Current Parent Inc", price="30.00", status="UNMATCHED", ticker="CUR"),
        _row(source_row=5, source_type="blackrock_product_data_v2", name="RPT Realty", price="40.00", status="RESOLVED", sid="sid-ajax", ticker="RPT", issuer_id="SEC_CIK:400"),
        _row(source_row=6, source_type="blackrock_product_data_v2", name="Great Ajax Corp", price="40.00", status="RESOLVED", sid="sid-ajax", ticker="AJX", issuer_id="SEC_CIK:400"),
        _row(source_row=7, source_type="sec_n-q", name="No Authority Corp", price="50.00", status="UNMATCHED"),
    ]
    fields = list(rows[0])
    _write_gz(b2 / "identity_ledger_v2.csv.gz", fields, rows)
    summary = {
        "schema": "stocker.r3000-proxy.identity-closure/2",
        "status": "PASS",
        "source_rows": len(rows),
        "canonical_dataset_hash": "a" * 64,
        "resolution_counts": {"RESOLVED": 3, "AMBIGUOUS": 0, "UNMATCHED": 4, "CONFLICT": 0},
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
    obs = [
        _obs("sid-getty", "GYI", "SEC_CIK:100", "10.00"),
        _obs("sid-old", "OLD", "SEC_CIK:200", "20.00"),
        _obs("sid-current", "CUR", "SEC_CIK:300", "30.00"),
        _obs("sid-ajax", "AJX", "SEC_CIK:400", "40.00"),
        _obs("sid-none", "NONE", "SEC_UNKNOWN:x", "50.00"),
    ]
    _write_gz(canonical / "observations-2021.csv.gz", list(obs[0]), obs)
    (canonical / "manifest.json").write_text(json.dumps({"dataset_hash": "a" * 64}) + "\n", encoding="utf-8")

    sec_zip = root / "submissions.zip"
    with zipfile.ZipFile(sec_zip, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("CIK0000000200.json", json.dumps({"cik": 200, "name": "New Corporation", "formerNames": [{"name": "Old Corporation", "from": "2000-01-01", "to": "2010-01-01"}], "tickers": ["OLD"], "exchanges": ["NYSE"]}))
        archive.writestr("CIK0000000300.json", json.dumps({"cik": 300, "name": "Current Parent Inc", "formerNames": [], "tickers": ["CUR"], "exchanges": ["NYSE"]}))
        archive.writestr("CIK0000000400.json", json.dumps({"cik": 400, "name": "Great Ajax Corp", "formerNames": [], "tickers": ["AJX"], "exchanges": ["NYSE"]}))
    return b2, canonical, sec_zip


def test_sec_footnotes_former_names_and_duplicate_adjudication(tmp_path: Path) -> None:
    b2, canonical, sec_zip = _fixture(tmp_path)
    out = tmp_path / "out"
    summary = close_identity_v3(b2, canonical, sec_zip, out)
    assert summary["status"] == "PASS"
    assert summary["methods_added"]["sec_footnote_normalization_plus_price_certified_blackrock_name"] == 1
    assert summary["methods_added"]["sec_cik_current_former_name_plus_historical_price"] == 2
    assert summary["methods_added"]["duplicate_rows_demoted"] == 1
    assert summary["duplicate_security_assignments_after"] == 0
    assert summary["resolution_counts"] == {"RESOLVED": 5, "AMBIGUOUS": 0, "UNMATCHED": 2, "CONFLICT": 0}
    with gzip.open(out / "identity_ledger_v3.csv.gz", "rt", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    by_row = {row["source_row_number"]: row for row in rows}
    assert by_row["2"]["normalized_security_id"] == "sid-getty"
    assert by_row["3"]["normalized_security_id"] == "sid-old"
    assert by_row["4"]["normalized_security_id"] == "sid-current"
    assert by_row["5"]["identity_status"] == "UNMATCHED"
    assert by_row["6"]["identity_status"] == "RESOLVED"
    assert by_row["7"]["identity_status"] == "UNMATCHED"


def test_name_normalization_is_exact_not_fuzzy() -> None:
    assert _name_variants("Getty Images Inc.(1)") == _name_variants("Getty Images Inc")
    assert _name_variants("Boeing Co. (The)") == _name_variants("Boeing Company")
    assert not (_name_variants("Alpha Holdings Inc") & _name_variants("Alpha Partners Inc"))
