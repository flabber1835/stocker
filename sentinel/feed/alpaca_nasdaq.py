"""Conservative current common-stock selection from free Nasdaq directories.

This is a versioned operational policy, not a historical security-type claim.
It consumes only public directory rows and Alpaca's current asset inventory.
"""
from __future__ import annotations

import csv
import io
import re
from collections import Counter
from collections.abc import Iterable, Mapping

DIRECTORY_URLS = (
    "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt",
    "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt",
)
CATEGORY = "Nasdaq Non-ETF Common Stock Candidate"
EXCLUDED_CATEGORY = "Alpaca Action Unresolved"
POLICY = "sentinel.alpaca-nasdaq-common-stock/4"
_NONCOMMON = re.compile(
    r"\b(?:warrants?|preferred|preference|rights?|notes?|debentures?|ETNs?|"
    r"(?:corporate|equity) units?)\b", re.IGNORECASE)
_BUNDLED_UNITS = re.compile(
    r"(?:\s+-\s+units?\b|\bunits?\s*,?\s*(?:each\s+)?"
    r"(?:consisting|comprised|composed)\b)", re.IGNORECASE)
_DEPOSITARY_SHARES = re.compile(r"\bdepositary shares\b", re.IGNORECASE)
_EQUITY_ADS = re.compile(r"\b(?:american|global) depositary shares\b", re.IGNORECASE)
# The public other-listed directory uses '$' for preferred-series symbols.
# Parse those rows for file integrity; the admission rule excludes them.
_SYMBOL = re.compile(r"^[A-Z0-9][A-Z0-9.$-]{0,31}$")


class DirectoryRefused(ValueError):
    pass


def parse_directory(text: str, *, name: str) -> dict[str, dict[str, str]]:
    """Parse one entire Nasdaq file; never accept a truncated or mixed schema."""
    headers = {
        "nasdaqlisted": ("Symbol", "Security Name", "Test Issue", "ETF"),
        "otherlisted": ("ACT Symbol", "Security Name", "Test Issue", "ETF"),
    }
    if name not in headers or not text or len(text.encode("utf-8")) > 4 * 1024 * 1024:
        raise DirectoryRefused("unsupported or oversized Nasdaq directory")
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")), delimiter="|")
    expected = headers[name]
    if reader.fieldnames is None or not set(expected).issubset(reader.fieldnames):
        raise DirectoryRefused("Nasdaq directory header changed")
    key = expected[0]
    rows: dict[str, dict[str, str]] = {}
    footer = False
    for row in reader:
        symbol = str(row.get(key) or "").strip().upper()
        if symbol.startswith("FILE CREATION TIME"):
            footer = True
            continue
        if footer or not _SYMBOL.fullmatch(symbol) or symbol in rows:
            raise DirectoryRefused("Nasdaq directory has duplicate or invalid symbol")
        if row.get(None) is not None:
            raise DirectoryRefused("Nasdaq directory row width changed")
        rows[symbol] = {field: str(value or "").strip()
                        for field, value in row.items() if field is not None}
    if not footer or not rows:
        raise DirectoryRefused("Nasdaq directory lacks rows or completion footer")
    return rows


def select_assets(assets: Iterable[Mapping], listed: Mapping[str, Mapping],
                  other: Mapping[str, Mapping]) -> tuple[list[dict], dict]:
    """Choose unambiguous current symbols, preserving Alpaca UUIDs as IDs."""
    overlap = set(listed) & set(other)
    if overlap:
        raise DirectoryRefused("Nasdaq directories overlap on active symbols")
    directory = {**listed, **other}
    selected: list[dict] = []
    reasons: Counter[str] = Counter()
    ids, symbols = set(), set()
    for asset in assets:
        symbol = str(asset.get("symbol") or "").strip().upper()
        asset_id = str(asset.get("id") or "").strip()
        if symbol in symbols or asset_id in ids or not symbol or not asset_id:
            raise DirectoryRefused("Alpaca assets have duplicate or absent identity")
        symbols.add(symbol)
        ids.add(asset_id)
        if (asset.get("class") != "us_equity" or asset.get("status") != "active"
                or asset.get("tradable") is not True or asset.get("exchange") == "OTC"):
            reasons["not_active_listed_tradable_equity"] += 1
            continue
        row = directory.get(symbol)
        if row is None:
            reasons["no_exact_nasdaq_directory_symbol"] += 1
            continue
        if row["Test Issue"] != "N" or row["ETF"] != "N":
            reasons["test_or_etf"] += 1
            continue
        name = row["Security Name"]
        if (_NONCOMMON.search(name) or _BUNDLED_UNITS.search(name)
                or (_DEPOSITARY_SHARES.search(name) and not _EQUITY_ADS.search(name))):
            reasons["explicit_non_stock_instrument"] += 1
            continue
        selected.append({"asset_id": asset_id, "ticker": symbol,
                         "name": name, "exchange": asset["exchange"]})
    selected.sort(key=lambda row: row["ticker"])
    if not selected:
        raise DirectoryRefused("no current common-stock candidates")
    return selected, {"policy": POLICY, "selected": len(selected),
                      "excluded": dict(sorted(reasons.items()))}


def reference_row(asset: Mapping, *, first_session: str, last_session: str,
                  action_unresolved: bool = False) -> dict:
    """Bridge selected identity into the canonical snapshot reference schema."""
    if not first_session or first_session > last_session:
        raise DirectoryRefused("Alpaca listing observation interval is invalid")
    return {"table": "SEP", "permaticker": asset["asset_id"],
            "ticker": asset["ticker"],
            "category": EXCLUDED_CATEGORY if action_unresolved else CATEGORY,
            "relatedtickers": None, "firstpricedate": first_session,
            "lastpricedate": last_session, "sector": None, "isdelisted": "N"}
