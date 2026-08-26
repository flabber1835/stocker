#!/usr/bin/env python3
"""Diagnose the retained 2008/2022 leadership-population fingerprints.

This is a research-only gate diagnostic.  It deliberately evaluates two category
models on exactly the same PIT price/liquidity history:

* legacy_current_category: current Sharadar TICKERS category (non-PIT), used only
  as a falsifier that this independent calculation reproduces the prior replay;
* sec_auto_common: common-equity evidence whose SEC filing date is strictly
  before the target session.  Unknown is fail-closed/ineligible.

No strategy performance is computed here.
"""
from __future__ import annotations

import csv
import gzip
import io
import json
import math
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PIT = ROOT / "PIT input data"
TICKERS_ZIP = ROOT / "sharadar" / "SHARADAR_TICKERS.zip"
SEC_EVIDENCE = PIT / "SEC_SECURITY_TYPE_POSITIVE_EVIDENCE.csv.gz"
OUT = PIT / "PIT_LEADERSHIP_FINGERPRINT_AUDIT.json"

TARGETS = {
    "2008-12-23": {"expected_pool": 101, "expected_overlap": 7},
    "2022-01-03": {"expected_pool": 96, "expected_overlap": 8},
}
MIN_PRICE = 1.0
MIN_ADV20 = 20_000_000.0
MIN_DAILY_DOLLAR = 5_000_000.0
TOP_FRAC = 0.10
NPOS = 25


def _read_zip_csv(path: Path) -> pd.DataFrame:
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if n.lower().endswith((".csv", ".tsv"))]
        if len(names) != 1:
            raise RuntimeError(f"expected one table in {path}: {names}")
        raw = z.read(names[0]).decode("utf-8-sig", errors="replace")
        first = raw.splitlines()[0]
        sep = "\t" if first.count("\t") >= first.count(",") else ","
        return pd.read_csv(io.StringIO(raw), sep=sep, low_memory=False)


def legacy_common() -> set[str]:
    d = _read_zip_csv(TICKERS_ZIP)
    d = d[d["table"].astype(str).eq("SEP")]
    cat = d["category"].fillna("").astype(str)
    ok = cat.str.contains("Common Stock", regex=False) & ~cat.str.contains("Warrant", regex=False) & ~cat.str.contains("Preferred", regex=False)
    return set(d.loc[ok, "ticker"].astype(str).str.upper())


def first_sec_common() -> dict[str, str]:
    out: dict[str, str] = {}
    with gzip.open(SEC_EVIDENCE, "rt", newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            t = (r.get("ticker") or "").strip().upper()
            d = (r.get("filed") or "").strip()
            if t and d and (t not in out or d < out[t]):
                out[t] = d
    return out


def load_window(target: pd.Timestamp) -> tuple[pd.DataFrame, list[pd.Timestamp]]:
    # Two calendar years are comfortably longer than the 126-session lookback.
    years = [target.year - 1, target.year]
    parts = []
    for y in years:
        base = pd.read_csv(
            PIT / f"SEP_{y}_PIT_ONLY.csv.gz",
            usecols=["ticker", "date", "volume", "closeunadj"],
            low_memory=False,
        )
        price = pd.read_csv(
            PIT / f"SEP_PRICE_{y}_PIT_ONLY.csv.gz",
            usecols=["ticker", "date", "signal_close"],
            low_memory=False,
        )
        x = base.merge(price, on=["ticker", "date"], how="inner", validate="one_to_one")
        x["date"] = pd.to_datetime(x["date"])
        parts.append(x)
    d = pd.concat(parts, ignore_index=True)
    d["ticker"] = d["ticker"].astype(str).str.upper()
    d = d[d["date"] <= target].copy()
    sessions = sorted(pd.unique(d["date"]))
    if target not in sessions:
        raise RuntimeError(f"target session absent: {target.date()}")
    ti = sessions.index(target)
    if ti < 126:
        raise RuntimeError(f"insufficient warmup for {target.date()}: {ti}")
    keep_sessions = sessions[ti - 126 : ti + 1]
    return d[d["date"].isin(keep_sessions)].copy(), keep_sessions


def fingerprint(target_s: str, legacy: set[str], sec_first: dict[str, str]) -> dict:
    target = pd.Timestamp(target_s)
    d, sessions = load_window(target)
    session_to_col = {s: i for i, s in enumerate(sessions)}
    d["j"] = d["date"].map(session_to_col)

    tickers = sorted(set(d.loc[d["date"].eq(target), "ticker"]))
    row = {t: i for i, t in enumerate(tickers)}
    n = len(tickers)
    close = np.full((n, 127), np.nan, dtype=np.float64)
    raw = np.full((n, 127), np.nan, dtype=np.float64)
    vol = np.full((n, 127), np.nan, dtype=np.float64)

    q = d[d["ticker"].isin(row)]
    for r in q.itertuples(index=False):
        i = row[r.ticker]
        j = int(r.j)
        close[i, j] = float(r.signal_close) if pd.notna(r.signal_close) else np.nan
        raw[i, j] = float(r.closeunadj) if pd.notna(r.closeunadj) else np.nan
        vol[i, j] = float(r.volume) if pd.notna(r.volume) else np.nan

    # Exact standalone continuity condition at the target: 126 valid consecutive
    # close-to-close returns through the target session.
    valid_close = np.isfinite(close) & (close > 0)
    continuous = valid_close.all(axis=1)
    logret = np.log(close[:, 1:] / close[:, :-1])
    # standalone fvol = 126-session return buffer less latest 21 returns
    f = logret[:, :105]
    fcnt = np.isfinite(f).sum(axis=1)
    fsum = np.nansum(f, axis=1)
    fsq = np.nansum(f * f, axis=1)
    var = np.full(n, np.nan)
    m = fcnt > 1
    var[m] = (fsq[m] - fsum[m] * fsum[m] / fcnt[m]) / (fcnt[m] - 1)
    fvol = np.sqrt(np.maximum(var, 0.0)) * np.sqrt(252.0)

    lag21 = close[:, 105]
    lag126 = close[:, 0]
    ss = lag21 / lag126 - 1.0
    score = np.full(n, np.nan)
    m = np.isfinite(ss) & (ss > -1) & np.isfinite(fvol) & (fvol > 0)
    score[m] = np.log1p(ss[m]) / fvol[m]

    dv = raw * vol
    adv20 = np.nansum(dv[:, -20:], axis=1) / 20.0
    # Because the standalone ring inserts zeros for absent/non-finite dollar
    # volume, nansum is the equivalent fail-closed arithmetic here.
    daily = dv[:, -1]
    base = (
        continuous
        & np.isfinite(ss)
        & np.isfinite(raw[:, -1])
        & (raw[:, -1] >= MIN_PRICE)
        & np.isfinite(adv20)
        & (adv20 >= MIN_ADV20)
        & np.isfinite(daily)
        & (daily >= MIN_DAILY_DOLLAR)
        & np.isfinite(score)
    )

    sec_ok = np.array([sec_first.get(t, "9999-99-99") < target_s for t in tickers], dtype=bool)
    legacy_ok = np.array([t in legacy for t in tickers], dtype=bool)

    def summarize(cat: np.ndarray) -> dict:
        elig = base & cat
        ids = np.flatnonzero(elig)
        vals = ss[ids]
        # lexical ticker order is the explicit PIT tie order; mergesort preserves it.
        order = np.argsort(-vals, kind="mergesort")
        ranked = ids[order]
        pool_n = max(NPOS, int(math.ceil(len(ids) * TOP_FRAC))) if len(ids) else 0
        pool = ranked[:pool_n]
        return {
            "eligible": int(len(ids)),
            "leadership_population": int(len(pool)),
            "pool_tickers": [tickers[i] for i in pool],
        }

    a = summarize(legacy_ok)
    b = summarize(sec_ok)
    unknown_numeric = [tickers[i] for i in np.flatnonzero(base & ~sec_ok)]
    return {
        "target": target_s,
        "expected_retained": TARGETS[target_s],
        "legacy_current_category_control": a,
        "sec_auto_common_fail_closed": b,
        "numeric_survivors_without_pre_session_sec_common": len(unknown_numeric),
        "numeric_survivors_without_pre_session_sec_common_tickers": unknown_numeric,
    }


def main() -> None:
    legacy = legacy_common()
    sec_first = first_sec_common()
    report = {
        "purpose": "PIT category/opportunity-set control diagnostic; no performance claim",
        "category_cutoff": "SEC filing date strictly before target session; unknown ineligible",
        "targets": [fingerprint(t, legacy, sec_first) for t in TARGETS],
    }
    OUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
