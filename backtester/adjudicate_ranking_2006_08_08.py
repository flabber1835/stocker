#!/usr/bin/env python3
"""Independently adjudicate the 2006-08-08 research/production ranking mismatch.

This script deliberately does not call either replay engine's signal helpers. It
reads the immutable canonical PIT signal-close history as decimal text and
recomputes the certified signal formulas with Python Decimal at high precision.
The resulting reference ordering is compared with the production and retained
research diagnostics emitted by the bounded replay.
"""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal, localcontext
import gzip
import json
from pathlib import Path
import re
from statistics import mean

TARGET = "2006-08-08"
REQUIRED_CLOSES = 127
SKIP_RECENT = 21
FORMATION_LONG = 126
TRADING_DAYS = Decimal(252)
MARKER = re.compile(r"\[RANKING DIAGNOSTIC\] role=(production|research) (\{.*\})$")


def parse_diagnostics(path: Path) -> dict[str, dict]:
    found: dict[str, list[dict]] = {"production": [], "research": []}
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = MARKER.search(raw)
        if not match:
            continue
        role = match.group(1)
        payload = json.loads(match.group(2))
        if str(payload.get("session")) == TARGET and payload.get("ranking"):
            found[role].append(payload)
    result = {}
    for role, rows in found.items():
        if not rows:
            raise RuntimeError(f"missing non-empty {role} diagnostic for {TARGET}")
        # The production diagnostic can emit an early empty snapshot before the
        # canonical observation has been installed. The non-empty snapshot is
        # the economically relevant one; require all non-empty copies to agree.
        first = rows[0]
        canonical = json.dumps(first, sort_keys=True, separators=(",", ":"))
        for row in rows[1:]:
            if json.dumps(row, sort_keys=True, separators=(",", ":")) != canonical:
                raise RuntimeError(f"conflicting non-empty {role} diagnostics")
        result[role] = first
    return result


def session_window(dataset: Path) -> list[str]:
    sessions = []
    with (dataset / "session-hashes.csv").open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            session = str(row["session"])
            if session <= TARGET:
                sessions.append(session)
    if not sessions or sessions[-1] != TARGET:
        raise RuntimeError(f"canonical session axis does not reach {TARGET}")
    if len(sessions) < REQUIRED_CLOSES:
        raise RuntimeError("canonical dataset lacks required 127-session history")
    return sessions[-REQUIRED_CLOSES:]


def canonical_closes(dataset: Path, security_ids: set[str], sessions: list[str]):
    wanted_sessions = set(sessions)
    closes: dict[str, dict[str, str]] = {sid: {} for sid in security_ids}
    tickers: dict[str, str] = {}
    path = dataset / "observations-2006.csv.gz"
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            session = str(row["session"])
            if session not in wanted_sessions:
                continue
            sid = str(row["security_id"])
            if sid not in closes:
                continue
            value = str(row["signal_close"]).strip()
            if not value:
                raise RuntimeError(f"blank canonical signal_close for {sid} on {session}")
            closes[sid][session] = value
            tickers[sid] = str(row["ticker"])
    ordered: dict[str, list[Decimal]] = {}
    for sid in sorted(security_ids):
        missing = [s for s in sessions if s not in closes[sid]]
        if missing:
            raise RuntimeError(
                f"candidate {sid} lacks continuous canonical history; first missing={missing[0]}")
        values = [Decimal(closes[sid][s]) for s in sessions]
        if any(v <= 0 for v in values):
            raise RuntimeError(f"candidate {sid} has non-positive canonical signal close")
        ordered[sid] = values
    return ordered, tickers


def reference_signal(values: list[Decimal]) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    if len(values) != REQUIRED_CLOSES:
        raise RuntimeError("reference window length changed")
    near = values[-(SKIP_RECENT + 1)]
    far = values[-(FORMATION_LONG + 1)]
    last = values[-1]
    momentum = near / far - Decimal(1)
    recent = last / near - Decimal(1)
    # t-126 through t-21 inclusive = 106 closes = 105 one-session returns.
    segment = values[-(FORMATION_LONG + 1): len(values) - SKIP_RECENT]
    log_returns = [(cur / prev).ln() for prev, cur in zip(segment, segment[1:])]
    n = Decimal(len(log_returns))
    avg = sum(log_returns, Decimal(0)) / n
    variance = sum(((r - avg) ** 2 for r in log_returns), Decimal(0)) / (n - Decimal(1))
    if variance <= 0:
        raise RuntimeError("non-positive reference formation variance")
    volatility = variance.sqrt() * TRADING_DAYS.sqrt()
    score = (Decimal(1) + momentum).ln() / volatility
    return momentum, recent, volatility, score


def dec(value) -> Decimal:
    return Decimal(str(value))


def numeric_errors(payload: dict, reference: dict[str, dict[str, Decimal]]) -> dict:
    errors = {"momentum": [], "recent": [], "score": []}
    per_sid = {}
    for row in payload["ranking"]:
        sid = str(row["security_id"])
        item = {}
        for field in errors:
            error = abs(dec(row[field]) - reference[sid][field])
            errors[field].append(error)
            item[field] = error
        per_sid[sid] = item
    summary = {}
    for field, values in errors.items():
        summary[field] = {
            "max_abs_error": str(max(values)),
            "mean_abs_error": str(sum(values, Decimal(0)) / Decimal(len(values))),
        }
    return {"summary": summary, "per_sid": per_sid}


def first_difference(a: list[str], b: list[str]) -> dict | None:
    for index, (left, right) in enumerate(zip(a, b)):
        if left != right:
            return {"index": index, "left": left, "right": right}
    if len(a) != len(b):
        return {"index": min(len(a), len(b)), "left": None, "right": None}
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--diagnostic-log", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    diagnostics = parse_diagnostics(args.diagnostic_log)
    prod = diagnostics["production"]
    research = diagnostics["research"]
    if int(prod["eligible_universe"]) != int(research["eligible_universe"]):
        raise RuntimeError("eligible universes differ; arithmetic adjudication would be premature")

    prod_rank_ids = [str(row["security_id"]) for row in prod["ranking"]]
    research_rank_ids = [str(row["security_id"]) for row in research["ranking"]]
    prod_lead_ids = [str(x) for x in prod["leadership_ids"]]
    research_lead_ids = [str(x) for x in research["leadership_ids"]]
    if set(prod_rank_ids) != set(research_rank_ids):
        raise RuntimeError("ranked candidate membership differs; expected ordering-only mismatch")
    if set(prod_lead_ids) != set(research_lead_ids):
        raise RuntimeError("leadership membership differs; expected ordering-only mismatch")
    if set(prod_rank_ids) != set(prod_lead_ids):
        raise RuntimeError("diagnostic ranking and leadership sets do not describe the same candidates")

    sessions = session_window(args.dataset)
    security_ids = set(prod_rank_ids)
    close_map, tickers = canonical_closes(args.dataset, security_ids, sessions)

    with localcontext() as ctx:
        ctx.prec = 80
        reference: dict[str, dict[str, Decimal]] = {}
        for sid, values in close_map.items():
            momentum, recent, volatility, score = reference_signal(values)
            reference[sid] = {
                "momentum": momentum,
                "recent": recent,
                "volatility": volatility,
                "score": score,
            }

        ref_lead = sorted(
            security_ids,
            key=lambda sid: (-reference[sid]["momentum"], sid, tickers.get(sid, "")),
        )
        ref_rank = sorted(
            security_ids,
            key=lambda sid: (-reference[sid]["score"], sid, tickers.get(sid, "")),
        )

        prod_errors = numeric_errors(prod, reference)
        research_errors = numeric_errors(research, reference)

        order_checks = {
            "production_leadership_exact": prod_lead_ids == ref_lead,
            "research_leadership_exact": research_lead_ids == ref_lead,
            "production_ranking_exact": prod_rank_ids == ref_rank,
            "research_ranking_exact": research_rank_ids == ref_rank,
        }
        prod_exact = order_checks["production_leadership_exact"] and order_checks["production_ranking_exact"]
        research_exact = order_checks["research_leadership_exact"] and order_checks["research_ranking_exact"]
        if prod_exact and not research_exact:
            verdict = "PRODUCTION_MATCHES_HIGH_PRECISION_REFERENCE"
        elif research_exact and not prod_exact:
            verdict = "RESEARCH_MATCHES_HIGH_PRECISION_REFERENCE"
        elif prod_exact and research_exact:
            verdict = "BOTH_MATCH_HIGH_PRECISION_REFERENCE"
        else:
            verdict = "NEITHER_MATCHES_HIGH_PRECISION_REFERENCE"

        first_lead_engine_diff = first_difference(prod_lead_ids, research_lead_ids)
        first_rank_engine_diff = first_difference(prod_rank_ids, research_rank_ids)
        witnesses = []
        witness_ids = set()
        for diff in (first_lead_engine_diff, first_rank_engine_diff):
            if diff:
                witness_ids.update(x for x in (diff["left"], diff["right"]) if x)
        prod_rows = {str(r["security_id"]): r for r in prod["ranking"]}
        research_rows = {str(r["security_id"]): r for r in research["ranking"]}
        for sid in sorted(witness_ids):
            witnesses.append({
                "security_id": sid,
                "ticker": tickers.get(sid),
                "reference": {k: str(v) for k, v in reference[sid].items()},
                "production": {
                    "momentum": prod_rows[sid]["momentum"],
                    "recent": prod_rows[sid]["recent"],
                    "score": prod_rows[sid]["score"],
                },
                "research": {
                    "momentum": research_rows[sid]["momentum"],
                    "recent": research_rows[sid]["recent"],
                    "score": research_rows[sid]["score"],
                },
                "production_abs_error": {
                    k: str(v) for k, v in prod_errors["per_sid"][sid].items()
                },
                "research_abs_error": {
                    k: str(v) for k, v in research_errors["per_sid"][sid].items()
                },
                "reference_leadership_rank": ref_lead.index(sid) + 1,
                "production_leadership_rank": prod_lead_ids.index(sid) + 1,
                "research_leadership_rank": research_lead_ids.index(sid) + 1,
                "reference_durable_rank": ref_rank.index(sid) + 1,
                "production_durable_rank": prod_rank_ids.index(sid) + 1,
                "research_durable_rank": research_rank_ids.index(sid) + 1,
            })

        payload = {
            "schema": "backtester.ranking-high-precision-adjudication/1",
            "session": TARGET,
            "reference": {
                "source": "canonical PIT observations-2006.csv.gz signal_close decimal text",
                "precision_digits": ctx.prec,
                "momentum": "close[t-21] / close[t-126] - 1",
                "recent": "close[t] / close[t-21] - 1",
                "volatility": "sample stdev of 105 log returns over t-126..t-21, annualized sqrt(252)",
                "durable_score": "ln(1+momentum) / annualized formation volatility",
            },
            "eligible_universe": int(prod["eligible_universe"]),
            "candidate_count": len(security_ids),
            "canonical_window_sessions": [sessions[0], sessions[-1]],
            "order_checks": order_checks,
            "first_engine_leadership_difference": first_lead_engine_diff,
            "first_engine_ranking_difference": first_rank_engine_diff,
            "numeric_error_vs_reference": {
                "production": prod_errors["summary"],
                "research": research_errors["summary"],
            },
            "witnesses": witnesses,
            "verdict": verdict,
        }

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    csv_path = args.output.with_suffix(".csv")
    prod_rows = {str(r["security_id"]): r for r in prod["ranking"]}
    research_rows = {str(r["security_id"]): r for r in research["ranking"]}
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        fields = [
            "security_id", "ticker", "reference_leadership_rank", "production_leadership_rank",
            "research_leadership_rank", "reference_durable_rank", "production_durable_rank",
            "research_durable_rank", "reference_momentum", "production_momentum", "research_momentum",
            "reference_recent", "production_recent", "research_recent", "reference_score",
            "production_score", "research_score",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for sid in ref_rank:
            writer.writerow({
                "security_id": sid,
                "ticker": tickers.get(sid),
                "reference_leadership_rank": ref_lead.index(sid) + 1,
                "production_leadership_rank": prod_lead_ids.index(sid) + 1,
                "research_leadership_rank": research_lead_ids.index(sid) + 1,
                "reference_durable_rank": ref_rank.index(sid) + 1,
                "production_durable_rank": prod_rank_ids.index(sid) + 1,
                "research_durable_rank": research_rank_ids.index(sid) + 1,
                "reference_momentum": str(reference[sid]["momentum"]),
                "production_momentum": prod_rows[sid]["momentum"],
                "research_momentum": research_rows[sid]["momentum"],
                "reference_recent": str(reference[sid]["recent"]),
                "production_recent": prod_rows[sid]["recent"],
                "research_recent": research_rows[sid]["recent"],
                "reference_score": str(reference[sid]["score"]),
                "production_score": prod_rows[sid]["score"],
                "research_score": research_rows[sid]["score"],
            })

    print(f"[ADJUDICATION] verdict={payload['verdict']}", flush=True)
    print("[ADJUDICATION ORDER] " + json.dumps(order_checks, sort_keys=True), flush=True)
    print("[ADJUDICATION NUMERIC ERROR] " + json.dumps(payload["numeric_error_vs_reference"], sort_keys=True), flush=True)
    for witness in witnesses:
        print("[ADJUDICATION WITNESS] " + json.dumps(witness, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
