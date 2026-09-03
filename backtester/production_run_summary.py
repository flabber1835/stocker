#!/usr/bin/env python3
"""Render the authenticated Production/SPY 5/10/15/20-year result table."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path

from backtester.production_year_checkpoint_overlay import hash_value


SCHEMA = "backtester.production-20y-public-summary/1"
WINDOWS = (5, 10, 15, 20)
VARIANTS = ("Production", "SPY")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _finite(value, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"{label} is not numeric") from exc
    if not math.isfinite(number):
        raise RuntimeError(f"{label} is not finite")
    return number


def _window_number(value: object) -> int | None:
    text = str(value or "").strip().lower()
    if text == "max":
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    integer = int(number)
    return integer if number == integer else None


def load_metrics(path: Path) -> dict[tuple[int, str], dict]:
    with Path(path).open("r", encoding="utf-8", newline="") as handle:
        rows = [dict(row) for row in csv.DictReader(handle)]
    selected: dict[tuple[int, str], dict] = {}
    for row in rows:
        window = _window_number(row.get("window_years"))
        variant = str(row.get("variant") or "")
        if window not in WINDOWS or variant not in VARIANTS:
            continue
        key = (window, variant)
        if key in selected:
            raise RuntimeError(f"duplicate {window}y {variant} metric row")
        block = {
            "start": str(row.get("start") or ""),
            "end": str(row.get("end") or ""),
            "sessions": int(float(row.get("sessions") or 0)),
            "elapsed_years": _finite(row.get("elapsed_years"), f"{key} elapsed_years"),
            "cagr": _finite(row.get("cagr"), f"{key} CAGR"),
            "max_drawdown": _finite(
                row.get("max_drawdown"), f"{key} max drawdown"
            ),
            "sharpe": _finite(row.get("sharpe"), f"{key} Sharpe"),
        }
        if not block["start"] or not block["end"] or block["sessions"] < 2:
            raise RuntimeError(f"{window}y {variant} metric window is incomplete")
        selected[key] = block

    expected = {(window, variant) for window in WINDOWS for variant in VARIANTS}
    if set(selected) != expected:
        missing = sorted(expected - set(selected))
        raise RuntimeError(f"final metrics are missing required windows: {missing}")
    for window in WINDOWS:
        left = selected[(window, "Production")]
        right = selected[(window, "SPY")]
        if (left["start"], left["end"]) != (right["start"], right["end"]):
            raise RuntimeError(f"{window}y Production/SPY date windows differ")
    return selected


def load_authenticated_ledger(
    checkpoint_path: Path, certificate_path: Path
) -> list[dict]:
    certificate = json.loads(Path(certificate_path).read_text(encoding="utf-8"))
    if certificate.get("status") != "PASS" or int(certificate.get("year", 0)) != 2026:
        raise RuntimeError("final Production annual certificate is not PASS/2026")
    expected_checkpoint = str(
        (certificate.get("checkpoint") or {}).get("file_sha256") or ""
    )
    if sha256_file(checkpoint_path) != expected_checkpoint:
        raise RuntimeError("final checkpoint differs from annual certificate")

    envelope = json.loads(Path(checkpoint_path).read_text(encoding="utf-8"))
    if envelope.get("schema") != "backtester.production-year-checkpoint/3":
        raise RuntimeError("unexpected Production checkpoint schema")
    payload = envelope.get("payload")
    if not isinstance(payload, dict):
        raise RuntimeError("Production checkpoint payload is missing")
    if hash_value(payload) != envelope.get("payload_sha256"):
        raise RuntimeError("Production checkpoint payload hash mismatch")

    production = ((payload.get("states") or {}).get("production") or {}).get("state")
    ledger = (production or {}).get("ledger")
    events = (ledger or {}).get("events")
    if not isinstance(events, list):
        raise RuntimeError("authenticated Production ledger events are missing")
    normalized = []
    for index, event in enumerate(events):
        if not isinstance(event, dict):
            raise RuntimeError(f"ledger event {index} is not an object")
        session = str(event.get("session") or "")
        event_type = str(event.get("event_type") or "")
        if len(session) != 10 or not event_type:
            raise RuntimeError(f"ledger event {index} is incomplete")
        normalized.append(dict(event))
    return normalized


def _trade_counts(events: list[dict], start: str, end: str) -> tuple[int, int]:
    buys = sells = 0
    for event in events:
        session = str(event["session"])
        if not (start <= session <= end):
            continue
        event_type = str(event["event_type"])
        if event_type == "BUY":
            buys += 1
        elif event_type == "SELL":
            sells += 1
    return buys, sells


def build_summary(metrics: dict[tuple[int, str], dict], events: list[dict]) -> dict:
    rows = []
    for window in WINDOWS:
        production = dict(metrics[(window, "Production")])
        spy = dict(metrics[(window, "SPY")])
        buys, sells = _trade_counts(events, production["start"], production["end"])
        rows.append(
            {
                "window_years": window,
                "start": production["start"],
                "end": production["end"],
                "Production": {
                    **production,
                    "executed_buys": buys,
                    "executed_sells": sells,
                },
                "SPY": spy,
            }
        )
    return {
        "schema": SCHEMA,
        "trade_count_definition": (
            "count authenticated Wealth Core ledger events whose event_type is "
            "exactly BUY or SELL; corporate actions are not trades"
        ),
        "windows": rows,
    }


def render_markdown(summary: dict) -> str:
    lines = [
        "## Production 20-year backtest results",
        "",
        "| Window | Production CAGR | Production Max DD | Production Sharpe | Buys | Sells | SPY CAGR | SPY Max DD | SPY Sharpe |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary["windows"]:
        p = row["Production"]
        s = row["SPY"]
        lines.append(
            f"| {row['window_years']}y "
            f"| {p['cagr']:.2%} | {p['max_drawdown']:.2%} | {p['sharpe']:.2f} "
            f"| {p['executed_buys']} | {p['executed_sells']} "
            f"| {s['cagr']:.2%} | {s['max_drawdown']:.2%} | {s['sharpe']:.2f} |"
        )
    lines.extend(
        [
            "",
            "Buy/sell counts are executed Production ledger events only; splits, dividends, conversions, cash mergers, and write-offs are excluded.",
            "",
        ]
    )
    return "\n".join(lines)


def write_outputs(summary: dict, output_root: Path) -> tuple[Path, Path, Path]:
    output_root.mkdir(parents=True, exist_ok=True)
    json_path = output_root / "production-20y-summary.json"
    csv_path = output_root / "production-20y-summary.csv"
    md_path = output_root / "production-20y-summary.md"
    json_path.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        fieldnames = [
            "window_years",
            "start",
            "end",
            "production_cagr",
            "production_max_drawdown",
            "production_sharpe",
            "executed_buys",
            "executed_sells",
            "spy_cagr",
            "spy_max_drawdown",
            "spy_sharpe",
        ]
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        for row in summary["windows"]:
            p = row["Production"]
            s = row["SPY"]
            writer.writerow(
                {
                    "window_years": row["window_years"],
                    "start": row["start"],
                    "end": row["end"],
                    "production_cagr": p["cagr"],
                    "production_max_drawdown": p["max_drawdown"],
                    "production_sharpe": p["sharpe"],
                    "executed_buys": p["executed_buys"],
                    "executed_sells": p["executed_sells"],
                    "spy_cagr": s["cagr"],
                    "spy_max_drawdown": s["max_drawdown"],
                    "spy_sharpe": s["sharpe"],
                }
            )
    markdown = render_markdown(summary)
    md_path.write_text(markdown, encoding="utf-8")
    return json_path, csv_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--metrics", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--certificate", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--github-summary", type=Path)
    args = parser.parse_args()

    metrics = load_metrics(args.metrics)
    events = load_authenticated_ledger(args.checkpoint, args.certificate)
    summary = build_summary(metrics, events)
    _json_path, _csv_path, md_path = write_outputs(summary, args.output_root)
    rendered = md_path.read_text(encoding="utf-8")
    print(rendered, flush=True)
    github_summary = args.github_summary
    if github_summary is None and os.environ.get("GITHUB_STEP_SUMMARY"):
        github_summary = Path(os.environ["GITHUB_STEP_SUMMARY"])
    if github_summary is not None:
        with Path(github_summary).open("a", encoding="utf-8") as handle:
            handle.write(rendered)
            if not rendered.endswith("\n"):
                handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
