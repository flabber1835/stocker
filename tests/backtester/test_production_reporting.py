from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
import pytest

# Pytest imports this directory as the top-level ``backtester`` package. Extend
# that package's search path to the repository's runner sources without loading
# the strict wrapper or any canonical dataset.
import backtester as _test_package

_RUNNER_PACKAGE = str(Path(__file__).resolve().parents[2] / "backtester")
if _RUNNER_PACKAGE not in _test_package.__path__:
    _test_package.__path__.append(_RUNNER_PACKAGE)

import backtester.run_ldrc_nonpit_vs_pit_certified as reporting
import backtester.run_production_strict_pit_certification as strict_reporting


def _metric_block(multiplier: float) -> dict:
    return {
        "start": "2006-07-31",
        "end": "2026-07-31",
        "sessions": 5000,
        "elapsed_years": 20.0,
        "cagr": multiplier ** (1.0 / 20.0) - 1.0,
        "sharpe": 1.0,
        "max_drawdown": -0.2,
        "ending_multiple": multiplier,
    }


def _failure_state():
    return SimpleNamespace(
        last_processed_session="2008-02-04",
        last_evidence={
            "wealth_core": {
                "estimated_equity": 101.0,
                "resolved_open_equity": None,
                "open_unresolved_security_ids": ["sid-z", "sid-a", "sid-z"],
                "hashes": {"state": "abc123"},
            }
        },
        wealth_core={
            "episodes": {
                "7": {
                    "security_id": "sid-z",
                    "ticker": "OLD",
                    "entry_date": "2007-09-01",
                    "source_lots": [
                        {"kind": "ADMISSION", "session": "2007-09-01"},
                        {"kind": "CONVERSION", "session": "2008-01-31"},
                    ],
                },
                "2": {
                    "security_id": "held-but-resolved",
                    "ticker": "OK",
                    "source_lots": [],
                },
            },
            "unresolved_terminals": {"sid-z": "missing raw open"},
            "terminal_pending_sessions": {"sid-z": 2},
            "terminal_pending_terms": {"sid-z": {"kind": "CASH"}},
            "terminal_carry_audit": {"sid-z": {"source": "frozen"}},
            "sessions_since_valid_mark": {"sid-z": 2},
            "last_valid_mark_session": {"sid-z": "2008-01-31"},
        },
        feed={
            "series": {
                "sid-z": {
                    "security_id": "sid-z",
                    "ticker": "NEW",
                    "issuer_id": "SEC_CIK:42",
                    "split_factor": 2.0,
                    "sessions": ["2008-01-31"],
                }
            }
        },
        last_known={"sid-z": 36.5},
        pending=[
            {"security_id": "sid-z", "side": "EXIT"},
            {"security_id": "other", "side": "ENTRY"},
        ],
        last_decision={"target_core_exposure": 0.2},
        strategy_identity={"strategy": "production", "wealth_core_source_sha256": "w"},
    )


def _account():
    return SimpleNamespace(
        name="B",
        nav=1.25,
        effective=1.0,
        pending=0.2,
        initialized=True,
        transitions=4,
        transition_cost=0.001,
    )


def test_canonical_axis_builds_quarter_end_and_segment_end_checkpoints():
    sessions = [
        "2006-07-31",
        "2006-09-29",
        "2006-10-02",
        "2006-12-29",
        "2007-01-03",
        "2007-02-02",
    ]
    assert reporting._calendar_checkpoint_sessions(
        sessions, "2006-07-31", "2007-02-02"
    ) == {"2006-09-29", "2006-12-29", "2007-02-02"}


def test_measurement_cagr_is_anchored_at_the_post_reset_multiple():
    assert reporting._measurement_cagr(1.0, "2006-07-31", "2006-07-31") == 0.0
    expected = 1.21 ** (
        1.0 / ((pd.Timestamp("2008-07-31") - pd.Timestamp("2006-07-31")).days / 365.2425)
    ) - 1.0
    assert reporting._measurement_cagr(
        1.21, "2006-07-31", "2008-07-31"
    ) == pytest.approx(expected)


def test_max_metric_block_excludes_warmup_before_nav_reset(monkeypatch):
    monkeypatch.setattr(reporting.base.runner, "END_SESSION", "2008-07-31")
    frame = pd.DataFrame({
        "date": ["2006-01-03", "2006-07-31", "2007-07-31", "2008-07-31"],
        "Production_nav": [9.0, 1.0, 1.1, 1.21],
    })
    block = reporting._max_metric_block(
        frame, "Production_nav", "2006-07-31"
    )
    assert block["start"] == "2006-07-31"
    assert block["sessions"] == 3
    assert block["ending_multiple"] == pytest.approx(1.21)


def test_progress_counter_advances_once_per_completed_production_session():
    owner = SimpleNamespace(_progress_sessions=252)
    assert reporting._increment_production_progress(owner) == 253
    assert owner._progress_sessions == 253


def test_public_run_logs_hide_all_internal_account_designations(capsys):
    reporting._production_runner_print(
        "[RUN] 2008-01-04 sessions=505 A=1.000000 B=1.235559"
    )
    reporting._production_layer_print(
        "[PROGRESS] session=2008-03-31 sessions=563 from=2006-07-31 "
        "A_multiple=1.000000 A_cagr=0.000000% "
        "D_multiple=1.041365 D_cagr=2.460675%"
    )
    output = capsys.readouterr().out
    assert "Production=1.235559" in output
    assert "role=Production multiple=1.041365 cumulative_cagr=2.460675%" in output
    assert not any(marker in output for marker in (" A=", " B=", " D=", "A_multiple", "D_multiple"))


def test_failure_context_binds_unresolved_ids_to_episode_source_lots():
    payload = reporting._production_failure_payload(
        _failure_state(),
        _account(),
        core_open=None,
        core_close=101.0,
        prior_core_close=100.0,
        bil_gap=1.001,
        bil_intraday=1.0001,
        next_target=0.2,
    )

    assert payload["status"] == "FAIL_CLOSED"
    assert payload["session"] == "2008-02-04"
    assert payload["open_unresolved_security_ids"] == ["sid-a", "sid-z"]
    assert [row["security_id"] for row in payload["held_episodes"]] == ["sid-z"]
    held = payload["held_episodes"][0]
    assert [lot["kind"] for lot in held["source_lots"]] == [
        "ADMISSION", "CONVERSION"
    ]
    assert held["feed_source_identity"] == {
        "issuer_id": "SEC_CIK:42",
        "security_id": "sid-z",
        "split_factor": 2.0,
        "ticker": "NEW",
    }
    assert payload["terminal_state"]["unresolved_terminals"] == {
        "sid-z": "missing raw open"
    }
    assert payload["account"]["role"] == "Production"
    assert payload["account"]["transition_required"] is True
    assert payload["core_values"]["resolved_open_equity"] is None
    assert payload["source_identities"]["wealth_core_hashes"] == {
        "state": "abc123"
    }


def test_actual_internal_guard_writes_stable_context_and_raises_production_error(
    monkeypatch, tmp_path
):
    state = _failure_state()
    account = _account()
    context_path = tmp_path / "failure.json"
    monkeypatch.setenv("PRODUCTION_FAILURE_CONTEXT_PATH", str(context_path))
    monkeypatch.setattr(reporting, "_latest_pit_state", state)
    monkeypatch.setattr(reporting, "_pit_prior_core_close", 100.0)
    monkeypatch.setattr(
        reporting.base.runner, "wealth_equities", lambda _state: (None, 101.0)
    )

    def fail_closed(*_args, **_kwargs):
        raise RuntimeError(
            "B allocation transition coincides with unresolved Wealth Core open; "
            "exact next-open attribution is impossible"
        )

    monkeypatch.setattr(reporting, "_real_raw_overlay_step", fail_closed)
    with pytest.raises(RuntimeError, match="Production allocation transition") as caught:
        reporting._raw_overlay_step_fullstack(
            account, None, 101.0, 100.0, 1.001, 1.0001, 0.2
        )
    assert "sid-a,sid-z" in str(caught.value)
    assert caught.value.__suppress_context__ is True
    first = context_path.read_bytes()
    payload = json.loads(first)
    reporting._write_production_failure_context(payload)
    assert context_path.read_bytes() == first


def test_failure_context_write_error_is_not_hidden(monkeypatch):
    monkeypatch.setattr(reporting, "_latest_pit_state", _failure_state())
    monkeypatch.setattr(reporting, "_pit_prior_core_close", 100.0)
    monkeypatch.setattr(
        reporting.base.runner, "wealth_equities", lambda _state: (None, 101.0)
    )
    monkeypatch.setattr(
        reporting,
        "_real_raw_overlay_step",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError(reporting.UNRESOLVED_OPEN_TRANSITION_MARKER)
        ),
    )
    monkeypatch.setattr(
        reporting,
        "_write_production_failure_context",
        lambda _payload: (_ for _ in ()).throw(OSError("read-only evidence path")),
    )
    with pytest.raises(OSError, match="read-only evidence path"):
        reporting._raw_overlay_step_fullstack(
            _account(), None, 101.0, 100.0, 1.001, 1.0001, 0.2
        )


def test_public_daily_has_only_production_and_benchmark_columns():
    raw = pd.DataFrame({
        "date": ["2006-07-31"],
        "A_nav": [1.0],
        "D_nav": [1.2],
        "SPY_level": [1.1],
        "wealth_core_equity": [100_000.0],
        "A_allocation": [1.0],
        "D_allocation": [0.2],
        "D_ranking_count": [25],
        "green": [0.5],
    })
    public = reporting._public_production_daily(raw)
    assert public.loc[0, "Production_nav"] == 1.2
    assert public.loc[0, "Production_allocation"] == 0.2
    assert public.loc[0, "Production_ranking_count"] == 25
    assert set(public.columns) == {
        "date", "Production_nav", "Production_allocation",
        "Production_ranking_count", "SPY_level",
    }
    assert not any(column.startswith(("A_", "B_", "D_")) for column in public)


def test_public_metrics_and_summary_filter_the_legacy_control():
    raw = pd.DataFrame([
        {"window_years": "5", "variant": "A", "cagr": 0.0},
        {"window_years": "5", "variant": "D", "cagr": 0.2},
        {"window_years": "5", "variant": "SPY", "cagr": 0.1},
        {"window_years": "max", "variant": "D", "cagr": 999.0},
    ])
    blocks = {
        "Production": _metric_block(4.0),
        "SPY": _metric_block(3.0),
    }
    public = reporting._public_production_metrics(raw, blocks)
    assert set(public["variant"]) == {"Production", "SPY"}
    assert len(public[public["window_years"].astype(str).eq("max")]) == 2

    summary = reporting._public_metric_summary({
        "5": {
            "A": {"cagr": 0.0},
            "D": {"cagr": 0.2},
            "SPY": {"cagr": 0.1},
        }
    }, blocks)
    assert set(summary["5"]) == {"Production", "SPY"}
    assert set(summary["max"]) == {"Production", "SPY"}


def test_final_bundle_is_publicly_production_only_and_rehashes_outputs(
    monkeypatch, tmp_path
):
    dates = ["2006-07-31", "2007-07-31", "2008-07-31"]
    daily = pd.DataFrame({
        "date": dates,
        "A_nav": [1.0, 1.0, 1.0],
        "D_nav": [1.0, 1.1, 1.21],
        "SPY_level": [1.0, 1.05, 1.1025],
        "wealth_core_equity": [100.0, 100.0, 100.0],
        "A_allocation": [1.0, 1.0, 1.0],
        "D_allocation": [1.0, 0.2, 0.2],
        "green": [0.1, 0.2, 0.3],
    })
    daily.to_csv(
        tmp_path / "daily.csv.gz",
        index=False,
        compression={"method": "gzip", "compresslevel": 6, "mtime": 0},
    )
    pd.DataFrame([
        {
            "window_years": "5", "variant": label,
            "start": dates[0], "end": dates[-1], "sessions": 3,
            "cagr": cagr, "sharpe": 1.0, "max_drawdown": -0.1,
            "ending_multiple": multiple,
        }
        for label, cagr, multiple in (
            ("A", 0.0, 1.0), ("D", 0.1, 1.21), ("SPY", 0.05, 1.1025)
        )
    ]).to_csv(tmp_path / "metrics.csv", index=False)
    (tmp_path / "summary.json").write_text(json.dumps({
        "metrics": {
            "5": {
                "A": {"cagr": 0.0},
                "D": {"cagr": 0.1},
                "SPY": {"cagr": 0.05},
            }
        },
        "transitions": {"A": 0, "D": 2},
        "transition_cost_sum": {"A": 0.0, "D": 0.001},
        "d_pit_semantics": {"wealth_core_path": "legacy comparison"},
    }) + "\n", encoding="utf-8")
    (tmp_path / "manifest.json").write_text(json.dumps({
        "schema": "backtester.experiment-manifest/1",
        "outputs": {},
    }) + "\n", encoding="utf-8")

    monkeypatch.setattr(reporting.base, "OUTPUT", tmp_path)
    monkeypatch.setattr(reporting.base.runner, "END_SESSION", dates[-1])
    monkeypatch.setattr(reporting, "_pit_core_by_session", {
        session: (100.0 + index, 101.0 + index)
        for index, session in enumerate(dates)
    })
    reporting._write_final_comparison()
    first_sums = (tmp_path / "SHA256SUMS.txt").read_bytes()
    # The corrected wrapper finalizes once before and once after measurement
    # trimming. Public naming and hashes must therefore be idempotent.
    reporting._write_final_comparison()
    assert (tmp_path / "SHA256SUMS.txt").read_bytes() == first_sums

    public_daily = pd.read_csv(tmp_path / "daily.csv.gz", compression="gzip")
    assert "Production_nav" in public_daily
    assert "Production_wealth_core_equity" in public_daily
    assert not any(
        column.startswith(("A_", "B_", "D_")) for column in public_daily
    )
    public_metrics = pd.read_csv(tmp_path / "metrics.csv")
    assert set(public_metrics["variant"]) == {"Production", "SPY"}
    public_summary = json.loads((tmp_path / "summary.json").read_text())
    assert set(public_summary["metrics"]["5"]) == {"Production", "SPY"}
    assert set(public_summary["metrics"]["max"]) == {"Production", "SPY"}
    assert public_summary["transitions"] == {"Production": 2}
    assert "d_pit_semantics" not in public_summary

    def keys(value):
        if isinstance(value, dict):
            for key, child in value.items():
                yield str(key)
                yield from keys(child)
        elif isinstance(value, list):
            for child in value:
                yield from keys(child)

    assert not any(
        key in {"A", "B", "D"} or key.startswith(("A_", "B_", "D_"))
        for key in keys(public_summary)
    )

    manifest = json.loads((tmp_path / "manifest.json").read_text())
    for name in ("daily.csv.gz", "metrics.csv", "summary.json"):
        path = tmp_path / name
        assert manifest["outputs"][name] == {
            "sha256": reporting.base._sha256(path),
            "bytes": path.stat().st_size,
        }
    sums = (tmp_path / "SHA256SUMS.txt").read_text()
    assert f"{reporting.base._sha256(tmp_path / 'manifest.json')}  manifest.json" in sums


def test_strict_finalizer_removes_stale_calendar_cagr_fields():
    source = (
        Path(__file__).resolve().parents[2]
        / "backtester"
        / "run_production_strict_pit_certification.py"
    ).read_text(encoding="utf-8")
    assert 'summary.pop("calendar_year_cagr_checkpoints", None)' in source
    assert 'summary.pop("calendar_year_cagr_definition", None)' in source
    assert 'summary["cumulative_production_cagr_definition"]' in source
    assert "legacy CAGR reporting fields survived Production finalization" in source


def test_authenticated_phrm_terms_replace_only_the_incomplete_canonical_event(
    monkeypatch,
):
    incomplete = strict_reporting.TerminalTerms(
        session="2008-03-07",
        security_id="705177744622024105",
        kind=strict_reporting.TerminalKind.CASH_MERGER,
        reference="incomplete canonical vendor event",
    )
    replacement = strict_reporting.TerminalTerms(
        session="2008-03-07",
        security_id="705177744622024105",
        kind=strict_reporting.TerminalKind.CASH_PLUS_STOCK,
        cash_per_share=25.0,
        delivered_security_id="11651249425833422",
        delivered_ticker="CELG",
        delivered_issuer_id="SEC_CIK:816284",
        exchange_ratio=0.8367,
        cash_in_lieu_price_per_delivered_share=56.17,
        reference="authenticated PHRM/CELG terms",
    )
    monkeypatch.setattr(
        strict_reporting,
        "_canonical_terminal_terms",
        lambda _dataset: {"2008-03-07": (incomplete,)},
    )
    monkeypatch.setattr(
        strict_reporting,
        "load_frozen_terminal_terms",
        lambda *_args, **_kwargs: (
            {"2008-03-07": (replacement,)}, "a" * 64
        ),
    )

    class Dataset:
        sessions = ("2008-03-07",)

        def base_metadata(self, _meta_type):
            return (
                {"11651249425833422": object()},
                {},
                SimpleNamespace(resolve=lambda _ticker, _session: "unused"),
                {},
            )

        def metadata_for(self, _security_id, _session):
            return {
                "issuer_id": "SEC_CIK:816284",
                "issuer_source": "SEC_CIK_STRICT_PRIOR",
            }

    terms = strict_reporting._terminal_terms_with_authenticated_corrections(Dataset())
    corrected = terms["2008-03-07"][0]
    assert corrected == replacement
    assert corrected.completeness(1) == (True, "")
    audit = strict_reporting._terminal_correction_audit
    assert audit["source_sha256"] == "a" * 64
    assert audit["applied"][0]["original_incomplete_reason"] == (
        "MISSING_CASH_PER_SHARE"
    )
