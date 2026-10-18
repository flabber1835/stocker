"""Synthetic table-export HTTP/ZIP doubles for retained acquisition fixtures.

The serialized member names are legacy protocol bytes, not a production source.
"""
import io
import zipfile
from contextlib import contextmanager


class _Response:
    def __init__(self, *, status=200, payload=None, content=b"", headers=None):
        self.status_code = status
        self._payload = payload
        self.content = content
        self.headers = headers or {}

    def json(self):
        return self._payload

    def iter_bytes(self, chunk_size):
        for offset in range(0, len(self.content), chunk_size):
            yield self.content[offset:offset + chunk_size]

    def raise_for_status(self):
        if not 200 <= self.status_code < 300:
            exc = RuntimeError(f"HTTP {self.status_code}")
            exc.response = self
            raise exc


def _zip_csv(name: str, header: str, rows: list[list[str]]) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        body = header + "\n" + "\n".join(",".join(row) for row in rows) + "\n"
        archive.writestr(name, body)
    return out.getvalue()


def _zip_actions(rows: list[list[str]]) -> bytes:
    return _zip_csv(
        "SHARADAR_ACTIONS.csv",
        "date,action,ticker,name,value,contraticker,contraname", rows)


def _zip_tickers(rows: list[list[str]]) -> bytes:
    return _zip_csv("SHARADAR_TICKERS.csv", "table,permaticker,ticker", rows)


class _Client:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def get(self, url, params=None, **kwargs):
        self.calls.append((url, dict(params or {})))
        return self.responses.pop(0)

    @contextmanager
    def stream(self, method, url, **kwargs):
        assert method == "GET"
        yield self.get(url, **kwargs)


class _Http:
    class TimeoutException(Exception):
        pass

    class TransportError(Exception):
        pass

    def __init__(self, responses):
        self.client = _Client(responses)

    def Client(self, timeout=None):
        return self.client


def _status(*, state="fresh", link="https://example.com/snapshot.zip?api_key=secret",
            snapshot="2026-08-19T22:00:00Z",
            refreshed="2026-08-19T21:59:00Z"):
    return {
        "datatable_bulk_download": {
            "file": {
                "link": link,
                "status": state,
                "data_snapshot_time": snapshot,
            },
            "datatable": {"last_refreshed_time": refreshed},
        }
    }
