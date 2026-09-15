"""Binary source evidence is independent of economic numeric canonicalization."""
import hashlib

import httpx
import pytest

from research.sharadar_replay import provider as provider_module
from research.sharadar_replay.model import Fault
from research.sharadar_replay.provider import Provider
from research.sharadar_replay.scenarios import FIRST, step


@pytest.mark.parametrize("invalid", [False, True])
def test_download_sha256_binds_exact_delivered_bytes(monkeypatch, invalid):
    provider = Provider()
    faults = (Fault(table="SEP", channel="export", kind="invalid_zip"),) if invalid else ()
    provider.advance(step("binary_evidence", FIRST, faults=faults))
    export = provider(httpx.Request("GET",
        "https://data.nasdaq.com/api/v3/datatables/SHARADAR/SEP.json?qopts.export=true"))
    link = export.json()["datatable_bulk_download"]["file"]["link"]

    def forbid_numeric_digest(_value):
        raise AssertionError("binary download entered economic numeric canonicalization")

    monkeypatch.setattr(provider_module, "digest", forbid_numeric_digest)
    first = provider(httpx.Request("GET", link))
    assert provider.transcript[-1]["sha256"] == hashlib.sha256(first.content).hexdigest()
    assert provider.transcript[-1]["download_table"] == "SEP"
    generation = provider.transcript[-1]["generation"]
    second = provider(httpx.Request("GET", link))
    assert second.content == first.content
    assert provider.transcript[-1]["sha256"] == hashlib.sha256(second.content).hexdigest()
    assert provider.transcript[-1]["generation"] == generation
    assert len([r for r in provider.transcript if r["channel"] == "download"]) == 2
