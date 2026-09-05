from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
from pathlib import Path

from backtester.r3000_proxy_identity_closure import (
    close_identity,
    legal_name_key,
    sha256_file,
    ticker_key,
)


def _write_gz(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=fields, lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)


def _stage_row(
    *,
    fund: str,
    effective: str,
    source_type: str,
    source_row: int,
    ticker: str = "",
    name: str = "",
    cusip: str = "",
    isin: str = "",
) -> dict[str, str]:
    return {
        "snapshot_date": effective,
        "holdings_effective_date": effective,
        "source_publication_date": "",
        "available_to_model_date": "",
        "fund": fund,
        "source_type": source_type,
        "source_id": f"source-{effective}",
        "source_sha256": hashlib.sha256(f"{fund}-{effective}".encode()).hexdigest(),
        "source_row_number": str(source_row),
        "reported_ticker": ticker,
        "reported_issuer_name": name,
        "reported_cusip": cusip,
        "reported_isin": isin,
        "reported_asset_class": "Equity",
        "reported_shares": "100",
        "reported_market_value": "1000",
        "reported_weight": "0.1",
        "currency": "USD",
        "normalized_security_id": "",
        "normalized_ticker_on_snapshot_date": "",
        "normalized_issuer_id": "",
        "identity_authority": "",
        "identity_status": "UNRESOLVED",
        "identity_evidence_refs": "",
    }


def _obs(session: str, sid: str, ticker: str, issuer: str) -> dict[str, str]:
    return {
        "session": session,
        "security_id": sid,
        "ticker": ticker,
        "issuer_id": issuer,
        "issuer_source": "SYNTHETIC",
        "security_type": "common_stock",
        "listing_active": "1",
        "tradeable": "1",
        "identity_source": "SYNTHETIC_CANONICAL",
    }


def _fixture(root: Path) -> tuple[Path, Path]:
    stage = root / "stage-a"
    canonical = root / "canonical"
    stage.mkdir()
    canonical.mkdir()

    rows = [
        _stage_row(
            fund="IWB", effective="2007-06-30", source_type="blackrock_product_data_v2",
            source_row=1, ticker="AAA", name="Alpha Corporation", cusip="000000001", isin="US0000000010",
        ),
        _stage_row(
            fund="IWM", effective="2007-06-30", source_type="blackrock_product_data_v2",
            source_row=1, ticker="OLD.X", name="Alpha Corporation", cusip="000000001", isin="US0000000010",
        ),
        _stage_row(
            fund="IWB", effective="2018-06-29", source_type="blackrock_product_data_v2",
            source_row=1, ticker="BETA", name="Beta Holdings Inc", cusip="000000002", isin="US0000000020",
        ),
        _stage_row(
            fund="IWB", effective="2017-06-30", source_type="sec_n-q",
            source_row=1, name="Beta Holdings Incorporated",
        ),
        _stage_row(
            fund="IWM", effective="2017-06-30", source_type="sec_n-q",
            source_row=1, name="Gamma Corporation",
        ),
        _stage_row(
            fund="IWB", effective="2007-06-30", source_type="blackrock_product_data_v2",
            source_row=2, ticker="FUTURE", name="Future Corp", cusip="000000003", isin="US0000000030",
        ),
    ]
    fields = list(rows[0])
    _write_gz(stage / "parsed_holdings.csv.gz", fields, rows)
    (stage / "summary.json").write_text(
        json.dumps({"status": "PASS", "parsed_equity_rows": len(rows)}) + "\n",
        encoding="utf-8",
    )
    (stage / "SHA256SUMS.txt").write_text(
        f"{sha256_file(stage / 'parsed_holdings.csv.gz')}  parsed_holdings.csv.gz\n"
        f"{sha256_file(stage / 'summary.json')}  summary.json\n",
        encoding="utf-8",
    )

    sessions = ["2007-06-29", "2007-07-02", "2017-06-30", "2018-06-29"]
    with (canonical / "session-hashes.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["session", "input_sha256"], lineterminator="\n")
        writer.writeheader()
        for session in sessions:
            writer.writerow({"session": session, "input_sha256": "0" * 64})

    obs_fields = [
        "session", "security_id", "ticker", "issuer_id", "issuer_source",
        "security_type", "listing_active", "tradeable", "identity_source",
    ]
    _write_gz(
        canonical / "observations-2007.csv.gz",
        obs_fields,
        [
            _obs("2007-06-29", "sid-alpha", "AAA", "issuer-alpha"),
            _obs("2007-07-02", "sid-alpha", "AAA", "issuer-alpha"),
            _obs("2007-07-02", "sid-future", "FUTURE", "issuer-future"),
        ],
    )
    _write_gz(
        canonical / "observations-2017.csv.gz",
        obs_fields,
        [_obs("2017-06-30", "sid-beta", "BETA", "issuer-beta")],
    )
    _write_gz(
        canonical / "observations-2018.csv.gz",
        obs_fields,
        [_obs("2018-06-29", "sid-beta", "BETA", "issuer-beta")],
    )
    (canonical / "manifest.json").write_text(
        json.dumps({"dataset_hash": "a" * 64}) + "\n", encoding="utf-8"
    )
    return stage, canonical


def test_identity_closure_historical_only_and_deterministic(tmp_path: Path) -> None:
    stage, canonical = _fixture(tmp_path)
    first = tmp_path / "out-1"
    second = tmp_path / "out-2"
    a = close_identity(stage, canonical, first)
    b = close_identity(stage, canonical, second)

    assert a["status"] == "PASS"
    assert a["source_rows"] == 6
    assert a["fund_snapshots"] == 5
    assert a["resolution_counts"] == {
        "RESOLVED": 4,
        "AMBIGUOUS": 0,
        "UNMATCHED": 2,
        "CONFLICT": 0,
    }
    assert a["methods"]["canonical_historical_ticker"] == 2
    assert a["methods"]["blackrock_cusip_continuity"] == 1
    assert a["methods"]["sec_legal_name_continuity"] == 1
    assert a["future_session_violations"] == 0
    assert a["acceptance_state"] == "OPEN_IDENTITY_WORKLIST"
    assert a["identity_ledger_sha256"] == b["identity_ledger_sha256"]
    assert a["unresolved_worklist_sha256"] == b["unresolved_worklist_sha256"]


def test_future_ticker_is_not_used(tmp_path: Path) -> None:
    stage, canonical = _fixture(tmp_path)
    out = tmp_path / "out"
    close_identity(stage, canonical, out)
    with gzip.open(out / "identity_ledger.csv.gz", "rt", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    future = next(row for row in rows if row["reported_ticker"] == "FUTURE")
    assert future["identity_target_session"] == "2007-06-29"
    assert future["identity_status"] == "UNMATCHED"
    assert future["normalized_security_id"] == ""


def test_normalization_is_deterministic_not_fuzzy() -> None:
    assert ticker_key("BRK.B") == ticker_key("BRK-B") == "BRKB"
    assert legal_name_key("Beta Holdings Incorporated") == legal_name_key("BETA HLDGS INC")
    assert legal_name_key("Beta Holdings Incorporated") != legal_name_key("Beta Holdings Partners Inc")
