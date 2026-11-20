"""Bounded reads of retained captures and their refusal dispositions."""
import io
import os
import struct
import zipfile

import pytest

from sentinel.feed import acquisition_limits as limits
from sentinel.feed import snapshot_export as export
from tests.sentinel.test_source_acquisition_lifecycle import snapshot, stage
from tests.support.table_export import _zip_tickers


def zipped(body, entries=1):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("source.csv", body)
        for index in range(entries - 1):
            archive.writestr(f"extra-{index}.txt", b"")
    return buffer.getvalue()



@pytest.mark.parametrize("recovery", [False, True])
def test_go_refusal_reason_is_resource_not_provider_pending(monkeypatch, capsys, recovery):
    import json
    from pathlib import Path
    from types import SimpleNamespace
    root = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
    monkeypatch.syspath_prepend(str(root / "scripts"))
    import sentinel_go_validate_entry
    import sentinel_go_24x7_entry
    from sentinel import backup_guard, schema, retained_go
    from sentinel.feed import store, outage_recovery
    calls = []
    conn = SimpleNamespace(rollback=lambda: calls.append("rollback"), close=lambda: calls.append("close"))
    noop = lambda *a, **k: None
    monkeypatch.setenv("SENTINEL_DATABASE_URL", "fixture")
    # Direct payload execution must supply the deadline normally injected by GO.
    monkeypatch.setenv("SENTINEL_GO_PREPARATION_DEADLINE", "2026-08-12T05:46:00+00:00")
    monkeypatch.setattr(store, "connect", lambda *a: conn)
    monkeypatch.setattr(backup_guard, "require_writes_permitted", noop)
    monkeypatch.setattr(schema, "ensure_schema", noop)
    monkeypatch.setattr(store, "migrate_schema", noop)
    monkeypatch.setattr(store, "require_feed_schema", noop)
    def refuse(*a, **k):
        limits.check("ZIP_BYTES", limits.ZIP_BYTES + 1, limits.ZIP_BYTES)
    monkeypatch.setattr(retained_go, "prepare", refuse)
    monkeypatch.setattr(outage_recovery, "catch_up", refuse)
    code = (sentinel_go_validate_entry._RECOVERY_PREPARATION_CODE if recovery
            else sentinel_go_24x7_entry._PREPARATION_CODE)
    code = code.replace("target = calendar.latest_closed_session()", "target = '2026-08-11'")
    code = code.replace("now = datetime.now(timezone.utc)",
                        "now = datetime(2026, 8, 12, 3, 46, tzinfo=timezone.utc)")
    with pytest.raises(limits.AcquisitionResourceExceeded):
        exec(code, {})
    output = capsys.readouterr().out
    payload = json.loads(output.split("SENTINEL_GO_PREPARATION_FAILURE=", 1)[1])
    assert payload["reason_code"] == "SOURCE_RESOURCE_LIMIT"
    assert "SENTINEL_GO_PREPARATION=" not in output
    assert calls[-2:] == ["rollback", "close"]



@pytest.mark.parametrize("boundary,maximum,body", [
    ("CSV_BYTES", 4, "a\nx\n"),
    ("ROWS", 2, "a\nx\ny\n"),
    ("CELLS", 4, "a,b\nx,y\nz,w\n"),
    ("COLUMNS", 2, "a,b\nx,y\n"),
    ("RECORD_CHARS", 8, 'a\n"x\nyzz"\n'),
], ids=["CSV_BYTES", "ROWS", "CELLS", "COLUMNS", "RECORD_CHARS"])
def test_csv_exact_limit_then_one_less_refuses(monkeypatch, boundary, maximum, body):
    monkeypatch.setattr(limits, boundary, maximum)
    assert export._csv_rows(zipped(body), required={"a"})
    monkeypatch.setattr(limits, boundary, maximum - 1)
    with pytest.raises(limits.AcquisitionResourceExceeded, match=boundary):
        export._csv_rows(zipped(body), required={"a"})



def test_expansion_refused_before_opening_member(monkeypatch):
    blob = zipped("a\n" + "x" * 10000)
    monkeypatch.setattr(limits, "CSV_BYTES", 100)
    monkeypatch.setattr(zipfile.ZipFile, "open", lambda *a, **k: pytest.fail("expanded oversized CSV"))
    with pytest.raises(limits.AcquisitionResourceExceeded, match="CSV_BYTES"):
        export._csv_rows(blob, required={"a"})



def test_alternative_zip_decoder_refused_before_open(monkeypatch):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_BZIP2) as archive:
        archive.writestr("source.csv", "a\nx\n")
    monkeypatch.setattr(zipfile.ZipFile, "open", lambda *a, **k: pytest.fail("unsupported decoder"))
    with pytest.raises(export.SnapshotExportError, match="unsupported compression"):
        export._csv_rows(buffer.getvalue(), required={"a"})



def test_observed_expansion_bound_is_independent_of_metadata(monkeypatch):
    monkeypatch.setattr(limits, "CSV_BYTES", 4)
    good = limits.ExpandedReader(io.BytesIO(b"1234"))
    assert io.BufferedReader(good).read() == b"1234"
    with pytest.raises(limits.AcquisitionResourceExceeded, match="CSV_BYTES"):
        io.BufferedReader(limits.ExpandedReader(io.BytesIO(b"12345"))).read()



@pytest.mark.parametrize("boundary", ["ZIP_ENTRIES", "DIRECTORY_BYTES", "ZIP_BYTES"])
def test_directory_bounds_precede_zipfile_allocation(monkeypatch, boundary):
    blob = zipped("a\nx\n", entries=2)
    eocd = blob.rfind(b"PK\x05\x06")
    maximum = {"ZIP_ENTRIES": 2, "DIRECTORY_BYTES": struct.unpack_from("<L", blob, eocd + 12)[0],
               "ZIP_BYTES": len(blob)}[boundary]
    monkeypatch.setattr(limits, boundary, maximum)
    assert export._csv_rows(blob, required={"a"}) == [{"a": "x"}]
    monkeypatch.setattr(limits, boundary, maximum - 1)
    monkeypatch.setattr(zipfile, "ZipFile", lambda *a, **k: pytest.fail("allocated oversized directory"))
    with pytest.raises(limits.AcquisitionResourceExceeded, match=boundary):
        export._csv_rows(blob, required={"a"})



def test_existing_archive_obeys_both_byte_and_decoded_row_limits(monkeypatch):
    blob = _zip_tickers([["SEP", "1", "AAA"], ["SEP", "2", "BBB"]])
    path = stage(blob)
    for name, cap in (("ZIP_BYTES", len(blob)-1), ("ROWS", 1)):
        with monkeypatch.context() as owner:
            owner.setattr(limits, name, cap)
            with pytest.raises(limits.AcquisitionResourceExceeded, match=name):
                export.download_snapshot(snapshot(), required={"ticker"})
        assert path.read_bytes() == blob
