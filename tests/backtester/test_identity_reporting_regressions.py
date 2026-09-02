from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd
import pytest

from backtester.production_public_reporting import (
    public_metric_summary,
    public_production_metrics,
)
from backtester.strict_pit_metadata import (
    audit_cik_identity_boundaries,
    build_causal_metadata,
)


@dataclass(frozen=True)
class SecurityMeta:
    security_id: str
    ticker: str
    category: str | None = None
    permaticker: str | None = None
    related_tickers: tuple[str, ...] = ()
    first_session: str | None = None
    last_session: str | None = None
    exchange: str | None = None
    exchange_authoritative: bool = False


def _write_sep(root: Path, rows: list[dict]) -> Path:
    target = root / "sharadar"
    target.mkdir(parents=True, exist_ok=True)
    path = target / "SHARADAR_SEP_2007.csv.gz"
    pd.DataFrame(rows).to_csv(path, index=False, compression="gzip")
    return target


def _write_cik(root: Path, rows: list[dict]) -> Path:
    path = root / "cik.csv.gz"
    pd.DataFrame(rows).to_csv(path, index=False, compression="gzip")
    return path


def test_mls_cik_flips_do_not_split_continuous_security(tmp_path: Path):
    sharadar = _write_sep(tmp_path, [
        {"ticker": "SPY", "date": "2007-02-07"},
        {"ticker": "MLS", "date": "2007-02-07"},
        {"ticker": "SPY", "date": "2007-02-08"},
        {"ticker": "MLS", "date": "2007-02-08"},
        {"ticker": "SPY", "date": "2007-03-29"},
        {"ticker": "MLS", "date": "2007-03-29"},
        {"ticker": "SPY", "date": "2007-03-30"},
        {"ticker": "MLS", "date": "2007-03-30"},
    ])
    cik = _write_cik(tmp_path, [
        {"filing_date": "2007-01-02", "ticker": "MLS", "issuer_cik": 914713},
        {"filing_date": "2007-02-07", "ticker": "MLS", "issuer_cik": 745981},
        {"filing_date": "2007-03-29", "ticker": "MLS", "issuer_cik": 914713},
        {"filing_date": "2007-01-02", "ticker": "SPY", "issuer_cik": 884394},
    ])

    meta, _sectors, resolver, _canonical, audit = build_causal_metadata(
        sharadar_root=sharadar,
        cik_path=cik,
        SecurityMeta=SecurityMeta,
        start_year=2007,
        end_year=2007,
    )
    mls_ids = [sid for sid, row in meta.items() if row.ticker == "MLS"]
    assert len(mls_ids) == 1
    assert resolver.resolve("MLS", "2007-02-07") == mls_ids[0]
    assert resolver.resolve("MLS", "2007-02-08") == mls_ids[0]
    assert resolver.resolve("MLS", "2007-03-30") == mls_ids[0]
    assert audit["raw_cik_change_evidence_events"] == 2
    assert audit["cik_changes_continuous_tape_rejected"] == 2
    assert audit["cik_change_episode_boundaries"] == 0
    assert audit["blocking_identity_conflicts"] == 0


def test_unexplained_cik_change_across_price_gap_fails_closed(tmp_path: Path):
    sharadar = _write_sep(tmp_path, [
        {"ticker": "SPY", "date": "2007-01-02"},
        {"ticker": "GAP", "date": "2007-01-02"},
        {"ticker": "SPY", "date": "2007-01-03"},
        {"ticker": "GAP", "date": "2007-01-03"},
        {"ticker": "SPY", "date": "2007-01-04"},
        {"ticker": "SPY", "date": "2007-01-05"},
        {"ticker": "SPY", "date": "2007-01-08"},
        {"ticker": "GAP", "date": "2007-01-08"},
    ])
    cik = _write_cik(tmp_path, [
        {"filing_date": "2007-01-01", "ticker": "GAP", "issuer_cik": 100},
        {"filing_date": "2007-01-04", "ticker": "GAP", "issuer_cik": 200},
    ])
    records, audit = audit_cik_identity_boundaries(
        sharadar_root=sharadar,
        cik_path=cik,
        start_year=2007,
        end_year=2007,
    )
    assert audit["cik_changes_unresolved_gap_conflicts"] == 1
    assert records[0]["disposition"] == "UNRESOLVED_CIK_GAP_CONFLICT"
    with pytest.raises(RuntimeError, match="identity cannot be certified"):
        build_causal_metadata(
            sharadar_root=sharadar,
            cik_path=cik,
            SecurityMeta=SecurityMeta,
            start_year=2007,
            end_year=2007,
        )


def test_terminal_evidence_corroborates_new_episode_after_gap(tmp_path: Path):
    sharadar = _write_sep(tmp_path, [
        {"ticker": "SPY", "date": "2007-01-02"},
        {"ticker": "OLD", "date": "2007-01-02"},
        {"ticker": "SPY", "date": "2007-01-03"},
        {"ticker": "OLD", "date": "2007-01-03"},
        {"ticker": "SPY", "date": "2007-01-04"},
        {"ticker": "SPY", "date": "2007-01-05"},
        {"ticker": "SPY", "date": "2007-01-08"},
        {"ticker": "OLD", "date": "2007-01-08"},
    ])
    cik = _write_cik(tmp_path, [
        {"filing_date": "2007-01-01", "ticker": "OLD", "issuer_cik": 100},
        {"filing_date": "2007-01-04", "ticker": "OLD", "issuer_cik": 200},
    ])
    actions = tmp_path / "PIT input data"
    actions.mkdir(parents=True)
    pd.DataFrame([{
        "date": "2007-01-03", "action": "delisted", "ticker": "OLD"
    }]).to_csv(actions / "ACTIONS_PIT_ONLY.csv.gz", index=False, compression="gzip")

    meta, _sectors, resolver, _canonical, audit = build_causal_metadata(
        sharadar_root=sharadar,
        cik_path=cik,
        SecurityMeta=SecurityMeta,
        start_year=2007,
        end_year=2007,
    )
    ids = [sid for sid, row in meta.items() if row.ticker == "OLD"]
    assert len(ids) == 2
    assert resolver.resolve("OLD", "2007-01-03") == ids[0]
    assert resolver.resolve("OLD", "2007-01-08") == ids[1]
    assert ids[1] > ids[0]
    assert audit["cik_change_episode_boundaries"] == 1
    assert audit["blocking_identity_conflicts"] == 0


def test_partial_genesis_window_is_not_labeled_one_year():
    raw = pd.DataFrame([
        {
            "window_years": "1", "variant": "D",
            "start": "2006-07-31", "end": "2006-12-29", "cagr": 0.13727,
        },
        {
            "window_years": "1", "variant": "SPY",
            "start": "2006-07-31", "end": "2006-12-29", "cagr": 0.13844,
        },
    ])
    max_blocks = {
        "Production": {
            "start": "2006-07-31", "end": "2006-12-29",
            "elapsed_years": 151 / 365.2425, "ending_multiple": 1.13727,
        },
        "SPY": {
            "start": "2006-07-31", "end": "2006-12-29",
            "elapsed_years": 151 / 365.2425, "ending_multiple": 1.13844,
        },
    }
    public = public_production_metrics(raw, max_blocks)
    assert set(public["window_years"].astype(str)) == {"max"}

    summary = public_metric_summary({
        "1": {
            "D": dict(raw.iloc[0]),
            "SPY": dict(raw.iloc[1]),
        }
    }, max_blocks)
    assert set(summary) == {"max"}
    assert summary["max"]["Production"]["elapsed_years"] < 0.5


def test_complete_nominal_one_year_window_is_retained():
    raw = pd.DataFrame([
        {
            "window_years": "1", "variant": "D",
            "start": "2006-07-31", "end": "2007-07-31", "cagr": 0.22,
        },
        {
            "window_years": "1", "variant": "SPY",
            "start": "2006-07-31", "end": "2007-07-31", "cagr": 0.1811,
        },
    ])
    max_blocks = {
        "Production": {"start": "2006-07-31", "end": "2007-07-31", "elapsed_years": 1.0},
        "SPY": {"start": "2006-07-31", "end": "2007-07-31", "elapsed_years": 1.0},
    }
    public = public_production_metrics(raw, max_blocks)
    assert set(public["window_years"].astype(str)) == {"1", "max"}


def test_same_day_cik_oscillation_is_audited_and_never_splits_identity(tmp_path: Path):
    sharadar = _write_sep(tmp_path, [
        {"ticker": "SPY", "date": "2007-02-07"},
        {"ticker": "OSC", "date": "2007-02-07"},
        {"ticker": "SPY", "date": "2007-02-08"},
        {"ticker": "OSC", "date": "2007-02-08"},
    ])
    cik = _write_cik(tmp_path, [
        {"filing_date": "2007-01-02", "ticker": "OSC", "issuer_cik": 100},
        {"filing_date": "2007-02-07", "ticker": "OSC", "issuer_cik": 200},
        {"filing_date": "2007-02-07", "ticker": "OSC", "issuer_cik": 100},
    ])

    meta, _sectors, resolver, _canonical, audit = build_causal_metadata(
        sharadar_root=sharadar,
        cik_path=cik,
        SecurityMeta=SecurityMeta,
        start_year=2007,
        end_year=2007,
    )
    ids = [sid for sid, row in meta.items() if row.ticker == "OSC"]
    assert len(ids) == 1
    assert resolver.resolve("OSC", "2007-02-08") == ids[0]
    assert audit["raw_cik_change_evidence_events"] == 1
    assert audit["cik_changes_same_day_oscillation_rejected"] == 1
