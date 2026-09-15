"""Prepared transport observations preserve bytes and adversarial schedules."""
import datetime as dt
from decimal import Decimal
import json
import random

import httpx
import pytest

from research.sharadar_replay import provider as module
from research.sharadar_replay.model import Fault, Revision
from research.sharadar_replay.oracle import canonical_bytes, digest
from research.sharadar_replay.provider import Provider
from research.sharadar_replay.scenarios import FIRST, step

URL = "https://data.nasdaq.com/api/v3/datatables/SHARADAR/SEP.json"


def request(provider, **query):
    return provider(httpx.Request("GET", URL, params=query))


def legacy_rows(provider, table, query):
    identities = {"ACTIONS": {"action", "contraticker"}, "TICKERS": {"permaticker"}}.get(table, set())
    rows = []
    for row in provider._views[table]:
        if "ticker" in query and row.get("ticker") not in query["ticker"].split(","):
            continue
        if any(field in query and (row.get(field) is None or
               str(row[field]) not in query[field].split(",")) for field in identities):
            continue
        if "table" in query and row.get("table") != query["table"]:
            continue
        if any(key in query and (row.get(field) is None or
               (str(row[field]) < query[key] if bound == "gte" else str(row[field]) > query[key]))
               for field in ("date", "lastupdated") for bound in ("gte", "lte")
               for key in (f"{field}.{bound}",)):
            continue
        rows.append(dict(row))
    rows.sort(key=lambda row: (str(row.get("date", "")), str(row.get("ticker", "")),
                              json.dumps(row, sort_keys=True)))
    if provider.variation_seed:
        random.Random(provider.variation_seed).shuffle(rows)
    return rows


class UncachedProvider(Provider):
    def __call__(self, request):
        self._exports = {}
        return super().__call__(request)

    def _prepare_rows(self, table, query, faults):
        rows = legacy_rows(self, table, query)
        for fault in faults:
            if fault.kind == "set_value":
                for row in rows:
                    if fault.ticker is None or row.get("ticker") == fault.ticker:
                        row[fault.field] = fault.value
            elif fault.kind == "omit_ticker":
                rows = [row for row in rows if row.get("ticker") != fault.ticker]
            elif fault.kind == "duplicate_row" and rows:
                rows.append(dict(rows[0]))
            elif fault.kind == "conflicting_row" and rows:
                rows.append(dict(rows[0], close=999))
        return rows, canonical_bytes(rows)

    @staticmethod
    def _generation_digest(prefix, encoded_rows):
        return digest([*prefix, json.loads(encoded_rows)])


@pytest.mark.parametrize("kind", [None, "set_value", "omit_ticker", "duplicate_row", "conflicting_row"])
@pytest.mark.parametrize("revision_offset", [None, 0, 7])
def test_cached_pages_and_exports_match_uncached_transport(kind, revision_offset):
    faults = (() if kind is None else (Fault(table="SEP", kind=kind, after_rows=7,
                  ticker="AAA", field="close", value=17.25),))
    current = step("prepared", FIRST, faults=faults)
    if revision_offset is not None:
        changed = tuple(dict(row, close=21.5) if row["ticker"] == "AAA" else row
                        for row in current.tables["SEP"])
        current = current.model_copy(update={"revisions": (Revision(name="changed", table="SEP",
            observation=2, after_rows=revision_offset, rows=changed),)})
    providers = [Provider(page_size=7, variation_seed=19), UncachedProvider(page_size=7, variation_seed=19)]
    for provider in providers:
        provider.advance(current)
    for _ in range(2):
        for offset in (None, "7", "14"):
            query = {"api_key": "synthetic-only"}
            if offset is not None:
                query["qopts.cursor_id"] = offset
            responses = [request(provider, **query) for provider in providers]
            assert responses[0].content == responses[1].content
            assert providers[0].transcript == providers[1].transcript
    responses = [request(provider, **{"qopts.export": "true"}) for provider in providers]
    assert responses[0].content == responses[1].content
    for provider, response in zip(providers, responses):
        link = response.json()["datatable_bulk_download"]["file"]["link"]
        provider(httpx.Request("GET", link))
    assert providers[0].transcript == providers[1].transcript
    assert providers[0]._downloads == providers[1]._downloads


def test_unchanged_pages_and_corroboration_prepare_once(monkeypatch):
    provider = Provider(page_size=7)
    provider.advance(step("prepared_once", FIRST))
    calls = []
    original = module.canonical_bytes

    def counted(value):
        if isinstance(value, list) and value and isinstance(value[0], dict):
            calls.append(len(value))
        return original(value)

    monkeypatch.setattr(module, "canonical_bytes", counted)
    for _ in range(2):
        for query in ({}, {"qopts.cursor_id": "7"}, {"qopts.cursor_id": "14"}):
            request(provider, **query)
    assert calls == [len(provider.step.tables["SEP"])]
    provider.advance(step("next_generation", FIRST).model_copy(update={
        "at": provider.step.at + dt.timedelta(days=1)}))
    request(provider)
    assert len(calls) == 2


def test_monthly_export_corroboration_reuses_compact_descriptors(monkeypatch):
    providers = [Provider(variation_seed=19), UncachedProvider(variation_seed=19)]
    calls = []
    original = module.canonical_bytes

    def counted(value):
        if isinstance(value, list) and value and isinstance(value[0], dict):
            calls.append(len(value))
        return original(value)

    monkeypatch.setattr(module, "canonical_bytes", counted)
    for provider in providers:
        provider.advance(step("monthly_exports", FIRST))
    for _ in range(3):
        for lo, hi in (("2025-12-01", "2025-12-31"), ("2026-01-01", "2026-01-31")):
            query = {"date.gte": lo, "date.lte": hi, "qopts.export": "true"}
            responses = [request(provider, **query) for provider in providers]
            assert responses[0].content == responses[1].content
            assert providers[0].transcript == providers[1].transcript
            bodies = [provider(httpx.Request("GET", response.json()["datatable_bulk_download"]["file"]["link"])).content
                      for provider, response in zip(providers, responses)]
            assert bodies[0] == bodies[1]
    assert len(calls) == 2
    assert len(providers[0]._prepared) == 1
    assert len(providers[0]._exports["SEP"]) == 2
    assert providers[0].transcript == providers[1].transcript


@pytest.mark.parametrize("channel", ["pages", "export"])
def test_bounded_date_index_observes_revisions_and_preserves_issued_exports(channel):
    current = step("indexed_revision", FIRST)
    changed = tuple(dict(row, close=21.5) if row["ticker"] == "AAA" else row
                    for row in current.tables["SEP"])
    current = current.model_copy(update={"revisions": (Revision(name="changed", table="SEP",
        channel=channel, observation=2, after_rows=0, rows=changed),)})
    providers = [Provider(variation_seed=19), UncachedProvider(variation_seed=19)]
    query = {"date.gte": FIRST, "date.lte": FIRST}
    if channel == "export":
        query["qopts.export"] = "true"
    issued = []
    for provider in providers:
        provider.advance(current)
    for _ in range(2):
        responses = [request(provider, **query) for provider in providers]
        assert responses[0].content == responses[1].content
        assert providers[0].transcript == providers[1].transcript
        if channel == "export":
            links = [response.json()["datatable_bulk_download"]["file"]["link"]
                     for response in responses]
            bodies = [provider(httpx.Request("GET", link)).content
                      for provider, link in zip(providers, links)]
            assert bodies[0] == bodies[1]
            issued.append((links, bodies))
    for links, bodies in issued:
        assert [provider(httpx.Request("GET", link)).content
                for provider, link in zip(providers, links)] == bodies
    next_rows = tuple(dict(row, close=33.5) if row["ticker"] == "AAA" else row
                      for row in changed)
    for provider in providers:
        provider.assert_revisions_applied()
        provider.advance(step("next_indexed_generation", FIRST).model_copy(update={
            "at": current.at + dt.timedelta(days=1),
            "tables": {**current.tables, "SEP": next_rows}}))
    responses = [request(provider, **query) for provider in providers]
    assert responses[0].content == responses[1].content
    assert providers[0].transcript == providers[1].transcript


def test_date_index_scans_source_once_and_preserves_filters():
    provider = Provider(variation_seed=11)
    provider.advance(step("indexed", FIRST))

    class CountedRows(list):
        visits = 0

        def __iter__(self):
            for row in super().__iter__():
                self.visits += 1
                yield row

    source = CountedRows(provider._views["SEP"])
    provider._views["SEP"] = source
    for index, query in enumerate(({"date.gte": FIRST}, {"date.lte": FIRST},
                                  {"date.gte": FIRST, "date.lte": FIRST, "ticker": "AAA"},
                                  {"date.gte": FIRST, "lastupdated.gte": FIRST})):
        expected = legacy_rows(provider, "SEP", query)
        before = source.visits
        assert provider.rows("SEP", query) == expected
        assert source.visits - before == (len(source) if index == 0 else 0)
    assert len(provider._date_rows) == 1


@pytest.mark.parametrize("prefix", [[], ["SEP"], ["step", "SEP", {"date.gte": FIRST}]])
def test_generation_digest_preserves_exact_economic_canonicalization(prefix):
    rows = [{"ticker": "AAA", "close": Decimal("12.5000"), "volume": 10,
             "flag": False, "missing": None, "date": dt.date.fromisoformat(FIRST)}]
    assert Provider._generation_digest(prefix, canonical_bytes(rows)) == digest([*prefix, rows])
