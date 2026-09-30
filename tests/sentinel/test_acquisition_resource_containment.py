"""Oversized sources refuse intact; bounded cache operations survive absence."""
import hashlib
import io
import multiprocessing
import os
import signal
import struct
import time
import zipfile
from contextlib import contextmanager

import pytest

from sentinel.feed import acquisition_limits as limits, acquisition_work as work
from sentinel.feed import snapshot_export as export
from tests.sentinel.test_sharadar_snapshot_export import _Http, _Response, _zip_tickers
from tests.sentinel.test_source_acquisition_lifecycle import fresh, snapshot


def zipped(body, entries=1):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("source.csv", body)
        for index in range(entries - 1):
            archive.writestr(f"extra-{index}.txt", b"")
    return buffer.getvalue()


class Stream:
    def __init__(self, chunks, headers):
        self.chunks, self.headers = chunks, headers
        self.status_code = 200
        self.reads = 0

    def raise_for_status(self):
        pass

    def iter_bytes(self, chunk_size):
        for chunk in self.chunks:
            self.reads += 1
            yield chunk


class Client:
    def __init__(self, response):
        self.response, self.closed, self.calls = response, False, 0

    @contextmanager
    def stream(self, method, url, **kwargs):
        assert kwargs["headers"] == {"Accept-Encoding": "identity"}
        self.calls += 1
        try:
            yield self.response
        finally:
            self.closed = True


def download(client):
    return export._safe_download(client, "https://unit.invalid/file?secret=hidden",
                                 http=_Http([]), sleep=lambda _: pytest.fail("resource retry"), now=None)


@pytest.mark.parametrize("length", [None, "1", "4"])
def test_stream_limit_counts_bytes_without_trusting_length(monkeypatch, length):
    monkeypatch.setattr(limits, "ZIP_BYTES", 4)
    headers = {} if length is None else {"Content-Length": length}
    valid = Client(Stream([b"ab", b"cd"], headers))
    assert download(valid) == b"abcd" and valid.closed
    client = Client(Stream([b"abcd", b"e", b"unread"], headers))
    with pytest.raises(limits.AcquisitionResourceExceeded, match="ZIP_BYTES") as failure:
        download(client)
    assert client.closed and client.calls == 1 and client.response.reads == 2
    assert "hidden" not in str(failure.value)


def test_declared_oversize_refuses_before_consuming(monkeypatch):
    monkeypatch.setattr(limits, "ZIP_BYTES", 4)
    client = Client(Stream([b"never"], {"Content-Length": "5"}))
    with pytest.raises(limits.AcquisitionResourceExceeded):
        download(client)
    assert client.response.reads == 0 and client.closed


def test_http_compression_refuses_before_decompression():
    client = Client(Stream([b"never"], {"Content-Encoding": "gzip"}))
    with pytest.raises(export.SharadarSnapshotExportError, match="Content-Encoding"):
        download(client)
    assert client.response.reads == 0 and client.closed


@pytest.mark.parametrize("recovery", [False, True])
def test_go_refusal_reason_is_resource_not_provider_pending(monkeypatch, capsys, recovery):
    import json
    from pathlib import Path
    from types import SimpleNamespace
    root = Path(os.environ.get("SENTINEL_REPO_ROOT") or Path(__file__).resolve().parents[2])
    monkeypatch.syspath_prepend(str(root / "scripts"))
    import sentinel_go_validate_entry
    import sentinel_go_24x7_entry
    from sentinel import backup_guard, schema
    from sentinel.feed import store, rolling_go_inputs, outage_recovery
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
    def refuse(*a, **k):
        limits.check("ZIP_BYTES", limits.ZIP_BYTES + 1, limits.ZIP_BYTES)
    monkeypatch.setattr(rolling_go_inputs, "prepare", refuse)
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
    with pytest.raises(export.SharadarSnapshotExportError, match="unsupported compression"):
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


def test_cached_oversize_refuses_before_reading_or_network(monkeypatch, tmp_path):
    path = tmp_path / "old.zip"
    path.write_bytes(b"12345")
    path.with_suffix(".sha256").write_text(hashlib.sha256(b"12345").hexdigest())
    monkeypatch.setattr(limits, "ZIP_BYTES", 4)
    with pytest.raises(limits.AcquisitionResourceExceeded, match="ZIP_BYTES"):
        work.read_cached(path)


def cache_bytes(root):
    return sum(p.stat().st_size for p in root.iterdir()
               if p.suffix in {".zip", ".sha256"} or p.name.startswith(".partial-"))


def test_cache_reserves_bytes_before_writing(monkeypatch, tmp_path):
    monkeypatch.setattr(limits, "CACHE_BYTES", 138)
    work.save_cached(tmp_path / "a.zip", b"12345")
    work.save_cached(tmp_path / "b.zip", b"12345")
    assert cache_bytes(tmp_path) == 138  # Two exact-limit entries including checksums.
    original = work._atomic_write
    peaks = []
    def observed(path, blob):
        peaks.append(cache_bytes(tmp_path) + len(blob))
        original(path, blob)
    monkeypatch.setattr(work, "_atomic_write", observed)
    work.save_cached(tmp_path / "c.zip", b"123456")
    assert max(peaks) <= 138 and cache_bytes(tmp_path) == 70
    assert work.read_cached(tmp_path / "c.zip") == b"123456"


def test_cache_count_and_replacement_have_no_extra_copy(monkeypatch, tmp_path):
    monkeypatch.setattr(limits, "CACHE_FILES", 1)
    monkeypatch.setattr(limits, "CACHE_BYTES", 68)
    work.save_cached(tmp_path / "a.zip", b"old!")
    work.save_cached(tmp_path / "a.zip", b"new!")
    assert work.read_cached(tmp_path / "a.zip") == b"new!"
    work.save_cached(tmp_path / "b.zip", b"last")
    assert not (tmp_path / "a.zip").exists() and cache_bytes(tmp_path) == 68
    with pytest.raises(limits.AcquisitionResourceExceeded, match="CACHE_BYTES"):
        work.save_cached(tmp_path / "c.zip", b"large")
    assert work.read_cached(tmp_path / "b.zip") == b"last"


def test_cache_file_count_is_bounded_independently_of_bytes(monkeypatch, tmp_path):
    monkeypatch.setattr(limits, "CACHE_FILES", 1)
    work.save_cached(tmp_path / "old.zip", b"old")
    work.save_cached(tmp_path / "new.zip", b"new")
    assert list(tmp_path.glob("*.zip")) == [tmp_path / "new.zip"]


def test_legacy_cache_is_pruned_on_read_and_orphans_removed(monkeypatch, tmp_path):
    work.save_cached(tmp_path / "old.zip", b"old!")
    os.utime(tmp_path / "old.zip", (1, 1))
    work.save_cached(tmp_path / "new.zip", b"new!")
    (tmp_path / "orphan.sha256").write_bytes(b"x" * 100)
    (tmp_path / ".partial-dead").write_bytes(b"x" * 100)
    monkeypatch.setattr(limits, "CACHE_BYTES", 68)
    assert work.read_cached(tmp_path / "missing.zip") is None
    assert cache_bytes(tmp_path) == 68
    assert work.read_cached(tmp_path / "new.zip") == b"new!"
    assert cache_bytes(tmp_path) == 68
    assert work.read_cached(tmp_path / "old.zip") is None


@pytest.mark.parametrize("stage", ["write", "fsync", "replace", "checksum"])
def test_cache_failed_write_cleans_up_and_recovers(monkeypatch, tmp_path, stage):
    target = tmp_path / "a.zip"
    with monkeypatch.context() as patch:
        def fail(*args, **kwargs):
            raise OSError("injected disk failure")
        if stage in {"fsync", "replace"}:
            patch.setattr(work.os, stage, fail)
        elif stage == "write":
            original_fdopen = os.fdopen
            @contextmanager
            def broken_fdopen(*args, **kwargs):
                with original_fdopen(*args, **kwargs) as stream:
                    class Broken:
                        write = staticmethod(fail)
                    yield Broken()
            patch.setattr(work.os, "fdopen", broken_fdopen)
        else:
            original = work._atomic_write
            patch.setattr(work, "_atomic_write", lambda path, blob:
                          fail() if path.suffix == ".sha256" else original(path, blob))
        with pytest.raises(OSError, match="disk failure"):
            work.save_cached(target, b"data")
    assert cache_bytes(tmp_path) == 0
    work.save_cached(target, b"recovered")
    assert work.read_cached(target) == b"recovered"


def test_concurrent_writers_reserve_under_one_kernel_lock(monkeypatch, tmp_path):
    monkeypatch.setattr(limits, "CACHE_BYTES", 138)
    ctx = multiprocessing.get_context("fork")
    start = ctx.Event()
    def write(index):
        start.wait(10)
        original = work._atomic_write
        def observed(path, blob):
            assert cache_bytes(tmp_path) + len(blob) <= 138
            time.sleep(.03)  # Expose reservation races if the global lock is removed.
            original(path, blob)
        work._atomic_write = observed
        work.save_cached(tmp_path / f"{index}.zip", b"12345")
    workers = [ctx.Process(target=write, args=(i,)) for i in range(4)]
    for worker in workers:
        worker.start()
    start.set()
    for worker in workers:
        worker.join(15)
        if worker.is_alive():
            worker.kill()
            worker.join()
        assert worker.exitcode == 0
    assert cache_bytes(tmp_path) <= 138


def test_reader_holds_reservation_lock_until_bytes_are_consumed(monkeypatch, tmp_path):
    monkeypatch.setattr(limits, "CACHE_FILES", 1)
    target = tmp_path / "old.zip"
    work.save_cached(target, b"old!")
    ctx = multiprocessing.get_context("fork")
    reading, release, writing, done = [ctx.Event() for _ in range(4)]
    def read():
        original = work.os.fstat
        def paused(fd):
            reading.set()
            assert release.wait(10)
            return original(fd)
        work.os.fstat = paused
        assert work.read_cached(target) == b"old!"
    def write():
        writing.set()
        work.save_cached(tmp_path / "new.zip", b"new!")
        done.set()
    reader, writer = ctx.Process(target=read), ctx.Process(target=write)
    reader.start()
    try:
        assert reading.wait(10)
        writer.start()
        assert writing.wait(10)
        assert not done.wait(.3)
        assert target.exists()
    finally:
        release.set()
        for process in (reader, writer):
            if process.pid is not None:
                process.join(15)
                if process.is_alive():
                    process.kill()
                    process.join()
    assert reader.exitcode == writer.exitcode == 0
    assert work.read_cached(tmp_path / "new.zip") == b"new!"


def test_killed_writer_partial_is_removed_before_next_reservation(monkeypatch, tmp_path):
    monkeypatch.setattr(limits, "CACHE_BYTES", 68)
    target = tmp_path / "a.zip"
    def killed_write():
        work.os.replace = lambda *a: os.kill(os.getpid(), signal.SIGKILL)
        work.save_cached(target, b"dead")
    worker = multiprocessing.get_context("fork").Process(target=killed_write)
    worker.start()
    worker.join(10)
    assert worker.exitcode == -signal.SIGKILL
    assert list(tmp_path.glob(".partial-*"))
    work.save_cached(target, b"good")
    assert cache_bytes(tmp_path) == 68 and not list(tmp_path.glob(".partial-*"))
    assert work.read_cached(target) == b"good"


def test_refused_download_never_caches_partial_and_next_attempt_recovers(monkeypatch):
    monkeypatch.setenv("SHARADAR_API_KEY", "unit")
    blob = _zip_tickers([["SEP", "1", "AAA"]])
    with monkeypatch.context() as patch:
        patch.setattr(limits, "ZIP_BYTES", len(blob) - 1)
        with pytest.raises(limits.AcquisitionResourceExceeded):
            export.download_snapshot(snapshot(), required={"ticker"},
                                     http=_Http([fresh(), _Response(content=blob)]))
    assert not list(work.cache_root().glob("*.zip"))
    rows, proof = export.download_snapshot(snapshot(), required={"ticker"},
                                          http=_Http([fresh(), _Response(content=blob)]))
    assert rows == [{"table": "SEP", "permaticker": "1", "ticker": "AAA"}]
    assert proof["file_sha256"] == hashlib.sha256(blob).hexdigest()
    assert export.download_snapshot(snapshot(), required={"ticker"}, http=_Http([])) == (rows, proof)


def test_verified_cache_still_obeys_parser_envelope(monkeypatch):
    monkeypatch.setenv("SHARADAR_API_KEY", "unit")
    blob = _zip_tickers([["SEP", "1", "AAA"], ["SEP", "2", "BBB"]])
    export.download_snapshot(snapshot(), required={"ticker"},
                             http=_Http([fresh(), _Response(content=blob)]))
    monkeypatch.setattr(limits, "ROWS", 1)
    with pytest.raises(limits.AcquisitionResourceExceeded, match="ROWS"):
        export.download_snapshot(snapshot(), required={"ticker"}, http=_Http([]))


def test_httpx_stream_preserves_exact_complete_export_bytes(monkeypatch):
    import httpx
    blob = zipped("ticker\nAAA\n")
    monkeypatch.setattr(limits, "ZIP_BYTES", len(blob))
    def provider(request):
        assert request.headers["Accept-Encoding"] == "identity"
        return httpx.Response(200, content=blob)
    with httpx.Client(transport=httpx.MockTransport(provider)) as client:
        result = export._safe_download(client, "https://unit.invalid/file", http=httpx,
                                       sleep=lambda _: pytest.fail("unexpected retry"), now=None)
    assert result == blob
    assert export._csv_rows(result, required={"ticker"}) == [{"ticker": "AAA"}]
