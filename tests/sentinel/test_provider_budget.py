import io
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Event, Thread
from types import SimpleNamespace
from urllib.error import HTTPError

import pytest

from sentinel.feed import alpaca_transport as alpaca, openfigi, provider_budget


class Reply(io.BytesIO):
    status = 200


@pytest.mark.parametrize("provider", ["alpaca", "openfigi"])
def test_job_deadline_and_private_cooldown_across_client_restart(provider, tmp_path, monkeypatch):
    monkeypatch.setenv("SENTINEL_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("ALPACA_API_KEY", "test")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test")
    requests, sleeps = [], []
    (provider_budget.cache_root() / 'cooldown.sqlite').write_bytes(b'old or unreadable source state')
    asset = dict(ticker="AAA", exchange="NYSE")

    def observe(which, *, throttle=False):
        def open_request(request, timeout):
            requests.append((which, timeout))
            if throttle:
                raise HTTPError(request.full_url, 429, "rate limit", {"Retry-After": "60"}, None)
            return Reply(json.dumps([{}]).encode())
        opener = SimpleNamespace(open=open_request)
        if which == "alpaca":
            return alpaca.Client(opener=opener, sleeper=sleeps.append).get(alpaca.BAR_URL)
        return openfigi.Client(opener=opener, sleeper=sleeps.append).mapping([asset])

    with provider_budget.budget(1), provider_budget.budget(500):
        with pytest.raises(alpaca.AlpacaTransportUnavailable, match="deadline"):
            observe(provider, throttle=True)
        assert sleeps == [] and len(requests) == 1 and 0 < requests[0][1] <= 1
        with pytest.raises(alpaca.AlpacaTransportUnavailable, match="rate limit"):
            observe(provider)
        assert len(requests) == 1
        observe("openfigi" if provider == "alpaca" else "alpaca")
        assert len(requests) == 2


@pytest.mark.parametrize("provider", ["alpaca", "openfigi"])
def test_response_after_deadline_is_rejected_without_retry(provider, tmp_path, monkeypatch):
    monkeypatch.setenv("SENTINEL_STATE_DIR", str(tmp_path))
    monkeypatch.setenv("ALPACA_API_KEY", "test")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test")
    clock, requests = [11], []
    monkeypatch.setattr(provider_budget.time, "monotonic", lambda: clock[0])

    def late(request, timeout):
        requests.append(timeout)
        clock[0] += 3
        return Reply(b"[{}]")

    opener = SimpleNamespace(open=late)
    with provider_budget.budget(2), pytest.raises(alpaca.AlpacaTransportUnavailable, match="deadline"):
        if provider == "alpaca":
            alpaca.Client(opener=opener).get(alpaca.BAR_URL)
        else:
            openfigi.Client(opener=opener).mapping([dict(ticker="A", exchange="NYSE")])
    assert requests == [2]


@pytest.mark.parametrize("provider", ["alpaca", "openfigi"])
def test_production_socket_cancels_slow_continuous_response(provider, monkeypatch):
    from contextlib import nullcontext
    stop, started, finished, fully_sent = Event(), Event(), Event(), Event()

    class SlowBody(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Length', '160')
            self.end_headers()
            started.set()
            try:
                for _ in range(160):
                    if stop.wait(.03):
                        break
                    self.wfile.write(b' ')
                else:
                    fully_sent.set()
            except OSError:
                pass
            finally:
                finished.set()

        do_POST = do_GET

        def log_message(self, *args):
            pass

    monkeypatch.setenv("ALPACA_API_KEY", "test")
    monkeypatch.setenv("ALPACA_SECRET_KEY", "test")
    with ThreadingHTTPServer(('127.0.0.1', 0), SlowBody) as server:
        server_thread = Thread(target=server.serve_forever, daemon=True)
        server_thread.start()
        endpoint = f"http://127.0.0.1:{server.server_port}/test"
        monkeypatch.setattr(alpaca, 'BAR_URL', endpoint)
        monkeypatch.setattr(openfigi, 'ENDPOINT', endpoint)
        client = alpaca.Client() if provider == 'alpaca' else openfigi.Client()
        try:
            with client.pooled() if provider == 'alpaca' else nullcontext():
                with provider_budget.budget(1.5), pytest.raises(alpaca.AlpacaTransportUnavailable):
                    if provider == 'alpaca':
                        client.get(endpoint)
                    else:
                        client.mapping([dict(ticker="A", exchange="NYSE")])
                assert started.is_set() and not fully_sent.is_set()
        finally:
            stop.set()
            server.shutdown()
            server_thread.join(timeout=2)
        assert finished.wait(2)


def test_provider_retry_horizon_is_recorded_in_scheduler(monkeypatch):
    from sentinel.feed import rolling_publisher as publisher
    recorded = []
    monkeypatch.setattr(publisher.jobs, 'expire', lambda *_: False)
    monkeypatch.setattr(publisher.jobs, 'status', lambda *_: {"remaining_seconds": 300})
    monkeypatch.setattr(publisher.jobs, 'wait', lambda *_, **kw: recorded.append(kw))
    connection = SimpleNamespace(commit=lambda: None, rollback=lambda: None)
    publisher._record_failure(connection, SimpleNamespace(job_id="test"),
                              alpaca.AlpacaTransportUnavailable("rate limit", delay=61.5))
    assert recorded == [dict(state="RETRY_WAIT", reason="SOURCE_RETRY", retry_seconds=62)]
