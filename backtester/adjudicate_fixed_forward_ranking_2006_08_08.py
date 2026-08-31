#!/usr/bin/env python3
"""Adjudicate 2006-08-08 against Wealth Core's fixed-forward signal contract.

Unlike ``adjudicate_ranking_2006_08_08.py`` (which treats stored Sharadar
SEP.close as the reference signal), this script independently implements the
shared Wealth Core feed contract documented in ``wealth_core/feed.py``:

    signal_close(t) = raw_close(t) * product(split_ratio <= t)

The starting factor is arbitrary positive scale for ranking ratios; 1 is used at
the canonical dataset boundary.  No production or research signal helper is
called. Decimal arithmetic is used throughout the reconstruction and scoring.
"""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal, localcontext
import gzip
import json
from pathlib import Path
import re

TARGET = "2006-08-08"
REQUIRED_CLOSES = 127
SKIP_RECENT = 21
FORMATION_LONG = 126
TRADING_DAYS = Decimal(252)
MARKER = re.compile(r"\[RANKING DIAGNOSTIC\] role=(production|research) (\{.*\})$")


def diagnostics(path: Path) -> dict[str, dict]:
    found = {"production": [], "research": []}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = MARKER.search(raw)
        if not m:
            continue
        payload = json.loads(m.group(2))
        if str(payload.get("session")) == TARGET and payload.get("ranking"):
            found[m.group(1)].append(payload)
    out = {}
    for role, rows in found.items():
        if not rows:
            raise RuntimeError(f"missing {role} ranking diagnostic")
        first = rows[0]
        sig = json.dumps(first, sort_keys=True, separators=(",", ":"))
        if any(json.dumps(r, sort_keys=True, separators=(",", ":")) != sig for r in rows[1:]):
            raise RuntimeError(f"conflicting {role} diagnostic rows")
        out[role] = first
    return out


def session_axis(dataset: Path) -> list[str]:
    out = []
    with (dataset / "session-hashes.csv").open("r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            s = str(row["session"])
            if s <= TARGET:
                out.append(s)
    if not out or out[-1] != TARGET:
        raise RuntimeError("canonical session axis does not reach target")
    return out


def fixed_forward_history(dataset: Path, sids: set[str], sessions: list[str]):
    wanted_sessions = set(sessions)
    factors = {sid: Decimal(1) for sid in sids}
    by_sid: dict[str, dict[str, Decimal]] = {sid: {} for sid in sids}
    tickers = {}
    # Canonical warmup starts in 2006, so one partition is sufficient here.
    with gzip.open(dataset / "observations-2006.csv.gz", "rt", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            session = str(row["session"])
            if session > TARGET:
                break
            if session not in wanted_sessions:
                continue
            sid = str(row["security_id"])
            if sid not in sids:
                continue
            ratio_text = str(row["split_ratio"]).strip()
            raw_text = str(row["raw_close"]).strip()
            if not ratio_text or not raw_text:
                raise RuntimeError(f"missing raw/split field for {sid} {session}")
            ratio = Decimal(ratio_text)
            raw_close = Decimal(raw_text)
            if ratio <= 0 or raw_close <= 0:
                raise RuntimeError(f"non-positive raw/split field for {sid} {session}")
            factors[sid] *= ratio
            by_sid[sid][session] = raw_close * factors[sid]
            tickers[sid] = str(row["ticker"])
    return by_sid, tickers


def signal(values: list[Decimal]):
    if len(values) != REQUIRED_CLOSES:
        raise RuntimeError(f"expected {REQUIRED_CLOSES} fixed-forward closes, got {len(values)}")
    near = values[-(SKIP_RECENT + 1)]
    far = values[-(FORMATION_LONG + 1)]
    last = values[-1]
    momentum = near / far - Decimal(1)
    recent = last / near - Decimal(1)
    segment = values[-(FORMATION_LONG + 1): len(values) - SKIP_RECENT]
    returns = [(cur / prev).ln() for prev, cur in zip(segment, segment[1:])]
    n = Decimal(len(returns))
    avg = sum(returns, Decimal(0)) / n
    variance = sum(((x - avg) ** 2 for x in returns), Decimal(0)) / (n - Decimal(1))
    if variance <= 0:
        raise RuntimeError("non-positive formation variance")
    vol = variance.sqrt() * TRADING_DAYS.sqrt()
    score = (Decimal(1) + momentum).ln() / vol
    return {"momentum": momentum, "recent": recent, "score": score, "volatility": vol}


def first_difference(left, right):
    for i, (a, b) in enumerate(zip(left, right)):
        if a != b:
            return {"index": i, "left": a, "right": b}
    if len(left) != len(right):
        return {"index": min(len(left), len(right)), "left": None, "right": None}
    return None


def error_summary(payload: dict, ref: dict[str, dict[str, Decimal]]):
    result = {}
    for field in ("momentum", "recent", "score"):
        values = [abs(Decimal(str(row[field])) - ref[str(row["security_id"])][field])
                  for row in payload["ranking"]]
        result[field] = {
            "max_abs_error": str(max(values)),
            "mean_abs_error": str(sum(values, Decimal(0)) / Decimal(len(values))),
        }
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", type=Path, required=True)
    ap.add_argument("--diagnostic-log", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()

    d = diagnostics(args.diagnostic_log)
    prod, research = d["production"], d["research"]
    prod_rank = [str(x["security_id"]) for x in prod["ranking"]]
    research_rank = [str(x["security_id"]) for x in research["ranking"]]
    prod_lead = [str(x) for x in prod["leadership_ids"]]
    research_lead = [str(x) for x in research["leadership_ids"]]
    if set(prod_rank) != set(research_rank) or set(prod_lead) != set(research_lead):
        raise RuntimeError("expected ordering-only engine mismatch")
    if set(prod_rank) != set(prod_lead):
        raise RuntimeError("ranking and leadership candidate sets differ")

    sessions = session_axis(args.dataset)
    sids = set(prod_rank)
    histories, tickers = fixed_forward_history(args.dataset, sids, sessions)

    with localcontext() as ctx:
        ctx.prec = 80
        ref = {}
        for sid in sorted(sids):
            available = [(s, histories[sid][s]) for s in sessions if s in histories[sid]]
            if len(available) < REQUIRED_CLOSES:
                raise RuntimeError(f"{sid} has only {len(available)} observations")
            # Production eligibility requires GLOBAL-session continuity. Use the
            # final 127 market sessions and require every one to be present.
            tail_sessions = sessions[-REQUIRED_CLOSES:]
            missing = [s for s in tail_sessions if s not in histories[sid]]
            if missing:
                raise RuntimeError(f"{sid} lacks contiguous fixed-forward history at {missing[0]}")
            ref[sid] = signal([histories[sid][s] for s in tail_sessions])

        ref_lead = sorted(sids, key=lambda sid: (-ref[sid]["momentum"], sid, tickers.get(sid, "")))
        ref_rank = sorted(sids, key=lambda sid: (-ref[sid]["score"], sid, tickers.get(sid, "")))
        checks = {
            "production_leadership_exact": prod_lead == ref_lead,
            "research_leadership_exact": research_lead == ref_lead,
            "production_ranking_exact": prod_rank == ref_rank,
            "research_ranking_exact": research_rank == ref_rank,
        }
        p_exact = checks["production_leadership_exact"] and checks["production_ranking_exact"]
        r_exact = checks["research_leadership_exact"] and checks["research_ranking_exact"]
        if p_exact and not r_exact:
            verdict = "PRODUCTION_MATCHES_FIXED_FORWARD_CAUSAL_REFERENCE"
        elif r_exact and not p_exact:
            verdict = "RESEARCH_MATCHES_FIXED_FORWARD_CAUSAL_REFERENCE"
        elif p_exact and r_exact:
            verdict = "BOTH_MATCH_FIXED_FORWARD_CAUSAL_REFERENCE"
        else:
            verdict = "NEITHER_MATCHES_FIXED_FORWARD_CAUSAL_REFERENCE"

        prod_rows = {str(x["security_id"]): x for x in prod["ranking"]}
        research_rows = {str(x["security_id"]): x for x in research["ranking"]}
        witness_ids = set()
        for diff in (first_difference(prod_lead, research_lead), first_difference(prod_rank, research_rank)):
            if diff:
                witness_ids.update(x for x in (diff["left"], diff["right"]) if x)
        witnesses = []
        for sid in sorted(witness_ids):
            witnesses.append({
                "security_id": sid,
                "ticker": tickers.get(sid),
                "reference": {k: str(v) for k, v in ref[sid].items()},
                "production": {k: prod_rows[sid][k] for k in ("momentum", "recent", "score")},
                "research": {k: research_rows[sid][k] for k in ("momentum", "recent", "score")},
                "reference_leadership_rank": ref_lead.index(sid) + 1,
                "production_leadership_rank": prod_lead.index(sid) + 1,
                "research_leadership_rank": research_lead.index(sid) + 1,
                "reference_durable_rank": ref_rank.index(sid) + 1,
                "production_durable_rank": prod_rank.index(sid) + 1,
                "research_durable_rank": research_rank.index(sid) + 1,
            })

        payload = {
            "schema": "backtester.fixed-forward-ranking-adjudication/1",
            "session": TARGET,
            "contract": "signal_close(t)=raw_close(t)*cumulative_split_factor(t); split factor includes only ratios through t",
            "precision_digits": ctx.prec,
            "candidate_count": len(sids),
            "order_checks": checks,
            "first_engine_leadership_difference": first_difference(prod_lead, research_lead),
            "first_engine_ranking_difference": first_difference(prod_rank, research_rank),
            "numeric_error_vs_reference": {
                "production": error_summary(prod, ref),
                "research": error_summary(research, ref),
            },
            "witnesses": witnesses,
            "verdict": verdict,
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"[FIXED-FORWARD ADJUDICATION] verdict={payload['verdict']}", flush=True)
    print("[FIXED-FORWARD ORDER] " + json.dumps(checks, sort_keys=True), flush=True)
    print("[FIXED-FORWARD NUMERIC ERROR] " + json.dumps(payload["numeric_error_vs_reference"], sort_keys=True), flush=True)
    for witness in witnesses:
        print("[FIXED-FORWARD WITNESS] " + json.dumps(witness, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
