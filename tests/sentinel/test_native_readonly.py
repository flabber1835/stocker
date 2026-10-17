import asyncio
import hashlib
import json

import httpx
from pydantic import ValidationError
import pytest

from sentinel.execution.native_readonly import (
    ExecutionSubject, NativeReadRefused, ReadOnlyAlpacaClient, ReadOnlyLimits,
)


ACCOUNT_ID = "a139019a-b2d5-40a8-939a-9ccf053d6455"
OTHER_ID = "76707cf2-ecbc-4cda-91bd-04e204b9556a"


def subject(**changes):
    return ExecutionSubject(**{
        "deployment_id": "qualification", "account_id": ACCOUNT_ID,
        "takeover_epoch": 1, "environment": "ALPACA_LIVE",
        "base_url": "https://api.alpaca.markets", **changes,
    })


def account(account_id=ACCOUNT_ID, **changes):
    return {"id": account_id, "account_number": "TEST-001", **changes}


def run(coroutine):
    return asyncio.run(coroutine)


def test_subject_is_versioned_frozen_and_environment_bound():
    live = subject()
    paper = subject(environment="ALPACA_PAPER", base_url="https://paper-api.alpaca.markets")
    assert live.broker == "alpaca"
    assert live.broker_account_id == ACCOUNT_ID
    assert live.subject_version == "native-read-subject/1"
    assert live.sha256 != paper.sha256
    canonical = json.dumps(live.to_dict(), sort_keys=True, separators=(",", ":"))
    assert live.sha256 == hashlib.sha256(canonical.encode()).hexdigest()
    with pytest.raises(ValidationError):
        live.account_id = OTHER_ID


@pytest.mark.parametrize("change", [
    {"extra": "field"}, {"broker": "other"}, {"subject_version": "native-read-subject/2"},
    {"account_id": " "}, {"account_id": "TEST-001"}, {"account_id": ACCOUNT_ID.upper()},
    {"deployment_id": " trailing "},
    {"takeover_epoch": 0}, {"takeover_epoch": True},
    {"environment": "ALPACA_PAPER"}, {"base_url": "https://api.alpaca.markets/"},
    {"base_url": "https://api.alpaca.markets:443"},
    {"base_url": "https://api.alpaca.markets.evil.example"},
    {"base_url": "https://user:secret@api.alpaca.markets"},
    {"base_url": "https://api.alpaca.markets?query"},
])
def test_subject_refuses_ambiguous_or_unbound_inputs(change):
    with pytest.raises((ValidationError, ValueError)):
        subject(**change)


def test_before_collection_and_end_account_identity_are_verified():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=account() if request.url.path == "/v2/account" else [])

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            async with ReadOnlyAlpacaClient(subject(), api_key="key", secret_key="secret", http_client=http) as client:
                assert await client.get("/v2/positions") == []
                identity = await client.verify_account()
                assert identity.account_id == ACCOUNT_ID
                assert identity.broker == "alpaca"
                assert client.requests_used == 3
                assert client.bytes_used > 0
            assert not http.is_closed

    run(exercise())
    assert [request.url.path for request in requests] == ["/v2/account", "/v2/positions", "/v2/account"]
    assert all(request.method == "GET" for request in requests)
    assert all(request.headers["accept-encoding"] == "identity" for request in requests)
    assert all(request.url.host == "api.alpaca.markets" for request in requests)


def test_mismatched_account_cannot_read_positions():
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json=account(OTHER_ID))

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = ReadOnlyAlpacaClient(subject(), api_key="key", secret_key="secret", http_client=http)
            with pytest.raises(NativeReadRefused, match="NATIVE_READ_ACCOUNT_MISMATCH"):
                await client.get("/v2/positions")
            with pytest.raises(NativeReadRefused, match="NATIVE_READ_CLIENT_CLOSED"):
                await client.verify_account()

    run(exercise())
    assert paths == ["/v2/account"]


@pytest.mark.parametrize("replacement", [account(OTHER_ID), account(account_number="TEST-002")])
def test_end_verification_detects_account_or_alias_change(replacement):
    calls = 0

    def handler(_request):
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=account() if calls == 1 else replacement)

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = ReadOnlyAlpacaClient(subject(), api_key="key", secret_key="secret", http_client=http)
            await client.verify_account()
            with pytest.raises(NativeReadRefused, match="NATIVE_READ_ACCOUNT_MISMATCH"):
                await client.verify_account()

    run(exercise())


@pytest.mark.parametrize("payload", [None, [], {}, {"id": 1}, {"id": ACCOUNT_ID, "account_number": ""},
                                     {"id": OTHER_ID, "account_number": ACCOUNT_ID},
                                     {"account_number": ACCOUNT_ID}])
def test_malformed_account_cannot_establish_identity(payload):
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200, content=json.dumps(payload)))) as http:
            client = ReadOnlyAlpacaClient(subject(), api_key="key", secret_key="secret", http_client=http)
            with pytest.raises(NativeReadRefused, match="NATIVE_READ_ACCOUNT_(MALFORMED|MISMATCH)"):
                await client.verify_account()

    run(exercise())


@pytest.mark.parametrize("path,params", [
    ("https://evil.example/v2/account", None), ("//evil.example/v2/account", None),
    ("/v2/account?redirect=https://evil.example", None), ("/v2/orders/../account", None),
    ("/v2/orders/" + ACCOUNT_ID + "/", None), ("/v2/orders/" + ACCOUNT_ID.upper(), None),
    ("/v2/account/activities/FILL", None), ("/v2/positions", {"after": "2026-10-16T00:00:00Z"}),
    ("/v2/orders", {"url": "https://evil.example"}),
    ("/v2/orders", {"after": "2026-10-16"}),
    ("/v2/orders", {"limit": True}), ("/v2/orders", {"limit": 501}),
    ("/v2/account/activities", {"page_size": 101}),
    ("/v2/account/activities", {"page_token": "../orders?after=escape"}),
    ("/v2/account/activities", {"page_token": "a\r\nsecret"}),
])
def test_route_and_parameter_escape_refused_before_transport(path, params):
    calls = []

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: calls.append(r))) as http:
            client = ReadOnlyAlpacaClient(subject(), api_key="key", secret_key="secret", http_client=http)
            with pytest.raises(NativeReadRefused, match="NATIVE_READ_(ROUTE|PARAMETERS)_REFUSED"):
                await client.get(path, params)

    run(exercise())
    assert calls == []


def test_native_order_uuid_and_activity_parameters_preserved():
    requests = []
    parameters = {"after": "2026-10-01T00:00:00Z", "until": "2026-10-16T23:59:59+00:00",
                  "direction": "asc", "page_size": 100, "page_token": "20261016::abc-123",
                  "activity_types": "FILL,DIV,FEE"}

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=account() if request.url.path == "/v2/account" else [])

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = ReadOnlyAlpacaClient(subject(), api_key="key", secret_key="secret", http_client=http)
            await client.get("/v2/orders/" + OTHER_ID)
            await client.get("/v2/account/activities", parameters)

    run(exercise())
    assert requests[1].url.path == "/v2/orders/" + OTHER_ID
    assert dict(requests[2].url.params) == {name: str(value) for name, value in parameters.items()}


def test_redirect_is_never_followed_even_on_injected_redirecting_client():
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(302, headers={"location": "https://evil.example/secret"})

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=True) as http:
            client = ReadOnlyAlpacaClient(subject(), api_key="key", secret_key="secret", http_client=http)
            with pytest.raises(NativeReadRefused, match="NATIVE_READ_HTTP_STATUS_REFUSED"):
                await client.verify_account()

    run(exercise())
    assert len(requests) == 1


class ChunkStream(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks
        self.yielded = 0

    async def __aiter__(self):
        for chunk in self.chunks:
            self.yielded += 1
            yield chunk


def test_streaming_and_total_byte_limits_are_enforced_without_content_length():
    stream = ChunkStream([b" " * 65536, b" " * 65536, b" " * 65536])

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200, stream=stream))) as http:
            client = ReadOnlyAlpacaClient(subject(), api_key="key", secret_key="secret", http_client=http,
                                         limits=ReadOnlyLimits(max_bytes=70000))
            with pytest.raises(NativeReadRefused, match="NATIVE_READ_BYTE_LIMIT_EXCEEDED"):
                await client.verify_account()
            assert client.bytes_used == 131072

    run(exercise())
    assert stream.yielded == 2


def test_content_length_cannot_allocate_beyond_total_budget():
    stream = ChunkStream([b" " * 1024])

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200, headers={"content-length": "1024"}, stream=stream))) as http:
            client = ReadOnlyAlpacaClient(subject(), api_key="key", secret_key="secret", http_client=http,
                                         limits=ReadOnlyLimits(max_bytes=100))
            with pytest.raises(NativeReadRefused, match="NATIVE_READ_BYTE_LIMIT_EXCEEDED"):
                await client.verify_account()
            assert client.bytes_used == 0

    run(exercise())
    assert stream.yielded == 0


def test_byte_budget_is_shared_across_account_and_collection():
    paths = []
    account_bytes = json.dumps(account()).encode()

    def handler(request):
        paths.append(request.url.path)
        body = account_bytes if request.url.path == "/v2/account" else b"[]"
        return httpx.Response(200, content=body)

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = ReadOnlyAlpacaClient(subject(), api_key="key", secret_key="secret", http_client=http,
                                         limits=ReadOnlyLimits(max_bytes=len(account_bytes) + 1))
            with pytest.raises(NativeReadRefused, match="NATIVE_READ_BYTE_LIMIT_EXCEEDED"):
                await client.get("/v2/positions")
            assert client.bytes_used == len(account_bytes)

    run(exercise())
    assert paths == ["/v2/account", "/v2/positions"]


def test_request_limit_includes_identity_brackets():
    paths = []

    def handler(request):
        paths.append(request.url.path)
        return httpx.Response(200, json=account())

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = ReadOnlyAlpacaClient(subject(), api_key="key", secret_key="secret", http_client=http,
                                         limits=ReadOnlyLimits(max_requests=1))
            with pytest.raises(NativeReadRefused, match="NATIVE_READ_REQUEST_LIMIT_EXCEEDED"):
                await client.get("/v2/positions")
            assert client.requests_used == 1

    run(exercise())
    assert paths == ["/v2/account"]


def test_absolute_deadline_and_clock_rollback_refuse_before_transport():
    async def exercise(values, code):
        clock = iter(values)
        client = ReadOnlyAlpacaClient(subject(), api_key="key", secret_key="secret", clock=lambda: next(clock),
                                     limits=ReadOnlyLimits(max_seconds=1))
        with pytest.raises(NativeReadRefused, match=code):
            await client.verify_account()
        assert client.requests_used == 0

    run(exercise([10, 11], "NATIVE_READ_DEADLINE_EXCEEDED"))
    run(exercise([10, 9], "NATIVE_READ_CLOCK_REFUSED"))


def test_per_request_timeout_bounds_injected_transport_and_sanitizes_exception():
    async def handler(_request):
        await asyncio.sleep(1)
        return httpx.Response(200, json=account())

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = ReadOnlyAlpacaClient(subject(), api_key="SECRETKEY", secret_key="SECRETSECRET", http_client=http,
                                         limits=ReadOnlyLimits(request_timeout=0.01))
            with pytest.raises(NativeReadRefused, match="^NATIVE_READ_TIMEOUT$") as raised:
                await client.verify_account()
            assert raised.value.__suppress_context__
            assert "SECRET" not in str(raised.value)

    run(exercise())


@pytest.mark.parametrize("response", [
    {"content": b'{"id":"one","id":"two"}'}, {"content": b'{"id":NaN}'},
    {"content": b"not json"}, {"content": b"\xff"},
    {"content": b"{}", "headers": {"content-length": "invalid"}},
])
def test_malformed_json_and_headers_refuse(response):
    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: httpx.Response(200, **response))) as http:
            client = ReadOnlyAlpacaClient(subject(), api_key="key", secret_key="secret", http_client=http)
            with pytest.raises(NativeReadRefused, match="^NATIVE_READ_RESPONSE_MALFORMED$"):
                await client.verify_account()

    run(exercise())


def test_compressed_response_cannot_bypass_decoded_byte_budget():
    import gzip

    async def exercise():
        response = httpx.Response(200, content=gzip.compress(b" " * 10000), headers={"content-encoding": "gzip"})
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _r: response)) as http:
            client = ReadOnlyAlpacaClient(subject(), api_key="key", secret_key="secret", http_client=http)
            with pytest.raises(NativeReadRefused, match="NATIVE_READ_RESPONSE_ENCODING_REFUSED"):
                await client.verify_account()

    run(exercise())


def test_transport_errors_do_not_disclose_native_headers_or_body():
    def handler(_request):
        raise RuntimeError("SECRETKEY native account body SECRETSECRET")

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
            client = ReadOnlyAlpacaClient(subject(), api_key="SECRETKEY", secret_key="SECRETSECRET", http_client=http)
            with pytest.raises(NativeReadRefused, match="^NATIVE_READ_TRANSPORT_REFUSED$") as raised:
                await client.verify_account()
            assert raised.value.__suppress_context__

    run(exercise())


def test_submit_and_cancel_are_unconditionally_refused_without_any_transport():
    calls = []

    async def exercise():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: calls.append(request))) as http:
            client = ReadOnlyAlpacaClient(subject(), api_key="key", secret_key="secret", http_client=http)
            for operation in (client.submit, client.cancel):
                with pytest.raises(NativeReadRefused, match="^NATIVE_READ_MUTATION_REFUSED$"):
                    await operation("arbitrary-native-order", paper_grant="forged")
            assert client.requests_used == 0

    run(exercise())
    assert calls == []


def test_closed_client_and_unvalidated_subject_are_refused():
    forged = subject().model_copy(update={"base_url": "https://evil.example"})
    with pytest.raises(NativeReadRefused, match="NATIVE_READ_SUBJECT_REQUIRED"):
        ReadOnlyAlpacaClient(forged, api_key="key", secret_key="secret")

    async def exercise():
        client = ReadOnlyAlpacaClient(subject(), api_key="key", secret_key="secret")
        await client.aclose()
        with pytest.raises(NativeReadRefused, match="NATIVE_READ_CLIENT_CLOSED"):
            await client.verify_account()

    run(exercise())
