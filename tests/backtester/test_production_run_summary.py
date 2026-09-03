from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path

import pytest

from backtester.production_run_summary import (
    build_summary,
    load_authenticated_ledger,
    load_metrics,
    render_markdown,
)
from backtester.production_year_checkpoint_overlay import hash_value


def _metrics(path: Path) -> None:
    fields = [
        "window_years", "variant", "start", "end", "sessions",
        "elapsed_years", "cagr", "sharpe", "max_drawdown",
    ]
    rows = []
    starts = {
        5: "2021-07-30",
        10: "2016-07-29",
        15: "2011-07-29",
        20: "2006-07-31",
    }
    for window in (5, 10, 15, 20):
        for variant in ("Production", "SPY"):
            rows.append(
                {
                    "window_years": window,
                    "variant": variant,
                    "start": starts[window],
                    "end": "2026-07-31",
                    "sessions": 1260 if window == 5 else 252 * window,
                    "elapsed_years": window,
                    "cagr": 0.2 if variant == "Production" else 0.1,
                    "sharpe": 1.5 if variant == "Production" else 0.8,
                    "max_drawdown": -0.25 if variant == "Production" else -0.4,
                }
            )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _checkpoint(path: Path, certificate: Path) -> None:
    events = [
        {"session": "2007-01-02", "event_type": "BUY"},
        {"session": "2012-01-03", "event_type": "SELL"},
        {"session": "2017-01-03", "event_type": "BUY"},
        {"session": "2022-01-03", "event_type": "SELL"},
        {"session": "2023-01-03", "event_type": "SPLIT"},
        {"session": "2024-01-03", "event_type": "CASH_MERGER"},
        {"session": "2025-01-03", "event_type": "BUY"},
    ]
    payload = {
        "states": {
            "production": {
                "state": {"ledger": {"events": events}},
                "state_hash": "a" * 64,
            }
        }
    }
    envelope = {
        "schema": "backtester.production-year-checkpoint/3",
        "format_generation": 3,
        "payload_sha256": hash_value(payload),
        "payload": payload,
    }
    path.write_text(json.dumps(envelope, sort_keys=True) + "\n", encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    certificate.write_text(
        json.dumps(
            {
                "status": "PASS",
                "year": 2026,
                "checkpoint": {"file_sha256": digest},
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_summary_uses_authenticated_executed_buy_sell_events_only(tmp_path: Path) -> None:
    metrics_path = tmp_path / "metrics.csv"
    checkpoint_path = tmp_path / "checkpoint.json"
    certificate_path = tmp_path / "certificate.json"
    _metrics(metrics_path)
    _checkpoint(checkpoint_path, certificate_path)

    metrics = load_metrics(metrics_path)
    events = load_authenticated_ledger(checkpoint_path, certificate_path)
    summary = build_summary(metrics, events)
    by_window = {row["window_years"]: row for row in summary["windows"]}

    assert by_window[5]["Production"]["executed_buys"] == 1
    assert by_window[5]["Production"]["executed_sells"] == 1
    assert by_window[10]["Production"]["executed_buys"] == 2
    assert by_window[10]["Production"]["executed_sells"] == 1
    assert by_window[15]["Production"]["executed_buys"] == 2
    assert by_window[15]["Production"]["executed_sells"] == 2
    assert by_window[20]["Production"]["executed_buys"] == 3
    assert by_window[20]["Production"]["executed_sells"] == 2
    assert "SPLIT" not in summary["trade_count_definition"]
    rendered = render_markdown(summary)
    assert "Production CAGR" in rendered
    assert "SPY Max DD" in rendered
    assert "| 20y " in rendered


def test_missing_required_window_fails_closed(tmp_path: Path) -> None:
    path = tmp_path / "metrics.csv"
    _metrics(path)
    rows = list(csv.DictReader(path.open()))
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=rows[0].keys(), lineterminator="\n")
        writer.writeheader()
        writer.writerows(
            row
            for row in rows
            if not (row["window_years"] == "15" and row["variant"] == "SPY")
        )
    with pytest.raises(RuntimeError, match="missing required windows"):
        load_metrics(path)


def test_tampered_checkpoint_is_rejected(tmp_path: Path) -> None:
    checkpoint = tmp_path / "checkpoint.json"
    certificate = tmp_path / "certificate.json"
    _checkpoint(checkpoint, certificate)
    value = json.loads(checkpoint.read_text())
    value["payload"]["states"]["production"]["state"]["ledger"]["events"][0][
        "event_type"
    ] = "SELL"
    checkpoint.write_text(json.dumps(value) + "\n")
    with pytest.raises(RuntimeError, match="differs from annual certificate"):
        load_authenticated_ledger(checkpoint, certificate)
