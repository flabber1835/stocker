from __future__ import annotations

import csv
import gzip
import hashlib
import io
import json
from pathlib import Path

from backtester.r3000_proxy_identity_closure_v2 import close_identity_v2, sha256_file


def _write_gz(path: Path, fields: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as gz:
            with io.TextIOWrapper(gz, encoding="utf-8", newline="") as text:
                writer = csv.DictWriter(text, fieldnames=fields, lineterminator="\n")
                writer.writeheader()
                writer.writerows(rows)


def _row(*, source_id: str, effective: str, source_type: str, source_row: int, ticker: str = "", name: str = "", cusip: str = "", isin: str = "", shares: str = "100", market: str = "1000") -> dict[str, str]:
    return {
        "snapshot_date": effective,
        "holdings_effective_date": effective,
        "source_publication_date": "",
        "available_to_model_date": "",
        "fund": "IWB",
        "source_type": source_type,
        "source_id": source_id,
        "source_sha256": hashlib.sha256(source_id.encode()).hexdigest(),
        "source_row_number": str(source_row),
        "reported_ticker": ticker,
        "reported_issuer_name": name,
        "reported_cusip": cusip,
        "reported_isin": isin,
        "reported_asset_class": "Equity",
        "reported_shares": shares,
        "reported_market_value": market,
        "reported_weight": "",
        "currency": "USD",
        "normalized_security_id": "",
        "normalized_ticker_on_snapshot_date": "",
        "normalized_issuer_id": "",
        "identity_authority": "",
        "identity_status": "UNRESOLVED",
        "identity_evidence_refs": "",
    }


def _blackrock_json(path: Path, rows: list[dict[str, str]]) -> None:
    keys = ["sedol", "exchange", "countryOfRisk", "unitPrice"]
    values = {key: [row[key] for row in rows] for key in keys}
    payload = {
        "componentsByNameMap": {
            "holdings": {
                "containersByNameMap": {
                    "all": {
                        "dataPointsByNameMap": {
                            key: {"formattedValue": value} for key, value in values.items()
                        }
                    }
                }
            }
        }
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def _obs(session: str, sid: str, ticker: str, price: str) -> dict[str, str]:
    return {
        "session": session,
        "security_id": sid,
        "ticker": ticker,
        "issuer_id": f"issuer-{sid}",
        "issuer_source": "TEST",
        "security_type": "common_stock",
        "listing_active": "1",
        "tradeable": "1",
        "identity_source": "TEST",
        "raw_close": price,
        "exchange": "NYSE",
    }


def _fixture(root: Path) -> tuple[Path, Path]:
    stage = root / "stage-a"
    raw = stage / "raw"
    canonical = root / "canonical"
    raw.mkdir(parents=True)
    canonical.mkdir()

    parsed = []
    for year, price in ((2007, "10.00"), (2008, "11.00"), (2009, "12.00")):
        source = f"IWB_{year}0630_product_data_v2.json"
        _blackrock_json(raw / source, [{"sedol": "SEDOLD", "exchange": "NYSE", "countryOfRisk": "United States", "unitPrice": price}])
        parsed.append(_row(source_id=source, effective=f"{year}-06-30", source_type="blackrock_product_data_v2", source_row=1, ticker="NEW", name="Old Corporation", cusip="111111111", isin="US1111111111"))

    direct_source = "IWB_20110630_product_data_v2.json"
    _blackrock_json(raw / direct_source, [{"sedol": "SEDGOOD", "exchange": "NYSE", "countryOfRisk": "United States", "unitPrice": "30.00"}])
    parsed.append(_row(source_id=direct_source, effective="2011-06-30", source_type="blackrock_product_data_v2", source_row=1, ticker="GOOD", name="Good Corporation", cusip="222222222", isin="US2222222222", shares="100", market="3000"))
    parsed.append(_row(source_id="sec-test", effective="2010-06-30", source_type="sec_n-q", source_row=1, name="Good Corporation a", shares="100", market="3000"))

    fields = list(parsed[0])
    _write_gz(stage / "parsed_holdings.csv.gz", fields, parsed)
    (stage / "summary.json").write_text(json.dumps({"status": "PASS", "parsed_equity_rows": len(parsed)}) + "\n", encoding="utf-8")
    members = [stage / "parsed_holdings.csv.gz", stage / "summary.json", *sorted(raw.iterdir())]
    (stage / "SHA256SUMS.txt").write_text("".join(f"{sha256_file(path)}  {path.relative_to(stage).as_posix()}\n" for path in members), encoding="utf-8")

    sessions = ["2007-06-29", "2008-06-30", "2009-06-30", "2010-06-30", "2011-06-30"]
    with (canonical / "session-hashes.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["session", "input_sha256"], lineterminator="\n")
        writer.writeheader()
        for session in sessions:
            writer.writerow({"session": session, "input_sha256": "0" * 64})

    obs_fields = list(_obs("2007-06-29", "sid-old", "OLD", "10.00"))
    yearly = {
        2007: [_obs("2007-06-29", "sid-old", "OLD", "10.00"), _obs("2007-06-29", "sid-new", "NEW", "20.00")],
        2008: [_obs("2008-06-30", "sid-old", "OLD", "11.00"), _obs("2008-06-30", "sid-new", "NEW", "21.00")],
        2009: [_obs("2009-06-30", "sid-old", "OLD", "12.00"), _obs("2009-06-30", "sid-new", "NEW", "22.00")],
        2010: [_obs("2010-06-30", "sid-good", "GOOD", "30.00")],
        2011: [_obs("2011-06-30", "sid-good", "GOOD", "30.00")],
    }
    for year, observations in yearly.items():
        _write_gz(canonical / f"observations-{year}.csv.gz", obs_fields, observations)
    (canonical / "manifest.json").write_text(json.dumps({"dataset_hash": "a" * 64}) + "\n", encoding="utf-8")
    return stage, canonical


def test_price_path_rejects_currentized_ticker_and_recovers_old_security(tmp_path: Path) -> None:
    stage, canonical = _fixture(tmp_path)
    out = tmp_path / "out"
    summary = close_identity_v2(stage, canonical, out)
    assert summary["status"] == "PASS"
    assert summary["resolution_counts"]["RESOLVED"] == 5
    assert summary["reported_ticker_price_mismatches"] == 3
    assert summary["methods"]["identifier_plus_historical_price_path"] == 3
    assert summary["methods"]["historical_ticker_plus_unit_price"] == 1
    assert summary["methods"]["sec_normalized_name_plus_implied_price"] == 1
    with gzip.open(out / "identity_ledger_v2.csv.gz", "rt", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    old = [row for row in rows if row["reported_ticker"] == "NEW"]
    assert {row["normalized_security_id"] for row in old} == {"sid-old"}
    assert {row["normalized_ticker_on_snapshot_date"] for row in old} == {"OLD"}
    assert all(row["identity_target_session"] <= row["holdings_effective_date"] for row in rows)


def test_sec_footnote_name_requires_price_agreement(tmp_path: Path) -> None:
    stage, canonical = _fixture(tmp_path)
    out = tmp_path / "out"
    close_identity_v2(stage, canonical, out)
    with gzip.open(out / "identity_ledger_v2.csv.gz", "rt", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    sec = next(row for row in rows if row["source_type"] == "sec_n-q")
    assert sec["reported_unit_price"].startswith("30")
    assert sec["normalized_security_id"] == "sid-good"
    assert sec["identity_method"] == "SEC_NORMALIZED_NAME_PLUS_IMPLIED_PRICE"
