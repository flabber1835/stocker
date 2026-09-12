from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
PATH = ROOT / "tools" / "production_go_e2e_harness.py"
SPEC = importlib.util.spec_from_file_location("production_go_e2e_harness", PATH)
assert SPEC is not None and SPEC.loader is not None
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)


def test_script_process_can_load_production_session_calendar(tmp_path):
    env = dict(os.environ, PYTHONPATH=str(ROOT / "shared"))
    completed = subprocess.run(
        [sys.executable, "-c",
         "import runpy,sys; h=runpy.run_path(sys.argv[1]); "
         "assert len(h['_session_days']()) >= 252", str(PATH)],
        cwd=tmp_path, env=env, text=True, capture_output=True, timeout=30,
        check=False,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr


def test_canonical_entrypoint_is_real_production_go():
    assert harness.ENTRYPOINT == ("bash", "scripts/sentinel-go-validate.sh")
    assert harness.REQUIRED_PHASES[-3:] == (
        "CERTIFICATION + FINANCIAL READINESS",
        "PROMOTE EXACT CERTIFIED RUNTIME",
        "POST-VALIDATION HANDOFF",
    )


def test_fixture_pages_satisfy_consumed_sharadar_protocol():
    required = {
        "SEP": {"ticker", "date", "open", "close", "closeunadj", "volume", "lastupdated"},
        "SFP": {"ticker", "date", "open", "close", "closeadj", "closeunadj"},
        "ACTIONS": {"date", "action", "ticker", "name", "value", "contraticker", "contraname"},
        "TICKERS": {"table", "permaticker", "ticker", "category", "relatedtickers",
                    "firstpricedate", "lastpricedate", "sector", "isdelisted", "exchange"},
    }
    day = harness._latest_closed_session().isoformat()
    for table in required:
        page = harness._payload(table, {"date": [day]})
        names = [item["name"] for item in page["datatable"]["columns"]]
        assert required[table].issubset(names)
        assert page["meta"] == {"next_cursor_id": None}
        assert all(len(row) == len(names) for row in page["datatable"]["data"])


def test_fixture_supplies_seed_reference_tickers():
    page = harness._payload("SFP", {"ticker": ["SPY,BIL"]})
    assert {row[0] for row in page["datatable"]["data"]} == {"SPY", "BIL"}


def test_fixture_is_large_enough_for_readiness_history():
    page = harness._payload("SEP", {"ticker": ["SPY"]})
    by_spy = [row for row in page["datatable"]["data"] if row[0] == "SPY"]
    assert len(by_spy) >= 252
    assert len({row[1] for row in by_spy}) >= 252


def test_fixture_supports_the_current_cash_adjudication_migration(monkeypatch):
    import datetime as dt
    from decimal import Decimal
    from sentinel.feed import actions, actions_reconcile_v7
    monkeypatch.setattr(harness, "_session_days", lambda: tuple(
        dt.date(2026, 5, day) for day in (1, 4, 5)))
    payload = harness._payload("ACTIONS", {})["datatable"]
    columns = [item["name"] for item in payload["columns"]]
    rows = [{**dict(zip(columns, row)), "source_row_id": f"fixture-source-{i}"}
            for i, row in enumerate(payload["data"])]
    monkeypatch.setattr(actions, "active_rows", lambda *_a, **_k: rows)

    class Connection:
        def cursor(self):
            return self
        def __enter__(self):
            return self
        def __exit__(self, *_args):
            pass
        def execute(self, sql, params):
            assert params[:2] == ("TRI", "2026-05-04")
        def fetchall(self):
            return [("fixture-TRI", Decimal("1.435518"))]

    audit = actions_reconcile_v7._cash_adjudication_audit(
        Connection(), run_id="fixture", dates=["2026-05-04"],
        windows=[("2026-05-01", "2026-05-05")])
    assert len(audit) == 1
    assert audit[0]["source_amount"] == "1.36"
    assert audit[0]["normalized_bar_dividend_per_share"] == "1.435518"
    assert "TRI" in harness.TICKERS
    assert len(harness.TICKERS) == 4_000


def test_compose_propagates_sharadar_transport_with_safe_defaults():
    compose = (ROOT / "docker-compose.sentinel.yml").read_text(encoding="utf-8")
    assert "NDL_BASE_URL: ${NDL_BASE_URL:-https://data.nasdaq.com/api/v3/datatables/SHARADAR}" in compose
    assert "SHARADAR_ALLOW_INSECURE_BASE_URL: ${SHARADAR_ALLOW_INSECURE_BASE_URL:-0}" in compose
    assert "SHARADAR_FETCH_RETRIES: ${SHARADAR_FETCH_RETRIES:-6}" in compose
    assert "SHARADAR_FETCH_BACKOFF: ${SHARADAR_FETCH_BACKOFF:-2.0}" in compose


def test_phase_parser_is_stage_sensitive():
    output = "\n=== HOST COMPATIBILITY ===\n[GO] ok\n=== RUNTIME SELECTION PREFLIGHT ===\n"
    assert harness._phase_names(output) == [
        "HOST COMPATIBILITY", "RUNTIME SELECTION PREFLIGHT"
    ]


@pytest.mark.parametrize("missing", ["NDL_BASE_URL", "SHARADAR_ALLOW_INSECURE_BASE_URL",
                                     "SHARADAR_FETCH_RETRIES", "SHARADAR_FETCH_BACKOFF"])
def test_fixture_refuses_dropped_container_transport_setting(missing):
    expected = {"NDL_BASE_URL": "http://127.0.0.1:8000",
                "SHARADAR_ALLOW_INSECURE_BASE_URL": "1",
                "SHARADAR_FETCH_RETRIES": "1", "SHARADAR_FETCH_BACKOFF": "0"}
    actual = dict(expected)
    harness._require_local_source({"services": {"sentinel": {"environment": actual}}}, expected)
    actual.pop(missing)
    with pytest.raises(harness.HarnessFailure, match="local Sharadar"):
        harness._require_local_source({"services": {"sentinel": {"environment": actual}}}, expected)


def test_real_source_membrane_consumes_local_pages_and_complete_exports(monkeypatch):
    import httpx
    from types import SimpleNamespace
    from sentinel.feed import sharadar, snapshot_export, snapshot_source, source_authority
    monkeypatch.setenv("SHARADAR_API_KEY", "e2e-sharadar-key")
    monkeypatch.setattr(sharadar, "ALLOW_INSECURE_BASE_URL", True)
    monkeypatch.setattr(sharadar, "FETCH_MAX_RETRIES", 1)
    monkeypatch.setattr(harness, "PAGE_SIZE", 4_000)
    with harness._source_server() as port:
        def local_only(request):
            assert request.url.host == "127.0.0.1" and request.url.port == port

        # The real HTTP socket is scoped to this test's loopback server.
        http = SimpleNamespace(
            Client=lambda **kw: httpx.Client(
                trust_env=False, event_hooks={"request": [local_only]}, **kw),
            TimeoutException=httpx.TimeoutException, TransportError=httpx.TransportError,
        )
        monkeypatch.setattr(sharadar, "NDL_BASE", f"http://127.0.0.1:{port}")
        guarded = source_authority.StableSharadarFetch(
            snapshot_source.fetch_table, seed_mode=True)
        tickers = list(guarded(sharadar.TICKERS, http=http))
        assert {row["ticker"] for row in tickers} == set(harness.TICKERS)
        days = harness._session_days()
        interval = sharadar.date_params(days[-2].isoformat(), days[-1].isoformat())
        list(guarded(sharadar.ACTIONS, interval, http=http))
        list(guarded(sharadar.SFP, {"ticker": "SPY,BIL", **interval}, http=http))
        seeded = list(guarded(sharadar.SEP, interval, http=http))
        assert len(seeded) == 2 * len(harness.TICKERS)
        assert guarded.seed_coverage_evidence["missing_eligible_total"] == 0
        assert sum(item == {"table": "SEP", "channel": "pages"}
                   for item in harness.SOURCE_REQUESTS) >= 4
        actions, evidence = snapshot_export.fetch_complete_actions(
            through=days[-1].isoformat(), http=http)
        assert actions[0]["action"] == "relation"
        assert {row["action"] for row in actions} <= {"relation", "dividend"}
        assert actions[0]["action"] == "relation"
        snapshot_export.require_actions_refresh(
            through=days[-1].isoformat(), evidence=evidence, http=http)
        prices, _ = snapshot_export.fetch_complete_sep(
            start=days[-2].isoformat(), end=days[-1].isoformat(), http=http)
        assert len(prices) == 2 * len(harness.TICKERS)
        observed = {(item["table"], item["channel"]) for item in harness.SOURCE_REQUESTS}
        assert {("TICKERS", "pages"), ("TICKERS", "export"), ("TICKERS", "download"),
                ("ACTIONS", "export"), ("ACTIONS", "download"),
                ("SEP", "export"), ("SEP", "download")} <= observed
