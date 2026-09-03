#!/usr/bin/env python3
"""Probe iShares IWV historical holdings as independent Russell 3000 evidence.

Research only. Raw third-party holdings files are never persisted. Outputs retain
request/provenance metadata, hashes, schema diagnostics, and aggregate counts only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Sequence

BASE_URL = (
    "https://www.ishares.com/us/products/239714/ishares-russell-3000-etf/"
    "1467271812596.ajax"
)
USER_AGENT = "stocker-pit-russell-research/1.0 (+https://github.com/flabber1835/stocker)"
TICKER_COLUMN_ALIASES = ("Ticker", "Issuer Ticker")
REQUIRED_COLUMNS = ("Name", "Asset Class")


@dataclass
class HoldingsEvidence:
    requested_as_of: str
    request_url: str
    fetch_ok: bool
    http_status: int | None
    final_url: str | None
    response_content_type: str | None
    byte_length: int | None
    sha256: str | None
    csv_detected: bool | None
    source_encoding: str | None
    metadata_as_of: str | None
    metadata_date_matches_request: bool | None
    ticker_column: str | None
    column_count: int | None
    required_columns_present: bool | None
    data_rows: int | None
    equity_rows: int | None
    nonempty_tickers: int | None
    nonempty_cusips: int | None
    error: str | None


def holdings_url(as_of: str) -> str:
    params = {
        "fileType": "csv",
        "fileName": "IWV_holdings",
        "dataType": "fund",
        "asOfDate": as_of,
    }
    return f"{BASE_URL}?{urllib.parse.urlencode(params)}"


def request_bytes(url: str, timeout: int, attempts: int) -> tuple[bytes, int, str | None, str]:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/csv,text/plain,*/*;q=0.5",
                "Accept-Language": "en-US,en;q=0.8",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return (
                    response.read(),
                    int(getattr(response, "status", 200)),
                    response.headers.get("Content-Type"),
                    response.geturl(),
                )
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = exc
            if attempt == attempts:
                break
            time.sleep(min(2 ** (attempt - 1), 4))
    assert last_error is not None
    raise last_error


def decode_text(payload: bytes) -> tuple[str, str]:
    # iShares exports have changed encoding/schema over time. Prefer explicit Unicode
    # encodings before permissive single-byte fallbacks so embedded NULs cannot hide headers.
    for encoding in ("utf-8-sig", "utf-16", "utf-16-le", "utf-16-be", "cp1252", "latin-1"):
        try:
            text = payload.decode(encoding)
        except (UnicodeDecodeError, UnicodeError):
            continue
        # Reject implausible UTF-16 guesses on ordinary byte streams.
        if encoding.startswith("utf-16") and "\x00" in text[:2000]:
            continue
        return text, encoding
    raise ValueError("unable to decode holdings payload")


def _normal(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def _find_header(rows: list[list[str]]) -> tuple[int, list[str], str]:
    ticker_aliases = {_normal(value) for value in TICKER_COLUMN_ALIASES}
    required = {_normal(value) for value in REQUIRED_COLUMNS}
    for idx, row in enumerate(rows):
        normalized = {_normal(cell) for cell in row}
        ticker_matches = ticker_aliases & normalized
        if ticker_matches and required.issubset(normalized):
            header = [cell.strip() for cell in row]
            ticker_column = next(
                cell.strip() for cell in row if _normal(cell) in ticker_matches
            )
            return idx, header, ticker_column
    raise ValueError("IWV holdings CSV header not found")


def _extract_metadata_date(rows: list[list[str]], header_index: int) -> str | None:
    for row in rows[:header_index]:
        joined = " | ".join(cell.strip() for cell in row if cell.strip())
        if "holdings as of" not in joined.casefold():
            continue
        match = re.search(
            r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
            r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|"
            r"Dec(?:ember)?)\s+\d{1,2},\s+\d{4}",
            joined,
            flags=re.IGNORECASE,
        )
        if match:
            return match.group(0)
        iso = re.search(r"\b20\d{2}-\d{2}-\d{2}\b", joined)
        if iso:
            return iso.group(0)
    return None


def _metadata_matches_requested(metadata_as_of: str | None, requested: str) -> bool | None:
    if metadata_as_of is None:
        return None
    for fmt in ("%b %d, %Y", "%B %d, %Y", "%Y-%m-%d"):
        try:
            parsed = datetime.strptime(metadata_as_of, fmt).strftime("%Y%m%d")
            return parsed == requested
        except ValueError:
            continue
    return None


def parse_holdings_csv(payload: bytes) -> dict:
    text, source_encoding = decode_text(payload)
    rows = list(csv.reader(io.StringIO(text)))
    header_index, header, ticker_column = _find_header(rows)
    index = {_normal(name): pos for pos, name in enumerate(header)}
    metadata_as_of = _extract_metadata_date(rows, header_index)

    data_rows = 0
    equity_rows = 0
    ticker_count = 0
    cusip_count = 0
    asset_pos = index[_normal("Asset Class")]
    ticker_pos = index[_normal(ticker_column)]
    cusip_pos = index.get(_normal("CUSIP"))

    for row in rows[header_index + 1 :]:
        if not any(cell.strip() for cell in row):
            if data_rows:
                break
            continue
        if len(row) <= max(asset_pos, ticker_pos):
            continue
        asset_class = row[asset_pos].strip()
        ticker = row[ticker_pos].strip()
        if not asset_class and not ticker:
            if data_rows:
                break
            continue
        data_rows += 1
        if _normal(asset_class) == "equity":
            equity_rows += 1
        if ticker:
            ticker_count += 1
        if cusip_pos is not None and len(row) > cusip_pos and row[cusip_pos].strip():
            cusip_count += 1

    return {
        "source_encoding": source_encoding,
        "metadata_as_of": metadata_as_of,
        "ticker_column": ticker_column,
        "columns": header,
        "column_count": len(header),
        "required_columns_present": True,
        "data_rows": data_rows,
        "equity_rows": equity_rows,
        "nonempty_tickers": ticker_count,
        "nonempty_cusips": cusip_count,
    }


def payload_diagnostics(payload: bytes) -> dict:
    try:
        text, encoding = decode_text(payload)
    except Exception as exc:
        return {
            "source_encoding": None,
            "diagnostic": f"decode_failed:{type(exc).__name__}",
        }
    lowered = text.casefold()
    return {
        "source_encoding": encoding,
        "diagnostic": (
            f"lines={text.count(chr(10)) + 1};"
            f"ticker_token={'ticker' in lowered};"
            f"asset_class_token={'asset class' in lowered};"
            f"holdings_as_of_token={'holdings as of' in lowered}"
        ),
    }


def probe_date(as_of: str, timeout: int, attempts: int) -> HoldingsEvidence:
    url = holdings_url(as_of)
    try:
        payload, status, content_type, final_url = request_bytes(url, timeout, attempts)
        digest = hashlib.sha256(payload).hexdigest()
        try:
            parsed = parse_holdings_csv(payload)
            return HoldingsEvidence(
                requested_as_of=as_of,
                request_url=url,
                fetch_ok=True,
                http_status=status,
                final_url=final_url,
                response_content_type=content_type,
                byte_length=len(payload),
                sha256=digest,
                csv_detected=True,
                source_encoding=parsed["source_encoding"],
                metadata_as_of=parsed["metadata_as_of"],
                metadata_date_matches_request=_metadata_matches_requested(parsed["metadata_as_of"], as_of),
                ticker_column=parsed["ticker_column"],
                column_count=parsed["column_count"],
                required_columns_present=parsed["required_columns_present"],
                data_rows=parsed["data_rows"],
                equity_rows=parsed["equity_rows"],
                nonempty_tickers=parsed["nonempty_tickers"],
                nonempty_cusips=parsed["nonempty_cusips"],
                error=None,
            )
        except Exception as exc:
            diagnostics = payload_diagnostics(payload)
            return HoldingsEvidence(
                requested_as_of=as_of,
                request_url=url,
                fetch_ok=True,
                http_status=status,
                final_url=final_url,
                response_content_type=content_type,
                byte_length=len(payload),
                sha256=digest,
                csv_detected=False,
                source_encoding=diagnostics["source_encoding"],
                metadata_as_of=None,
                metadata_date_matches_request=None,
                ticker_column=None,
                column_count=None,
                required_columns_present=False,
                data_rows=None,
                equity_rows=None,
                nonempty_tickers=None,
                nonempty_cusips=None,
                error=f"parse: {type(exc).__name__}: {exc}; {diagnostics['diagnostic']}",
            )
    except Exception as exc:
        return HoldingsEvidence(
            requested_as_of=as_of,
            request_url=url,
            fetch_ok=False,
            http_status=getattr(exc, "code", None),
            final_url=None,
            response_content_type=None,
            byte_length=None,
            sha256=None,
            csv_detected=None,
            source_encoding=None,
            metadata_as_of=None,
            metadata_date_matches_request=None,
            ticker_column=None,
            column_count=None,
            required_columns_present=None,
            data_rows=None,
            equity_rows=None,
            nonempty_tickers=None,
            nonempty_cusips=None,
            error=f"fetch: {type(exc).__name__}: {exc}",
        )


def write_outputs(output_dir: Path, evidence: list[HoldingsEvidence]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
    manifest = {
        "schema": 2,
        "generated_utc": generated,
        "source_role": "independent corroboration candidate; not Russell membership authority",
        "raw_holdings_persisted": False,
        "evidence": [asdict(row) for row in evidence],
    }
    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    lines = [
        "# IWV historical holdings probe",
        "",
        f"Generated: {generated}",
        "",
        "Research corroboration only. Raw holdings files are not persisted.",
        "",
        "| Requested date | Fetch | CSV | Metadata date | Date match | Equity rows | Tickers | CUSIPs |",
        "|---|---|---|---|---|---:|---:|---:|",
    ]
    for row in evidence:
        date_match = (
            "YES" if row.metadata_date_matches_request is True else
            "NO" if row.metadata_date_matches_request is False else "-"
        )
        lines.append(
            f"| {row.requested_as_of} | {'OK' if row.fetch_ok else 'FAIL'} | "
            f"{'YES' if row.csv_detected else 'NO' if row.csv_detected is False else '-'} | "
            f"{row.metadata_as_of or '-'} | {date_match} | "
            f"{row.equity_rows if row.equity_rows is not None else '-'} | "
            f"{row.nonempty_tickers if row.nonempty_tickers is not None else '-'} | "
            f"{row.nonempty_cusips if row.nonempty_cusips is not None else '-'} |"
        )
    lines.extend(
        [
            "",
            "Interpretation: a historical response is useful only when its embedded metadata date agrees with the requested date. ETF holdings can corroborate an annual Russell universe and identifiers, but are not automatically identical to official index membership.",
            "",
        ]
    )
    (output_dir / "report.md").write_text("\n".join(lines))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", action="append", required=True, help="YYYYMMDD; repeatable")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--attempts", type=int, default=3)
    parser.add_argument("--delay", type=float, default=0.5)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    for value in args.as_of:
        if not re.fullmatch(r"\d{8}", value):
            parser.error(f"invalid --as-of date: {value!r}")
    return args


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    evidence: list[HoldingsEvidence] = []
    for idx, as_of in enumerate(args.as_of):
        if idx:
            time.sleep(args.delay)
        print(f"IWV {as_of}", flush=True)
        row = probe_date(as_of, args.timeout, args.attempts)
        evidence.append(row)
        print(
            f"  fetch={row.fetch_ok} csv={row.csv_detected} metadata_as_of={row.metadata_as_of} "
            f"date_match={row.metadata_date_matches_request} equity_rows={row.equity_rows} error={row.error}",
            flush=True,
        )
    write_outputs(args.output_dir, evidence)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
