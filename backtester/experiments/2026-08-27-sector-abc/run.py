#!/usr/bin/env python3
"""Fresh chronological A/B/C sector-grouping backtest.

This research runner executes exact current-main production strategy code. It
never reads historical decisions, holdings, allocations, NAVs, crisis dates, or
other prerecorded strategy paths. The only A/B/C difference is the grouping
used by Sentinel's contagion/sector-stress clause.
"""
from __future__ import annotations

import argparse
import bisect
import csv
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import re
import sys
from collections import defaultdict, deque
from typing import Iterable, Mapping, Optional, Sequence
import zipfile

import numpy as np
import pandas as pd


EXPERIMENT_ID = "2026-08-27-sector-ab"
EXPECTED_MAIN_SHA = "c502d077cae9c494f8b74a41ee8be7f40b25837d"
CHAIN_START = "1998-01-02"
END_SESSION = "2026-07-31"
STARTING_CASH = 100_000_000.0
OVERLAY_ONE_WAY_COST = 0.001
PEER_LOOKBACK = 252
PEER_MIN_OBSERVATIONS = 120
PEER_COUNT = 3
PEER_CORRELATION_FLOOR = 0.145
MEASUREMENT_WINDOWS = {
    5: "2021-07-30",
    10: "2016-07-29",
    15: "2011-07-29",
    20: "2006-07-31",
}


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def finite(value) -> bool:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(x)


def positive(value) -> bool:
    return finite(value) and float(value) > 0.0


def normalize_int_text(value) -> Optional[str]:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return str(int(float(text)))
    except (TypeError, ValueError, OverflowError):
        return text


def parse_checksum_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        digest, name = line.split(None, 1)
        name = name.lstrip("* ")
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise RuntimeError(f"invalid SHA256SUMS digest in {path}: {digest}")
        out[name] = digest
    return out


def read_zip_csv(path: Path, *, usecols: Sequence[str] | None = None) -> pd.DataFrame:
    with zipfile.ZipFile(path) as zf:
        members = [name for name in zf.namelist() if name.lower().endswith(".csv")]
        if len(members) != 1:
            raise RuntimeError(f"{path}: expected one CSV member, got {members}")
        with zf.open(members[0]) as f:
            return pd.read_csv(f, usecols=usecols, low_memory=False)


class IdentityResolver:
    """Current Sharadar TICKERS projection, resolved by historical listing bounds."""

    def __init__(self, rows: pd.DataFrame):
        self.by_ticker: dict[str, tuple[tuple[str, str, str], ...]] = {}
        grouped: dict[str, list[tuple[str, str, str]]] = defaultdict(list)
        for row in rows.itertuples(index=False):
            ticker = str(row.ticker).strip()
            sid = normalize_int_text(row.permaticker)
            if not ticker or sid is None:
                continue
            first = "0001-01-01" if pd.isna(row.firstpricedate) else str(row.firstpricedate)[:10]
            last = "9999-12-31" if pd.isna(row.lastpricedate) else str(row.lastpricedate)[:10]
            grouped[ticker].append((first, last, sid))
        for ticker, values in grouped.items():
            self.by_ticker[ticker] = tuple(sorted(set(values)))

    def resolve(self, ticker: str, session: str) -> Optional[str]:
        candidates = self.by_ticker.get(str(ticker), ())
        if not candidates:
            return None
        active = {sid for first, last, sid in candidates if first <= session <= last}
        if len(active) == 1:
            return next(iter(active))
        all_ids = {sid for _first, _last, sid in candidates}
        if not active and len(all_ids) == 1:
            return next(iter(all_ids))
        return None


def latest_non_null(group: pd.DataFrame, column: str):
    usable = group[group[column].notna()]
    if usable.empty:
        return None
    ordered = usable.sort_values(
        ["_last_sort", "_first_sort", "ticker"], kind="mergesort")
    return ordered.iloc[-1][column]


def load_current_metadata(tickers_path: Path, main) -> tuple[dict, dict, IdentityResolver, dict[str, str]]:
    required = [
        "table", "permaticker", "ticker", "category", "sector",
        "relatedtickers", "firstpricedate", "lastpricedate", "exchange",
    ]
    rows = read_zip_csv(tickers_path, usecols=required)
    rows = rows[rows["table"].astype(str).eq("SEP")].copy()
    rows = rows[rows["permaticker"].notna() & rows["ticker"].notna()].copy()
    if rows.empty:
        raise RuntimeError("current TICKERS contains no SEP permanent identities")
    rows["_sid"] = rows["permaticker"].map(normalize_int_text)
    rows = rows[rows["_sid"].notna()].copy()
    rows["_first_sort"] = rows["firstpricedate"].fillna("0001-01-01").astype(str)
    rows["_last_sort"] = rows["lastpricedate"].fillna("9999-12-31").astype(str)

    resolver = IdentityResolver(rows)
    meta: dict[str, object] = {}
    sectors: dict[str, str | None] = {}
    canonical_ticker: dict[str, str] = {}
    parse_related = main["parse_related_tickers"]
    SecurityMeta = main["SecurityMeta"]

    for sid, group in rows.groupby("_sid", sort=True):
        ordered = group.sort_values(
            ["_last_sort", "_first_sort", "ticker"], kind="mergesort")
        representative = ordered.iloc[-1]
        ticker = str(representative["ticker"])
        category = latest_non_null(group, "category")
        sector = latest_non_null(group, "sector")
        related = latest_non_null(group, "relatedtickers")
        first_values = [str(v)[:10] for v in group["firstpricedate"] if pd.notna(v)]
        first_session = min(first_values) if first_values else None
        meta[str(sid)] = SecurityMeta(
            security_id=str(sid), ticker=ticker,
            category=None if category is None else str(category),
            permaticker=str(sid), related_tickers=parse_related(related),
            first_session=first_session, last_session=None,
            exchange=None, exchange_authoritative=False,
        )
        sectors[str(sid)] = None if sector is None else str(sector)
        canonical_ticker[str(sid)] = ticker
    return meta, sectors, resolver, canonical_ticker


def load_phase1_manifest(path: Path) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return {row["file"]: row for row in rows}


def source_hash_for_year(manifest: Mapping[str, Mapping[str, str]], year: int) -> str:
    row = manifest.get(f"SEP_{year}_PIT_ONLY.csv.gz")
    if row is None:
        raise RuntimeError(f"Phase-1 manifest lacks SEP {year}")
    return str(row["source_sha256"])


def find_raw_sep(root: Path, year: int, expected_sha: str) -> Path:
    candidates = sorted(root.glob(f"SHARADAR_SEP_{year}.csv*.gz"))
    if not candidates:
        raise RuntimeError(f"missing raw Sharadar SEP source for {year}")
    observed = [(path, sha256_file(path)) for path in candidates]
    matches = [path for path, digest in observed if digest == expected_sha]
    if len(matches) != 1:
        raise RuntimeError(
            f"SEP {year} source hash mismatch/ambiguity: expected {expected_sha}; "
            + ", ".join(f"{path.name}={digest}" for path, digest in observed))
    return matches[0]


def raw_sep_rows(root: Path, manifest, end: str, observed_inputs: dict[str, dict]) -> Iterable[dict]:
    """Yield canonical keep-last raw SEP rows in strict (date,ticker) order."""
    end_year = int(end[:4])
    for year in range(1998, end_year + 1):
        expected = source_hash_for_year(manifest, year)
        path = find_raw_sep(root, year, expected)
        observed_inputs[f"sharadar/{path.name}"] = {
            "sha256": expected, "bytes": path.stat().st_size,
        }
        cols = ["ticker", "date", "open", "close", "closeunadj", "volume"]
        frame = pd.read_csv(path, usecols=cols, low_memory=False)
        frame["ticker"] = frame["ticker"].astype(str)
        frame["date"] = frame["date"].astype(str).str[:10]
        frame = frame[frame["date"] <= end].copy()
        frame["_seq"] = np.arange(len(frame), dtype=np.int64)
        frame.sort_values(["date", "ticker", "_seq"], inplace=True, kind="mergesort")
        frame.drop_duplicates(["date", "ticker"], keep="last", inplace=True)
        frame.sort_values(["date", "ticker"], inplace=True, kind="mergesort")
        for row in frame.itertuples(index=False):
            yield {
                "ticker": row.ticker, "date": row.date,
                "open": row.open, "close": row.close,
                "closeunadj": row.closeunadj, "volume": row.volume,
            }
        del frame


def build_sfp_levels(path: Path) -> tuple[list[str], dict[str, float], dict[str, float], dict[str, tuple[float, float]]]:
    frame = pd.read_csv(path, compression="gzip", low_memory=False)
    required = {
        "ticker", "date", "raw_open", "raw_close", "close_to_close_factor",
        "prior_close_to_open_factor", "open_to_close_factor",
    }
    if set(frame.columns) != required:
        raise RuntimeError(f"unexpected SFP factor columns: {list(frame.columns)}")
    frame["date"] = frame["date"].astype(str).str[:10]
    spy = frame[frame.ticker.astype(str).eq("SPY")].sort_values("date")
    bil = frame[frame.ticker.astype(str).eq("BIL")].sort_values("date")
    if spy.empty:
        raise RuntimeError("SFP factors contain no SPY")

    spy_level: dict[str, float] = {}
    spy_return: dict[str, float] = {}
    level = 1.0
    prior_date = None
    for row in spy.itertuples(index=False):
        date = str(row.date)
        factor = float(row.close_to_close_factor) if finite(row.close_to_close_factor) else None
        if prior_date is not None:
            if factor is None or factor <= 0:
                raise RuntimeError(f"SPY missing/invalid close factor on {date}")
            level *= factor
            spy_return[date] = factor - 1.0
        spy_level[date] = level
        prior_date = date

    bil_factors: dict[str, tuple[float, float]] = {}
    for row in bil.itertuples(index=False):
        pco = float(row.prior_close_to_open_factor) if finite(row.prior_close_to_open_factor) else None
        o2c = float(row.open_to_close_factor) if finite(row.open_to_close_factor) else None
        if pco is not None and pco > 0 and o2c is not None and o2c > 0:
            bil_factors[str(row.date)] = (pco, o2c)
    sessions = [date for date in spy_level if CHAIN_START <= date <= END_SESSION]
    if not sessions or sessions[-1] != END_SESSION:
        raise RuntimeError(
            f"SPY session axis does not reach requested end {END_SESSION}; "
            f"last={sessions[-1] if sessions else None}")
    return sessions, spy_level, spy_return, bil_factors


def load_actions(path: Path, sessions: Sequence[str], main) -> tuple[list[dict], object, dict]:
    frame = pd.read_csv(path, compression="gzip", low_memory=False)
    required = {"date", "action", "ticker", "value"}
    if set(frame.columns) != required:
        raise RuntimeError(f"unexpected PIT ACTIONS columns: {list(frame.columns)}")
    rows = []
    for i, row in enumerate(frame.itertuples(index=False), 1):
        rows.append({
            "source_row_id": f"pit-actions-{i}",
            "date": str(row.date)[:10],
            "action": "" if pd.isna(row.action) else str(row.action),
            "ticker": "" if pd.isna(row.ticker) else str(row.ticker),
            "value": None if pd.isna(row.value) else row.value,
        })
    replay_rows = [row for row in rows if str(row["date"]) >= CHAIN_START]
    splits = main["split_ratios_from_actions"](replay_rows, sessions)
    dividends = main["dividends_from_actions"](replay_rows, sessions)
    terminal_by_session: dict[str, list[dict]] = defaultdict(list)
    terminal_sides = main["TERMINAL_ACTION_SIDES"]
    for row in replay_rows:
        action = str(row["action"]).lower()
        if action not in terminal_sides:
            continue
        i = bisect.bisect_left(sessions, str(row["date"]))
        if i >= len(sessions):
            continue
        effective = sessions[i]
        if effective <= END_SESSION:
            terminal_by_session[effective].append(row)
    return rows, splits, {"dividends": dividends, "terminal": terminal_by_session}


def build_terminal_events(session: str, rows: Sequence[dict], priced_tickers: set[str], resolver: IdentityResolver, main):
    candidates = []
    ActionSide = main["ActionSide"]
    terminal_sides = main["TERMINAL_ACTION_SIDES"]
    TerminalCandidate = main["TerminalCandidate"]
    terminal_from_action = main["terminal_from_action"]
    for row in rows:
        action = str(row.get("action") or "").lower()
        side = terminal_sides.get(action)
        if side is not ActionSide.TARGET:
            continue
        ticker = str(row.get("ticker") or "")
        if ticker.upper() not in priced_tickers:
            continue
        sid = resolver.resolve(ticker, session)
        if sid is None:
            raise RuntimeError(
                f"terminal identity unresolved for priced {ticker} on {session}")
        terms = terminal_from_action(
            {**row, "vendor_session": str(row.get("date"))}, session,
            security_id=sid,
        )
        if terms is None:
            raise RuntimeError(f"terminal terms not expressible for {ticker} {session}")
        candidates.append(TerminalCandidate(
            terms=terms, source_key=str(row["source_row_id"])))
    events = []
    for outcome in main["coalesce_terminal_terms"](candidates):
        if outcome.conflicting:
            raise RuntimeError(f"conflicting terminal terms for {outcome.key}")
        if outcome.selected is None:
            raise RuntimeError(f"terminal coalescer produced no selection for {outcome.key}")
        events.append(outcome.selected.terms)
    return tuple(events)


FF12_RANGES = {
    "01 NoDur": ((100, 999), (2000, 2399), (2700, 2749), (2770, 2799), (3100, 3199), (3940, 3989)),
    "02 Durbl": ((2500, 2519), (2590, 2599), (3630, 3659), (3710, 3711), (3714, 3714), (3716, 3716), (3750, 3751), (3792, 3792), (3900, 3939), (3990, 3999)),
    "03 Manuf": ((2520, 2589), (2600, 2699), (2750, 2769), (3000, 3099), (3200, 3569), (3580, 3629), (3700, 3709), (3712, 3713), (3715, 3715), (3717, 3749), (3752, 3791), (3793, 3799), (3830, 3839), (3860, 3899)),
    "04 Enrgy": ((1200, 1399), (2900, 2999)),
    "05 Chems": ((2800, 2829), (2840, 2899)),
    "06 BusEq": ((3570, 3579), (3660, 3692), (3694, 3699), (3810, 3829), (7370, 7379)),
    "07 Telcm": ((4800, 4899),),
    "08 Utils": ((4900, 4949),),
    "09 Shops": ((5000, 5999), (7200, 7299), (7600, 7699)),
    "10 Hlth": ((2830, 2839), (3693, 3693), (3840, 3859), (8000, 8099)),
    "11 Money": ((6000, 6999),),
}


def ff12_for_sic(value) -> str:
    try:
        sic = int(float(value))
    except (TypeError, ValueError, OverflowError):
        return "12 Other"
    for label, ranges in FF12_RANGES.items():
        if any(lo <= sic <= hi for lo, hi in ranges):
            return label
    return "12 Other"


class PITFF12:
    def __init__(self, cik_path: Path, sic_path: Path, sid_to_ticker: Mapping[str, str]):
        cik = pd.read_csv(cik_path, compression="gzip", low_memory=False)
        sic = pd.read_csv(sic_path, compression="gzip", low_memory=False)
        required_cik = {"filing_date", "ticker", "issuer_cik"}
        required_sic = {"cik", "sic", "filed"}
        if not required_cik.issubset(cik.columns):
            raise RuntimeError(f"CIK evidence missing columns {sorted(required_cik-set(cik.columns))}")
        if not required_sic.issubset(sic.columns):
            raise RuntimeError(f"SIC evidence missing columns {sorted(required_sic-set(sic.columns))}")
        self.sid_to_ticker = dict(sid_to_ticker)
        self.cik_dates: dict[str, list[str]] = defaultdict(list)
        self.cik_values: dict[str, list[str]] = defaultdict(list)
        cik = cik.sort_values(["ticker", "filing_date"], kind="mergesort")
        for row in cik.itertuples(index=False):
            ticker = str(row.ticker)
            cik_value = normalize_int_text(row.issuer_cik)
            date = str(row.filing_date)[:10]
            if ticker and cik_value and date:
                self.cik_dates[ticker].append(date)
                self.cik_values[ticker].append(cik_value)
        self.sic_dates: dict[str, list[str]] = defaultdict(list)
        self.sic_values: dict[str, list[int]] = defaultdict(list)
        sic = sic.sort_values(["cik", "filed"], kind="mergesort")
        for row in sic.itertuples(index=False):
            cik_value = normalize_int_text(row.cik)
            date = str(row.filed)[:10]
            if not cik_value or not date or pd.isna(row.sic):
                continue
            try:
                sic_value = int(float(row.sic))
            except (TypeError, ValueError, OverflowError):
                continue
            self.sic_dates[cik_value].append(date)
            self.sic_values[cik_value].append(sic_value)
        self._cache: dict[tuple[str, str], str] = {}

    @staticmethod
    def _strict_prior(dates: Sequence[str], values: Sequence, session: str):
        i = bisect.bisect_left(dates, session) - 1
        return values[i] if i >= 0 else None

    def group(self, sid: str, session: str, ticker: str | None = None) -> str:
        key = (str(sid), session)
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        ticker = str(ticker or self.sid_to_ticker.get(str(sid), ""))
        cik = self._strict_prior(
            self.cik_dates.get(ticker, ()), self.cik_values.get(ticker, ()), session)
        if cik is None:
            result = f"UNKNOWN:{sid}"
        else:
            sic = self._strict_prior(
                self.sic_dates.get(cik, ()), self.sic_values.get(cik, ()), session)
            result = f"UNKNOWN:{sid}" if sic is None else ff12_for_sic(sic)
        self._cache[key] = result
        return result


class FF12SectorMap(Mapping[str, str]):
    def __init__(self, model: PITFF12, session: str,
                 sid_to_ticker: Mapping[str, str], meta: Mapping[str, object]):
        self.model = model
        self.session = session
        self.sid_to_ticker = sid_to_ticker
        self.meta = meta

    def __getitem__(self, key: str) -> str:
        sid = str(key)
        return self.model.group(sid, self.session, self.sid_to_ticker.get(sid))

    def __iter__(self):
        return iter(self.meta)

    def __len__(self):
        return len(self.meta)

    def get(self, key: str, default=None):
        if str(key) not in self.meta:
            return default
        return self[str(key)]


class SidSectorMap(Mapping[str, str]):
    def __init__(self, meta: Mapping[str, object]):
        self.meta = meta

    def __getitem__(self, key: str) -> str:
        if str(key) not in self.meta:
            raise KeyError(key)
        return "SID:" + str(key)

    def __iter__(self):
        return iter(self.meta)

    def __len__(self):
        return len(self.meta)

    def get(self, key: str, default=None):
        return "SID:" + str(key) if str(key) in self.meta else default


def corr(left: Sequence[float], right: Sequence[float]) -> Optional[float]:
    if len(left) != len(right) or len(left) < 2:
        return None
    lm = sum(left) / len(left)
    rm = sum(right) / len(right)
    cov = sum((x-lm)*(y-rm) for x, y in zip(left, right))
    lv = sum((x-lm)**2 for x in left)
    rv = sum((y-rm)**2 for y in right)
    if lv <= 0 or rv <= 0:
        return None
    value = cov / math.sqrt(lv*rv)
    return value if math.isfinite(value) else None


class DynamicPeerEngine:
    """Prior-only residual-correlation neighborhoods for the C breadth seam."""

    def __init__(self, breadth_module):
        self.breadth = breadth_module
        self.asset_returns: dict[str, deque[tuple[int, float]]] = defaultdict(
            lambda: deque(maxlen=PEER_LOOKBACK))
        self.market_returns: deque[tuple[int, float]] = deque(maxlen=PEER_LOOKBACK)
        self.current_index = -1
        self.current_session = ""
        self.peer_calculations = 0
        self.insufficient_histories = 0

    def update_market(self, index: int, value: Optional[float]) -> None:
        if finite(value):
            self.market_returns.append((index, float(value)))

    def update_assets(self, index: int, returns: Mapping[str, float]) -> None:
        for sid, value in returns.items():
            if finite(value):
                self.asset_returns[str(sid)].append((index, float(value)))

    def _residuals(self, sid: str) -> dict[int, float]:
        cutoff = self.current_index - PEER_LOOKBACK
        market = {i: v for i, v in self.market_returns if i >= cutoff}
        asset = {i: v for i, v in self.asset_returns.get(str(sid), ()) if i >= cutoff}
        common = sorted(set(market).intersection(asset))
        if len(common) < PEER_MIN_OBSERVATIONS:
            self.insufficient_histories += 1
            return {}
        av = [asset[i] for i in common]
        mv = [market[i] for i in common]
        am = sum(av)/len(av)
        mm = sum(mv)/len(mv)
        mvar = sum((x-mm)**2 for x in mv)
        if mvar <= 0:
            return {}
        beta = sum((a-am)*(m-mm) for a, m in zip(av, mv)) / mvar
        return {i: asset[i] - beta*market[i] for i in common}

    def session_breadth(self, holdings):
        B = self.breadth
        if not holdings:
            return B.SessionBreadth(
                damaged_breadth=0.0, green_breadth=0.0,
                denominator=0, greens=0, ambers=0, reds=0, labels=())
        sids = []
        for h in holdings:
            sector = str(h.sector or "")
            if not sector.startswith("SID:"):
                raise RuntimeError(
                    f"dynamic breadth did not receive SID grouping: {h.sector!r}")
            sids.append(sector[4:])
        residuals = {sid: self._residuals(sid) for sid in sids}
        reds = [B.is_red(h) for h in holdings]
        greens = [B.is_green(h) for h in holdings]
        labels = []
        amber_count = 0
        for i, (sid, h) in enumerate(zip(sids, holdings)):
            scores = []
            left = residuals[sid]
            if left:
                for j, other_sid in enumerate(sids):
                    if i == j:
                        continue
                    right = residuals[other_sid]
                    common = sorted(set(left).intersection(right))
                    if len(common) < PEER_MIN_OBSERVATIONS:
                        continue
                    value = corr([left[k] for k in common], [right[k] for k in common])
                    self.peer_calculations += 1
                    if value is not None and value >= PEER_CORRELATION_FLOOR:
                        scores.append((float(value), str(other_sid), j))
            scores.sort(key=lambda row: (-row[0], row[1]))
            neighbors = [i] + [row[2] for row in scores[:PEER_COUNT]]
            stress = sum(int(reds[j]) for j in neighbors) / len(neighbors)
            core_amber = B.is_amber(h, 0.0, greens[i])
            amber = core_amber or (
                stress >= B.SECTOR_STRESS_AT_OR_ABOVE and not greens[i])
            amber_count += int(amber)
            labels.append(B.HoldingLabel(
                ticker=h.ticker, sector=h.sector, green=greens[i], red=reds[i],
                amber=amber, sector_stress=stress))
        n = len(holdings)
        return B.SessionBreadth(
            damaged_breadth=amber_count/n,
            green_breadth=sum(map(int, greens))/n,
            denominator=n, greens=sum(map(int, greens)), ambers=amber_count,
            reds=sum(map(int, reds)), labels=tuple(labels))


def build_anchor_map(state, bars, meta, prior_split_factor: Mapping[str, float], seen_count: Mapping[str, int], main):
    existing = set((state.feed.get("series") or {}).keys())
    anchors = {}
    FeedAnchor = main["FeedAnchor"]
    for bar in bars:
        sid = str(bar.security_id)
        if sid in existing:
            continue
        m = meta.get(sid)
        if m is None:
            raise RuntimeError(f"bar {sid} has no current SecurityMeta")
        issuer_id, _source = m.issuer_key()
        seen = int(seen_count.get(sid, 0))
        if seen > 0 or m.first_session != bar.session:
            if not issuer_id:
                raise RuntimeError(
                    f"returning/pre-chain security {sid} has unresolved issuer identity")
            anchors[sid] = FeedAnchor(
                security_id=sid, ticker=bar.ticker, issuer_id=issuer_id,
                prior_split_factor=float(prior_split_factor.get(sid, 1.0)))
    return anchors


def state_wc_parity(a, b, session: str) -> None:
    fields = (
        "wealth_core", "pending", "ledger", "last_known",
        "shadow_nav_history", "shadow_peak_nav", "trailing_stop_sessions",
        "recent_leadership",
    )
    for field in fields:
        av, bv = getattr(a, field), getattr(b, field)
        if av != bv:
            raise RuntimeError(f"A/B shared economic state diverged at {session}: {field}")


def wealth_equities(state) -> tuple[Optional[float], float]:
    evidence = (state.last_evidence or {}).get("wealth_core") or {}
    close = evidence.get("estimated_equity")
    op = evidence.get("resolved_open_equity")
    if not positive(close):
        raise RuntimeError(f"Wealth Core lacks positive close equity on {state.last_processed_session}: close={close}")
    if op is not None and not positive(op):
        raise RuntimeError(f"Wealth Core has invalid resolved open equity on {state.last_processed_session}: open={op}")
    return (None if op is None else float(op)), float(close)


def target_allocation(state) -> float:
    decision = state.last_decision or {}
    value = decision.get("target_core_exposure")
    if not finite(value) or not 0.0 <= float(value) <= 1.0:
        raise RuntimeError(
            f"invalid final allocation on {state.last_processed_session}: {value}")
    return float(value)


class OverlayAccount:
    def __init__(self, name: str):
        self.name = name
        self.nav = 1.0
        self.effective = 1.0
        self.pending = 1.0
        self.initialized = False
        self.transition_cost = 0.0
        self.transitions = 0

    def step(self, core_open: Optional[float], core_close: float, prior_core_close: Optional[float],
             bil_gap: float, bil_intraday: float, next_target: float) -> float:
        if not self.initialized or prior_core_close is None:
            self.initialized = True
            self.pending = next_target
            return self.nav
        if core_open is None:
            if abs(self.pending - self.effective) > 1e-15:
                raise RuntimeError(f"{self.name} allocation transition coincides with unresolved Wealth Core open; exact next-open attribution is impossible")
            core_c2c = core_close / prior_core_close
            bil_c2c = bil_gap * bil_intraday
            if not positive(core_c2c) or not positive(bil_c2c):
                raise RuntimeError(f"invalid close-to-close return factor for {self.name}")
            self.nav *= self.effective * core_c2c + (1.0-self.effective) * bil_c2c
            self.pending = next_target
            if not positive(self.nav):
                raise RuntimeError(f"non-positive overlay NAV for {self.name}")
            return self.nav
        core_gap = core_open / prior_core_close
        core_intraday = core_close / core_open
        if not positive(core_gap) or not positive(core_intraday):
            raise RuntimeError(f"invalid Wealth Core return factors for {self.name}")
        nav_open = self.nav * (
            self.effective * core_gap + (1.0-self.effective) * bil_gap)
        new_effective = self.pending
        delta = abs(new_effective - self.effective)
        if delta > 1e-15:
            self.transitions += 1
            cost = OVERLAY_ONE_WAY_COST * delta
            nav_open *= 1.0 - cost
            self.transition_cost += cost
        self.nav = nav_open * (
            new_effective * core_intraday + (1.0-new_effective) * bil_intraday)
        self.effective = new_effective
        self.pending = next_target
        if not positive(self.nav):
            raise RuntimeError(f"non-positive overlay NAV for {self.name}")
        return self.nav


def metric_block(frame: pd.DataFrame, column: str, start: str, years: int) -> dict:
    x = frame[frame["date"] >= start][["date", column]].dropna().copy()
    if x.empty or x.iloc[-1]["date"] != END_SESSION:
        raise RuntimeError(f"{column} has incomplete {years}y measurement window")
    values = x[column].astype(float).to_numpy()
    if len(values) < 2 or values[0] <= 0 or values[-1] <= 0:
        raise RuntimeError(f"{column} invalid measurement values")
    normalized = values / values[0]
    rets = normalized[1:] / normalized[:-1] - 1.0
    std = float(np.std(rets, ddof=1)) if len(rets) > 1 else float("nan")
    sharpe = float(np.mean(rets) / std * math.sqrt(252.0)) if std > 0 else float("nan")
    peak = np.maximum.accumulate(normalized)
    max_dd = float(np.min(normalized/peak - 1.0))
    cagr = float(normalized[-1] ** (1.0/years) - 1.0)
    return {
        "start": str(x.iloc[0]["date"]), "end": END_SESSION,
        "sessions": int(len(x)), "cagr": cagr,
        "sharpe": sharpe, "max_drawdown": max_dd,
        "ending_multiple": float(normalized[-1]),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--lab-root", type=Path, default=Path(os.environ.get("BACKTESTER_LAB_ROOT", ".")))
    ap.add_argument("--main-root", type=Path, default=Path(os.environ.get("BACKTESTER_MAIN_ROOT", "main-src")))
    ap.add_argument("--output", type=Path, default=Path("backtester-results/sector-abc"))
    args = ap.parse_args()
    lab = args.lab_root.resolve()
    main_root = args.main_root.resolve()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(main_root / "shared"))
    sys.path.insert(0, str(main_root))

    from sentinel.breadth import classifier as breadth
    import sentinel.core.production as production
    from sentinel.controller.concordance_parent import load as load_concordance_parent
    from sentinel.controller.machine import Controller
    from sentinel.core.decision import runtime_strategy_identity
    from sentinel.core.production import PublishedSession, SessionState
    from sentinel.feed.actions_map import dividends_from_actions, split_ratios_from_actions
    from sentinel.feed.domains import (
        NormalisationReport, assert_identity_domain, assert_raw_price_domain,
        normalise_sep_rows,
    )
    from sentinel.feed.universe import parse_related_tickers
    from sentinel.core.terminal import (
        ActionSide, TERMINAL_ACTION_SIDES, terminal_from_action,
    )
    from stock_strategy_shared.terminal_coalescing import (
        TerminalCandidate, coalesce_terminal_terms,
    )
    from stock_strategy_shared.split_reconciliation import SPLIT_UNRESOLVED
    from stock_strategy_shared.wealth_core.feed import SecurityMeta

    imported = Path(production.__file__).resolve()
    if main_root not in imported.parents:
        raise RuntimeError(f"production module did not load from exact main checkout: {imported}")
    actual_main_sha = os.environ.get("BACKTESTER_MAIN_SHA", "")
    if actual_main_sha != EXPECTED_MAIN_SHA:
        raise RuntimeError(
            f"main SHA mismatch: expected {EXPECTED_MAIN_SHA}, got {actual_main_sha}")

    main_api = {
        "PublishedSession": PublishedSession,
        "SessionState": SessionState,
        "SecurityMeta": SecurityMeta,
        "parse_related_tickers": parse_related_tickers,
        "split_ratios_from_actions": split_ratios_from_actions,
        "dividends_from_actions": dividends_from_actions,
        "ActionSide": ActionSide,
        "TERMINAL_ACTION_SIDES": TERMINAL_ACTION_SIDES,
        "terminal_from_action": terminal_from_action,
        "TerminalCandidate": TerminalCandidate,
        "coalesce_terminal_terms": coalesce_terminal_terms,
        "FeedAnchor": production.FeedAnchor,
    }

    print(f"[RUN] experiment={EXPERIMENT_ID}", flush=True)
    print(f"[RUN] exact main={EXPECTED_MAIN_SHA}", flush=True)
    print("[RUN] fresh chronological A/B/C replay; no prerecorded decisions", flush=True)

    observed_inputs: dict[str, dict] = {}
    normalization = NormalisationReport()
    canonical_path = os.environ.get("CANONICAL_PIT_DATASET")
    canonical_dataset = None
    canonical_terminals = {}
    if canonical_path:
        from backtester.canonical_pit_dataset import CanonicalPITDataset
        canonical_dataset = CanonicalPITDataset(
            Path(canonical_path), expected_start=CHAIN_START, expected_end=END_SESSION
        )
        observed_inputs["canonical/manifest.json"] = {
            "sha256": sha256_file(canonical_dataset.root / "manifest.json"),
            "bytes": (canonical_dataset.root / "manifest.json").stat().st_size,
            "dataset_hash": canonical_dataset.dataset_hash,
        }
        sessions = list(canonical_dataset.sessions)
        spy_level, spy_return = canonical_dataset.benchmark()
        bil_factors = canonical_dataset.cash_factors()
        action_rows, authoritative_splits = [], {}
        dividends, terminal_by_session = {}, {}
        meta, a_sectors, resolver, sid_to_ticker = canonical_dataset.base_metadata(
            SecurityMeta
        )
        ff12 = canonical_dataset
        normalized = canonical_dataset.normalised_rows()
        canonical_terminals = canonical_dataset.terminal_terms()
        print(
            f"[CANONICAL PIT] dataset_hash={canonical_dataset.dataset_hash}",
            flush=True,
        )
    else:
        phase1_manifest_path = lab / "PIT input data" / "MANIFEST.csv"
        phase1_manifest = load_phase1_manifest(phase1_manifest_path)
        observed_inputs["PIT input data/MANIFEST.csv"] = {
            "sha256": sha256_file(phase1_manifest_path),
            "bytes": phase1_manifest_path.stat().st_size,
        }

        actions_path = lab / "PIT input data" / "ACTIONS_PIT_ONLY.csv.gz"
        action_manifest = phase1_manifest.get(actions_path.name)
        if action_manifest is None or sha256_file(actions_path) != action_manifest["sha256"]:
            raise RuntimeError("PIT ACTIONS hash does not match Phase-1 manifest")
        observed_inputs["PIT input data/ACTIONS_PIT_ONLY.csv.gz"] = {
            "sha256": action_manifest["sha256"], "bytes": actions_path.stat().st_size}

        sfp_path = lab / "PIT input data" / "SFP_SPY_BIL_PRICE_FACTORS_PIT_ONLY.csv.gz"
        price_manifest_path = lab / "PIT input data" / "PRICE_RECONSTRUCTION_MANIFEST.csv"
        with price_manifest_path.open("r", encoding="utf-8", newline="") as f:
            price_manifest = {row["file"]: row for row in csv.DictReader(f)}
        sfp_manifest = price_manifest.get(sfp_path.name)
        if sfp_manifest is None or sha256_file(sfp_path) != sfp_manifest["sha256"]:
            raise RuntimeError("SFP factor hash does not match price manifest")
        observed_inputs["PIT input data/PRICE_RECONSTRUCTION_MANIFEST.csv"] = {
            "sha256": sha256_file(price_manifest_path), "bytes": price_manifest_path.stat().st_size}
        observed_inputs["PIT input data/SFP_SPY_BIL_PRICE_FACTORS_PIT_ONLY.csv.gz"] = {
            "sha256": sfp_manifest["sha256"], "bytes": sfp_path.stat().st_size}

        tickers_path = lab / "sharadar" / "SHARADAR_TICKERS.zip"
        observed_inputs["sharadar/SHARADAR_TICKERS.zip"] = {
            "sha256": sha256_file(tickers_path), "bytes": tickers_path.stat().st_size}

        evidence_root = lab / "research" / "sentinel-fastgate" / "pit-evidence"
        generated = evidence_root / "generated"
        issuer_sums = parse_checksum_file(generated / "SHA256SUMS.txt")
        sic_sums = parse_checksum_file(generated / "SEC_SIC_SHA256SUMS.txt")
        cik_path = generated / "sec_cik_change_events.csv.gz"
        sic_path = generated / "sec_sic_submissions.csv.gz"
        for path, expected in (
            (cik_path, issuer_sums.get(cik_path.name)),
            (sic_path, sic_sums.get(sic_path.name)),
        ):
            if expected is None or sha256_file(path) != expected:
                raise RuntimeError(f"PIT evidence hash mismatch: {path.name}")
            observed_inputs[str(path.relative_to(lab))] = {
                "sha256": expected, "bytes": path.stat().st_size}
        ff12_path = evidence_root / "ff12_sic_definition.txt"
        observed_inputs[str(ff12_path.relative_to(lab))] = {
            "sha256": sha256_file(ff12_path), "bytes": ff12_path.stat().st_size}

        sessions, spy_level, spy_return, bil_factors = build_sfp_levels(sfp_path)
        action_rows, authoritative_splits, action_maps = load_actions(actions_path, sessions, main_api)
        dividends = action_maps["dividends"]
        terminal_by_session = action_maps["terminal"]

        meta, a_sectors, resolver, sid_to_ticker = load_current_metadata(tickers_path, main_api)
        ff12 = PITFF12(cik_path, sic_path, sid_to_ticker)
        normalized = normalise_sep_rows(
            raw_sep_rows(lab / "sharadar", phase1_manifest, END_SESSION, observed_inputs),
            resolve_identity=lambda ticker, session: resolver.resolve(str(ticker), str(session)),
            dividends=dividends, authoritative_splits=authoritative_splits,
            report=normalization)
    controller_config = load_concordance_parent()
    strategy_identity = runtime_strategy_identity(controller_config, concordance=True)
    state_a = SessionState.fresh(
        starting_cash=STARTING_CASH, controller=Controller(controller_config),
        strategy_identity=strategy_identity)
    state_b = SessionState.fresh(
        starting_cash=STARTING_CASH, controller=Controller(controller_config),
        strategy_identity=strategy_identity)
    accounts = {name: OverlayAccount(name) for name in ("A", "B")}
    prior_split_factor: dict[str, float] = defaultdict(lambda: 1.0)
    seen_count: dict[str, int] = defaultdict(int)
    prior_signal_close: dict[str, tuple[int, float]] = {}
    latest_ticker_by_sid: dict[str, str] = {}
    prior_core_close: Optional[float] = None
    daily_rows = []
    expected_pointer = 0
    original_session_breadth = production.session_breadth
    for session, group_iter in itertools.groupby(normalized, key=lambda row: row.vendor.session):
        if session < CHAIN_START:
            continue
        if session > END_SESSION:
            break
        while expected_pointer < len(sessions) and sessions[expected_pointer] < session:
            raise RuntimeError(
                f"normalized SEP omitted XNYS/SPY session {sessions[expected_pointer]}")
        if expected_pointer >= len(sessions) or sessions[expected_pointer] != session:
            raise RuntimeError(f"normalized SEP session {session} is outside SPY session axis")
        idx = expected_pointer
        expected_pointer += 1
        bars = [row.vendor for row in group_iter]
        if not bars:
            raise RuntimeError(f"no normalized bars for {session}")
        priced_tickers = {bar.ticker.upper() for bar in bars}
        terminals = (
            canonical_terminals.get(session, ())
            if canonical_dataset is not None
            else build_terminal_events(
                session, terminal_by_session.get(session, ()), priced_tickers,
                resolver, main_api
            )
        )

        anchors_a = build_anchor_map(
            state_a, bars, meta, prior_split_factor, seen_count, main_api)
        anchors_b = build_anchor_map(
            state_b, bars, meta, prior_split_factor, seen_count, main_api)
        if anchors_a != anchors_b:
            raise RuntimeError(f"A/B feed-anchor sets diverged at {session}")

        tail_start = max(0, idx - 20)
        spy_sessions = sessions[tail_start:idx+1]
        spy_closes = [spy_level[s] for s in spy_sessions]
        common = dict(
            session=session, data_version=1, bars=bars, meta=meta,
            spy_closeadj=spy_closes, spy_sessions=spy_sessions,
            spy_expected_sessions=spy_sessions, terminal_events=terminals,
            feed_anchors=anchors_a,
        )
        pub_a = PublishedSession(sectors=a_sectors, **common)
        causal_ticker_by_sid = dict(latest_ticker_by_sid)
        causal_ticker_by_sid.update(
            {str(bar.security_id): str(bar.ticker) for bar in bars})
        pub_b = PublishedSession(
            sectors=FF12SectorMap(
                ff12, session, causal_ticker_by_sid, meta), **common)
        state_a = production.advance_state(
            state_a, pub_a, controller_config=controller_config,
            strategy_identity=strategy_identity)
        state_b = production.advance_state(
            state_b, pub_b, controller_config=controller_config,
            strategy_identity=strategy_identity)
        state_wc_parity(state_a, state_b, session)
        core_open, core_close = wealth_equities(state_a)
        bil_gap, bil_intraday = bil_factors.get(session, (1.0, 1.0))
        navs = {}
        targets = {
            "A": target_allocation(state_a),
            "B": target_allocation(state_b),
        }
        for name, account in accounts.items():
            navs[name] = account.step(
                core_open, core_close, prior_core_close,
                bil_gap, bil_intraday, targets[name])

        ev_a = state_a.last_evidence or {}
        ev_b = state_b.last_evidence or {}
        strategy_boundary = getattr(
            production, "_certification_strategy_boundary", {}
        ).get(session, {})
        ob_a = ev_a.get("observation") or {}
        ob_b = ev_b.get("observation") or {}
        daily_rows.append({
            "date": session,
            "A_nav": navs["A"], "B_nav": navs["B"],
            "SPY_level": spy_level[session],
            "wealth_core_equity": core_close,
            "A_allocation": targets["A"], "B_allocation": targets["B"],
            "A_native": (state_a.last_decision or {}).get("native_target_core_exposure"),
            "B_native": (state_b.last_decision or {}).get("native_target_core_exposure"),
            "A_damaged": ob_a.get("damaged_breadth"),
            "B_damaged": ob_b.get("damaged_breadth"),
            "green": ob_a.get("green_breadth"),
            "D_eligible_universe": strategy_boundary.get("eligible_universe"),
            "D_ranking_count": strategy_boundary.get("ranking_count"),
            "D_ranking_sha256": strategy_boundary.get("ranking_sha256"),
            "D_selected_positions_sha256": strategy_boundary.get(
                "selected_positions_sha256"
            ),
            "D_selected_positions": json.dumps(
                strategy_boundary.get("selected_positions") or [],
                separators=(",", ":"),
            ),
            "D_intents": json.dumps(
                strategy_boundary.get("intents") or [],
                sort_keys=True, separators=(",", ":"),
            ),
            "D_ldrc_state": json.dumps(
                state_b.ldrc or {}, sort_keys=True, separators=(",", ":")
            ),
        })

        current_asset_returns: dict[str, float] = {}
        for bar in bars:
            sid = str(bar.security_id)
            current_factor = float(prior_split_factor.get(sid, 1.0)) * float(bar.split_ratio)
            if positive(bar.raw_close):
                signal_close = float(bar.raw_close) * current_factor
                prior = prior_signal_close.get(sid)
                if prior is not None and prior[0] == idx-1 and prior[1] > 0:
                    current_asset_returns[sid] = signal_close/prior[1] - 1.0
                prior_signal_close[sid] = (idx, signal_close)
            prior_split_factor[sid] = current_factor
            seen_count[sid] += 1
            latest_ticker_by_sid[sid] = str(bar.ticker)
        prior_core_close = core_close

        if idx % 252 == 0 or session == END_SESSION:
            print(
                f"[RUN] {session} sessions={idx+1:,} "
                f"A={accounts['A'].nav:.6f} B={accounts['B'].nav:.6f}", flush=True)

    production.session_breadth = original_session_breadth
    if expected_pointer != len(sessions):
        raise RuntimeError(
            f"replay ended before SPY session axis: processed={expected_pointer} expected={len(sessions)}")

    if canonical_dataset is None:
        assert_raw_price_domain(normalization)
    bad_identity = []
    if canonical_dataset is None:
        for session in sessions:
            coverage = assert_identity_domain(normalization, session)
            if coverage is not None and coverage < 1.0:
                bad_identity.append((session, coverage))
    unresolved_splits = [
        {"ticker": key[0], "session": key[1], **value}
        for key, value in normalization.split_dispositions.items()
        if value.get("disposition") == SPLIT_UNRESOLVED
    ]
    if unresolved_splits:
        raise RuntimeError(
            f"current-main split reconciliation left {len(unresolved_splits)} unresolved event(s): "
            f"{unresolved_splits[:5]}")

    daily = pd.DataFrame(daily_rows)
    if daily.empty or daily.iloc[-1]["date"] != END_SESSION:
        raise RuntimeError("fresh replay did not reach requested end session")
    metrics_rows = []
    summary_metrics = {}
    for years, start in sorted(MEASUREMENT_WINDOWS.items()):
        summary_metrics[str(years)] = {}
        for label, column in (
            ("A", "A_nav"), ("B", "B_nav"),
            ("SPY", "SPY_level"),
        ):
            block = metric_block(daily, column, start, years)
            summary_metrics[str(years)][label] = block
            metrics_rows.append({
                "window_years": years, "variant": label,
                "start": block["start"], "end": block["end"],
                "sessions": block["sessions"],
                "cagr": block["cagr"], "sharpe": block["sharpe"],
                "max_drawdown": block["max_drawdown"],
                "ending_multiple": block["ending_multiple"],
            })

    daily_path = output / "daily.csv.gz"
    metrics_path = output / "metrics.csv"
    summary_path = output / "summary.json"
    manifest_path = output / "manifest.json"
    daily.to_csv(
        daily_path, index=False,
        compression={"method": "gzip", "compresslevel": 6, "mtime": 0})
    pd.DataFrame(metrics_rows).to_csv(metrics_path, index=False)

    summary = {
        "experiment": EXPERIMENT_ID,
        "status": "PASS",
        "main_sha": EXPECTED_MAIN_SHA,
        "backtester_sha": os.environ.get("BACKTESTER_BRANCH_SHA"),
        "chain_start": CHAIN_START,
        "end_session": END_SESSION,
        "fresh_chronological_replay": True,
        "canonical_pit_dataset_hash": (
            canonical_dataset.dataset_hash if canonical_dataset is not None else None
        ),
        "prerecorded_decision_inputs": False,
        "wealth_core_parity": True,
        "variant_definition": {
            "A": "current-main current Sharadar sector grouping; historical metadata causality not claimed",
            "B": "A with sector contagion grouping replaced only by strict-prior SEC SIC -> FF12",
        },
        "overlay_accounting": {
            "decision_timing": "close decision -> following session open",
            "one_way_allocation_change_cost": OVERLAY_ONE_WAY_COST,
            "defensive_asset": "BIL when complete frozen factors exist; cash before BIL inception",
        },
        "metrics": summary_metrics,
        "transitions": {name: account.transitions for name, account in accounts.items()},
        "transition_cost_sum": {name: account.transition_cost for name, account in accounts.items()},
        "normalization": {
            "rows": normalization.rows,
            "bars": normalization.bars,
            "dropped_no_identity": normalization.dropped_no_identity,
            "dropped_no_raw_close": normalization.dropped_no_raw_close,
            "raw_close_coverage": normalization.raw_close_coverage,
            "splits_detected": normalization.splits_detected,
            "identity_partial_sessions": [
                {"session": s, "coverage": c} for s, c in bad_identity],
        },
    }
    summary_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    manifest = {
        "schema": "backtester.experiment-manifest/1",
        "experiment": EXPERIMENT_ID,
        "main_sha": EXPECTED_MAIN_SHA,
        "backtester_sha": os.environ.get("BACKTESTER_BRANCH_SHA"),
        "production_module": str(imported),
        "production_module_sha256": sha256_file(imported),
        "strategy_identity": strategy_identity,
        "input_files": dict(sorted(observed_inputs.items())),
        "outputs": {},
    }
    for path in (daily_path, metrics_path, summary_path):
        manifest["outputs"][path.name] = {
            "sha256": sha256_file(path), "bytes": path.stat().st_size}
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    sums = output / "SHA256SUMS.txt"
    files = (daily_path, metrics_path, summary_path, manifest_path)
    sums.write_text(
        "".join(f"{sha256_file(path)}  {path.name}\n" for path in files),
        encoding="utf-8")

    print("[PASS] fresh A/B replay completed", flush=True)
    print(pd.DataFrame(metrics_rows).to_string(index=False), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
