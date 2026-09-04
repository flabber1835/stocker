#!/usr/bin/env python3
"""Build a best-effort PIT Russell 1000 proxy from historical IWB holdings.

IWB is the iShares Russell 1000 ETF. This builder deliberately treats its
historical equity holdings as a *proxy* for Russell 1000 membership; it never
claims they are the official index constituent files.

Causality contract:
- request month-end historical snapshots from BlackRock/iShares product-data v2;
- accept only a payload whose as-of date is <= the requested date;
- replay code may use a snapshot only on sessions strictly AFTER its as-of date;
- map symbols to historical Sharadar SEP ticker episodes using exact or bounded
  punctuation/share-class normalization only; no name fuzzy matching.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

ISHARES_API = "https://www.ishares.com/varnish-api/blk-one01-product-data/product-data/api/v2/get-product-data"
BLACKROCK_API = "https://www.blackrock.com/varnish-api/blk-one01-product-data/product-data/api/v2/get-product-data"
API_URLS = (ISHARES_API, BLACKROCK_API)
PRODUCT_ID = "239707"
USER_AGENT = "Mozilla/5.0 (compatible; Stocker-R1000-PIT-research/1.0)"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def normalize_sid(value) -> str | None:
    if value is None or pd.isna(value):
        return None
    try:
        return str(int(float(value)))
    except (TypeError, ValueError, OverflowError):
        text = str(value).strip()
        return text or None


def compact_symbol(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value).upper().replace("*", ""))


@dataclass(frozen=True)
class Listing:
    ticker: str
    first: str
    last: str
    sid: str


def load_listings(tickers_zip: Path) -> tuple[dict[str, list[Listing]], dict[str, list[Listing]]]:
    with zipfile.ZipFile(tickers_zip) as zf:
        members = [name for name in zf.namelist() if name.lower().endswith(".csv")]
        if len(members) != 1:
            raise RuntimeError(f"{tickers_zip}: expected one CSV, got {members}")
        with zf.open(members[0]) as f:
            frame = pd.read_csv(
                f,
                usecols=["table", "permaticker", "ticker", "firstpricedate", "lastpricedate"],
                low_memory=False,
            )
    frame = frame[frame["table"].astype(str).eq("SEP") & frame["ticker"].notna()].copy()
    direct: dict[str, list[Listing]] = {}
    compact: dict[str, list[Listing]] = {}
    for row in frame.itertuples(index=False):
        ticker = str(row.ticker).strip().upper()
        sid = normalize_sid(row.permaticker)
        if not ticker or sid is None:
            continue
        first = "0001-01-01" if pd.isna(row.firstpricedate) else str(row.firstpricedate)[:10]
        last = "9999-12-31" if pd.isna(row.lastpricedate) else str(row.lastpricedate)[:10]
        listing = Listing(ticker=ticker, first=first, last=last, sid=sid)
        direct.setdefault(ticker, []).append(listing)
        compact.setdefault(compact_symbol(ticker), []).append(listing)
    return direct, compact


def active_unique(candidates: list[Listing], as_of: str) -> Listing | None:
    active = {row for row in candidates if row.first <= as_of <= row.last}
    if len(active) == 1:
        return next(iter(active))
    return None


def map_symbol(raw_symbol: str, as_of: str, direct, compact) -> tuple[str | None, str]:
    raw = str(raw_symbol).strip().upper()
    cleaned = raw.rstrip("*").strip()
    row = active_unique(direct.get(cleaned, []), as_of)
    if row is not None:
        return row.ticker, "exact" if cleaned == raw else "trailing_star"

    key = compact_symbol(cleaned)
    row = active_unique(compact.get(key, []), as_of)
    if row is not None:
        return row.ticker, "class_punctuation"
    return None, "unmapped"


def values(data_points: dict, name: str) -> list:
    point = data_points.get(name) if isinstance(data_points, dict) else None
    if not isinstance(point, dict):
        return []
    value = point.get("value")
    if isinstance(value, list):
        return value
    value = point.get("formattedValue")
    return value if isinstance(value, list) else []


def fetch_snapshot(candidate: pd.Timestamp, timeout: int = 45) -> dict:
    d = candidate.strftime("%Y%m%d")
    params = {
        "appType": "PRODUCT_PAGE",
        "appSubType": "ISHARES",
        "targetSite": "us-ishares",
        "locale": "en_US",
        "portfolioId": PRODUCT_ID,
        "userType": "individual",
        "component": "holdings",
        "asOfDate": d,
    }
    errors = []
    for base in API_URLS:
        url = base + "?" + urllib.parse.urlencode(params)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as response:
                raw = response.read()
            payload = json.loads(raw.decode("utf-8-sig"))
            dp = payload["componentsByNameMap"]["holdings"]["containersByNameMap"]["all"]["dataPointsByNameMap"]
            tickers = values(dp, "ticker")
            asset_classes = values(dp, "assetClass")
            as_of_value = ((dp.get("asOfDate") or {}).get("value")
                           or (dp.get("asOfDate") or {}).get("formattedValue")
                           or d)
            as_of_text = str(as_of_value).strip()
            if re.fullmatch(r"\d{8}", as_of_text):
                as_of = pd.to_datetime(as_of_text, format="%Y%m%d").normalize()
            else:
                as_of = pd.Timestamp(as_of_text).normalize()
            equities = []
            for i, ticker in enumerate(tickers):
                symbol = str(ticker).strip()
                if not symbol or symbol == "-":
                    continue
                asset = str(asset_classes[i]).strip() if i < len(asset_classes) else "Equity"
                if asset and asset.lower() != "equity":
                    continue
                equities.append(symbol)
            if len(equities) < 850:
                raise ValueError(f"implausibly small IWB equity holdings: {len(equities)}")
            return {
                "source_url": url,
                "source_host": urllib.parse.urlparse(base).netloc,
                "source_sha256": sha256_bytes(raw),
                "source_bytes": len(raw),
                "requested_candidate": candidate.strftime("%Y-%m-%d"),
                "as_of_date": as_of.strftime("%Y-%m-%d"),
                "raw_symbols": equities,
            }
        except Exception as exc:  # network/source fallback is intentionally explicit in manifest
            errors.append(f"{base}: {type(exc).__name__}: {exc}")
    raise RuntimeError("; ".join(errors))


def resolve_snapshot(requested: pd.Timestamp, max_lookback_days: int) -> dict:
    errors = []
    for delta in range(max_lookback_days + 1):
        candidate = requested - pd.Timedelta(days=delta)
        try:
            result = fetch_snapshot(candidate)
        except Exception as exc:
            errors.append(f"{candidate.date()}: {exc}")
            continue
        as_of = pd.Timestamp(result["as_of_date"])
        if as_of > requested:
            errors.append(f"{candidate.date()}: future as-of {as_of.date()}")
            continue
        result["requested_date"] = requested.strftime("%Y-%m-%d")
        result["lookback_days"] = delta
        return result
    raise RuntimeError(
        f"no IWB snapshot within {max_lookback_days} days before {requested.date()}: "
        + " | ".join(errors[-4:])
    )


def monthly_request_dates(start: str, end: str) -> list[pd.Timestamp]:
    s = pd.Timestamp(start).normalize()
    e = pd.Timestamp(end).normalize()
    dates = [pd.Timestamp(x).normalize() for x in pd.date_range(s, e, freq="ME")]
    if not dates or dates[0] > s:
        dates.insert(0, s)
    if dates[-1] != e:
        dates.append(e)
    return sorted(set(dates))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--start", default="2006-07-31")
    ap.add_argument("--end", default="2026-07-31")
    ap.add_argument("--max-lookback-days", type=int, default=7)
    ap.add_argument("--sleep-seconds", type=float, default=0.03)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)

    direct, compact = load_listings(args.tickers)
    snapshot_rows = []
    manifest_rows = []
    seen_asof = set()
    requests = monthly_request_dates(args.start, args.end)
    for number, requested in enumerate(requests, 1):
        snap = resolve_snapshot(requested, args.max_lookback_days)
        as_of = snap["as_of_date"]
        if as_of in seen_asof:
            continue
        seen_asof.add(as_of)
        raw_symbols = list(dict.fromkeys(snap.pop("raw_symbols")))
        mapped = []
        mapping_counts: dict[str, int] = {}
        unmapped = []
        for raw in raw_symbols:
            ticker, method = map_symbol(raw, as_of, direct, compact)
            mapping_counts[method] = mapping_counts.get(method, 0) + 1
            if ticker is None:
                unmapped.append(raw)
            else:
                mapped.append((raw, ticker, method))
        mapped_tickers = sorted({ticker for _raw, ticker, _method in mapped})
        coverage = len(mapped_tickers) / len(raw_symbols) if raw_symbols else 0.0
        if coverage < 0.94:
            raise RuntimeError(
                f"IWB mapping coverage too low on {as_of}: {len(mapped_tickers)}/{len(raw_symbols)}={coverage:.2%}; "
                f"unmapped sample={unmapped[:20]}")
        for raw, ticker, method in mapped:
            snapshot_rows.append({
                "as_of_date": as_of,
                "ticker": ticker,
                "raw_iwb_ticker": raw,
                "mapping_method": method,
            })
        manifest_rows.append({
            **snap,
            "raw_equity_count": len(raw_symbols),
            "mapped_unique_tickers": len(mapped_tickers),
            "mapping_coverage": coverage,
            "mapping_methods": mapping_counts,
            "unmapped_count": len(unmapped),
            "unmapped_sample": unmapped[:30],
        })
        if number % 12 == 0 or number == len(requests):
            print(
                f"[R1000] {as_of} snapshot={len(raw_symbols)} mapped={len(mapped_tickers)} "
                f"coverage={coverage:.2%} requests={number}/{len(requests)}",
                flush=True,
            )
        time.sleep(max(args.sleep_seconds, 0.0))

    snapshots = pd.DataFrame(snapshot_rows).drop_duplicates(["as_of_date", "ticker"], keep="first")
    snapshots.sort_values(["as_of_date", "ticker"], inplace=True)
    out_csv = args.output / "r1000_iwb_snapshots.csv.gz"
    snapshots.to_csv(out_csv, index=False, compression={"method": "gzip", "compresslevel": 6, "mtime": 0})

    summary = {
        "schema": "backtester.r1000-iwb-proxy/1",
        "status": "PASS",
        "evidence_label": "BEST_EFFORT_PIT_R1000_IWB_PROXY",
        "source": "BlackRock/iShares product-data v2 historical IWB holdings",
        "product_id": PRODUCT_ID,
        "causal_rule": "snapshot as-of t is eligible only for decision sessions strictly after t",
        "mapping_rule": "exact historical SEP ticker episode, trailing-star cleanup, or unique punctuation/share-class normalization; no fuzzy names",
        "requested_start": args.start,
        "requested_end": args.end,
        "snapshot_count": len(manifest_rows),
        "first_as_of": min(row["as_of_date"] for row in manifest_rows),
        "last_as_of": max(row["as_of_date"] for row in manifest_rows),
        "minimum_mapping_coverage": min(row["mapping_coverage"] for row in manifest_rows),
        "median_mapping_coverage": float(pd.Series([row["mapping_coverage"] for row in manifest_rows]).median()),
        "snapshots": manifest_rows,
        "output_sha256": sha256_file(out_csv),
    }
    summary_path = args.output / "r1000_iwb_membership_manifest.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"[PASS] R1000 IWB proxy snapshots={len(manifest_rows)} first={summary['first_as_of']} "
        f"last={summary['last_as_of']} min_mapping={summary['minimum_mapping_coverage']:.2%}",
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
