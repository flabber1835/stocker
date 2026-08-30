#!/usr/bin/env python3
"""Emit bounded raw evidence for strict-PIT Run #15 blockers."""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd

TARGETS = {
    ("AAWW", "2006-04-03"),
    ("SIM", "2006-05-30"),
    ("MBCRQ", "2006-06-20"),
    ("SCEIQ", "2007-08-21"),
    ("ETELY", "2007-09-04"),
}


def _records(frame: pd.DataFrame) -> list[dict]:
    return json.loads(frame.to_json(orient="records", date_format="iso"))


def _split_ratio(prev: dict, cur: dict) -> float | None:
    try:
        pc = float(prev["close"])
        pr = float(prev["closeunadj"])
        cc = float(cur["close"])
        cr = float(cur["closeunadj"])
    except (KeyError, TypeError, ValueError):
        return None
    if any(not math.isfinite(x) or x <= 0 for x in (pc, pr, cc, cr)):
        return None
    return (pr * cc) / (pc * cr)


def split_evidence(root: Path) -> dict:
    actions_path = root / "PIT input data" / "ACTIONS_PIT_ONLY.csv.gz"
    actions = pd.read_csv(actions_path, compression="gzip", low_memory=False)
    actions["ticker"] = actions.ticker.astype(str).str.upper()
    date_col = "date" if "date" in actions.columns else "eventdate"
    actions[date_col] = actions[date_col].astype(str).str[:10]
    action_dates = pd.to_datetime(actions[date_col], errors="coerce")
    out: dict[str, dict] = {}
    for ticker, session in sorted(TARGETS):
        target = pd.Timestamp(session)
        ticker_mask = actions.ticker == ticker
        exact_mask = ticker_mask & (actions[date_col] == session)
        nearby_mask = ticker_mask & action_dates.between(
            target - pd.Timedelta(days=21), target + pd.Timedelta(days=21)
        )
        ticker_rows = actions[ticker_mask]
        exact_rows = actions[exact_mask]
        nearby_rows = actions[nearby_mask].sort_values(date_col)
        year = session[:4]
        candidates = sorted((root / "sharadar").glob(f"SHARADAR_SEP_{year}.csv*.gz"))
        if not candidates:
            raise RuntimeError(f"missing SEP file for {year}")
        sep = pd.read_csv(candidates[0], compression="gzip", low_memory=False)
        sep["ticker"] = sep.ticker.astype(str).str.upper()
        sep["date"] = sep.date.astype(str).str[:10]
        q = sep[sep.ticker == ticker].sort_values("date").reset_index(drop=True)
        idxs = q.index[q.date == session].tolist()
        common = {
            "action_columns": list(map(str, actions.columns)),
            "actions_exact": _records(exact_rows),
            "actions_nearby_21d": _records(nearby_rows),
            "actions_ticker_total": int(len(ticker_rows)),
        }
        if not idxs:
            window = q[(q.date >= session[:7] + "-01") & (q.date <= session[:7] + "-31")]
            out[f"{ticker}:{session}"] = {
                **common,
                "sep_event_missing": True,
                "sep_month": _records(window),
            }
            continue
        idx = idxs[-1]
        lo, hi = max(0, idx - 3), min(len(q), idx + 4)
        window = q.iloc[lo:hi]
        prev = q.iloc[idx - 1].to_dict() if idx > 0 else {}
        cur = q.iloc[idx].to_dict()
        out[f"{ticker}:{session}"] = {
            **common,
            "sep_window": _records(window),
            "derived_from_immediately_prior_sep_row": _split_ratio(prev, cur),
        }
    return out


def security_type_inventory(root: Path) -> dict:
    positive_path = root / "PIT input data" / "SEC_SECURITY_TYPE_POSITIVE_EVIDENCE.csv.gz"
    positive = pd.read_csv(positive_path, compression="gzip", low_memory=False)
    result = {
        "positive_rows": int(len(positive)),
        "columns": list(map(str, positive.columns)),
    }
    for field in ("security_title", "security_type", "title"):
        if field in positive.columns:
            counts = positive[field].fillna("<missing>").astype(str).value_counts().head(50)
            result["positive_evidence_by_security_type"] = {
                str(k): int(v) for k, v in counts.items()
            }
            result["security_type_field"] = field
            break
    if "cik" in positive.columns:
        result["positive_rows_with_cik"] = int(positive.cik.notna().sum())
        result["positive_rows_without_cik"] = int(positive.cik.isna().sum())
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema": "backtester.strict-pit-run15-diagnostics/1",
        "splits": split_evidence(args.root),
        "security_type_evidence_inventory": security_type_inventory(args.root),
    }
    path = args.output / "run15_blocker_diagnostics.json"
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[DIAGNOSTIC] wrote {path}", flush=True)
    for key, row in payload["splits"].items():
        print(
            f"[SPLIT RAW] {key} derived={row.get('derived_from_immediately_prior_sep_row')} "
            f"actions_exact={len(row.get('actions_exact') or [])} "
            f"actions_nearby={len(row.get('actions_nearby_21d') or [])}",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
