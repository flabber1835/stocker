import copy
from decimal import Decimal

import httpx
import pytest
from pydantic import ValidationError

from research.sharadar_replay.model import Fault, Scenario
from research.sharadar_replay.oracle import StateMismatch, compare, compare_readiness, corpus_digest, digest
from research.sharadar_replay.provider import Provider
from research.sharadar_replay.runner import checked_server_dsn
from research.sharadar_replay.runtime import simulated_runtime
from research.sharadar_replay.scenarios import FIRST, SEED, build_scenarios, sessions, step, world


def test_scenarios_roundtrip_and_have_independent_provider_expectations():
    for scenario in build_scenarios().values():
        assert Scenario.model_validate_json(scenario.model_dump_json()) == scenario
        assert len(scenario.seed.expected.bars) > 254
    tables, expected = world(SEED)
    before = digest(expected.model_dump())
    tables["SEP"][0]["close"] = 999
    assert digest(expected.model_dump()) == before


@pytest.mark.parametrize("through", ["2026-05-01", "2026-05-04", SEED])
def test_replay_world_carries_reviewed_cash_authority(through):
    from sentinel.feed.corporate_action_authority import resolve_dividends

    tables, expected = world(through)
    resolution = resolve_dividends(tables["ACTIONS"], sessions(through))
    source = [r for r in tables["ACTIONS"] if r["ticker"] == "TRI"]
    canonical = [r for r in expected.bars if r[2] == "TRI"]
    identities = [r for r in expected.identities if r[1] == "TRI"]
    if through < "2026-05-04":
        assert not source and not canonical and not identities
        assert not resolution.adjudications
        return

    assert len(source) == len(canonical) == len(identities) == 1
    assert source[0]["value"] == 1.36
    assert canonical[0][-1] == 1.435518
    assert resolution.dividends[("TRI", "2026-05-04")] == Decimal(str(canonical[0][-1]))
    assert identities[0][-3:] == ("2026-05-04", "2026-05-04", True)


@pytest.mark.parametrize("field", ["bars", "actions", "identities", "spy", "defensive"])
def test_checker_kills_missing_and_extra_row_mutants(field):
    _, expected = world(SEED)
    rows = getattr(expected, field)
    for damaged in (rows[1:], (*rows, rows[0])):
        with pytest.raises(StateMismatch, match=field):
            compare(expected, expected.model_copy(update={field: damaged}))


@pytest.mark.parametrize("column", [0, 1, 3, 4, 5, 6, 7, 8])
def test_checker_kills_identity_timing_price_split_and_dividend_mutants(column):
    _, expected = world(SEED)
    row = list(expected.bars[0])
    row[column] = "WRONG" if column < 2 else 999
    damaged = expected.model_copy(update={"bars": (tuple(row), *expected.bars[1:])})
    with pytest.raises(StateMismatch):
        compare(expected, damaged)


def test_checker_rejects_false_readiness_and_missing_blocker():
    for actual, blockers in ((True, []), (False, [])):
        with pytest.raises(StateMismatch):
            compare_readiness(expected=False, actual=actual,
                              required_blockers=("freshness",), failures=blockers)


def test_corpus_digest_is_order_independent_but_retains_duplicate_multiplicity():
    _, expected = world(SEED)
    reordered = expected.model_copy(update={"bars": tuple(reversed(expected.bars))})
    assert corpus_digest(reordered) == corpus_digest(expected)
    duplicate = expected.model_copy(update={"bars": (*expected.bars, expected.bars[0])})
    assert corpus_digest(duplicate) != corpus_digest(expected)


def test_no_future_observation_and_monotonic_clock():
    current = step("current", FIRST)
    value = current.model_dump()
    value["tables"] = copy.deepcopy(value["tables"])
    value["tables"]["SEP"][0]["lastupdated"] = "2099-01-01"
    with pytest.raises(ValidationError, match="future"):
        type(current).model_validate(value)
    provider = Provider()
    provider.advance(current)
    with pytest.raises(ValueError, match="strictly advance"):
        provider.advance(current)


def test_strict_production_http_pages_exports_and_query_filters():
    from sentinel.feed import sharadar, snapshot_export, snapshot_source
    provider = Provider(page_size=7)
    provider.advance(step("current", FIRST))
    with simulated_runtime(provider, commit="a" * 40):
        got = list(sharadar.fetch_table("SEP", {"date.gte": FIRST, "date.lte": FIRST}))
        assert len(got) == 2
        full = list(sharadar.fetch_table("SEP"))
        assert len(full) > 254
        identities = list(snapshot_source.fetch_table("TICKERS"))
        assert {row["ticker"] for row in identities} == {"AAA", "BBB", "TRI"}
        assert len(identities) == 3
        rows, authority = snapshot_export.fetch_complete_sep(start=SEED, end=FIRST)
        assert len(rows) == 4
        assert authority["authority"] == "nasdaq-data-link-table-export/v1"
    assert any("qopts.cursor_id" in r.get("query", {}) for r in provider.transcript)
    assert "synthetic-provider-only" not in str(provider.transcript)


@pytest.mark.parametrize("fault,error", [
    (Fault(table="SEP", kind="missing_column"), "SharadarProtocolError"),
    (Fault(table="SEP", kind="repeat_cursor"), "PaginationError"),
    (Fault(table="TICKERS", kind="omit_ticker", ticker="BBB"), "SharadarSnapshotExportError"),
    (Fault(table="TICKERS", channel="export", kind="stale_export"), "SharadarSnapshotExportError"),
])
def test_transport_falsifiers_use_production_validators(fault, error):
    from sentinel.feed import snapshot_source
    provider = Provider(page_size=7)
    provider.advance(step("faulted", FIRST, faults=(fault,)))
    with simulated_runtime(provider, commit="a" * 40):
        with pytest.raises(Exception) as caught:
            list(snapshot_source.fetch_table(fault.table))
    assert type(caught.value).__name__ == error


def test_unmodeled_network_and_query_are_refused():
    provider = Provider()
    provider.advance(step("current", FIRST))
    with pytest.raises(RuntimeError, match="boundary"):
        provider(httpx.Request("GET", "https://example.com/"))
    with pytest.raises(ValueError, match="unmodeled query"):
        provider.rows("SEP", {"surprise": "value"})


def test_database_routing_is_local_and_explicit():
    assert checked_server_dsn("postgresql://test@127.0.0.1/test")["host"] == "127.0.0.1"
    for dsn in ("postgresql://test@production/test", "dbname=test",
                "host=127.0.0.1 hostaddr=192.0.2.1 dbname=test"):
        with pytest.raises(ValueError):
            checked_server_dsn(dsn)
