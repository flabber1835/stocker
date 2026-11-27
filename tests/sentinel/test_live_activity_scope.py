"""The exact LIVE account stream requires its own currently signed permission."""
from dataclasses import replace
from datetime import timedelta
from uuid import uuid4

import httpx
import pytest

from sentinel.execution.alpaca_asset_id import AssetIdAlpacaExecutionBroker
from sentinel.execution.alpaca import MalformedBrokerPayload
from sentinel.execution.guarded import BrokerAuthorityRefused
from tests.sentinel.live_authority_fixtures import live_fixture, signed_live


ACTIVITY_PATH = "/v2beta1/events/activities"


def test_plain_live_read_leaves_activity_capability_off():
    f = live_fixture(operations=("READ",))
    adapter = AssetIdAlpacaExecutionBroker(api_key="mock", secret_key="mock",
        base_url=f.subject.base_url, live_admission=f.admission)
    assert not adapter.financial_activity_sse
    assert not adapter.capabilities.account_cash_activity_evidence


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", [None, "withdraw_permission", "different_account"])
async def test_live_stream_is_account_bracketed_and_checks_current_scope(fault):
    f = live_fixture(operations=("READ", "ACTIVITY_READ"), account_id=str(uuid4()))
    document = [f.admission.certificate]
    reads = []

    def handle(request):
        assert request.url.host == "api.alpaca.markets" and request.method == "GET"
        reads.append(request.url.path)
        if request.url.path == "/v2/account":
            account_id = str(uuid4()) if fault == "different_account" else f.subject.account_id
            return httpx.Response(200, json={"id": account_id,
                "account_number": "offline-live", "created_at": "2026-11-01T00:00:00Z"})
        assert request.url.path == ACTIVITY_PATH
        if fault == "withdraw_permission":
            document[0] = signed_live(dict(f.claims, permitted_operations=["READ"]),
                                      f.private_key, f.key_id)
        return httpx.Response(200, text="")

    class Http:
        @staticmethod
        def AsyncClient(**kwargs):
            return httpx.AsyncClient(transport=httpx.MockTransport(handle), trust_env=False, **kwargs)

    adapter = AssetIdAlpacaExecutionBroker(api_key="mock", secret_key="mock",
        base_url=f.subject.base_url, http_provider=lambda: Http,
        live_admission=replace(f.admission, certificate_provider=lambda: document[0]))
    assert adapter.financial_activity_sse and adapter.capabilities.account_cash_activity_evidence
    args = dict(after=f.now - timedelta(days=1), through=f.now)
    if fault == "withdraw_permission":
        with pytest.raises(BrokerAuthorityRefused, match="fresh LIVE transport admission refused"):
            await adapter.account_cash_activities(**args)
        assert reads == ["/v2/account", ACTIVITY_PATH, "/v2/account"]
    elif fault == "different_account":
        with pytest.raises(MalformedBrokerPayload, match="differs from the signed LIVE account"):
            await adapter.account_cash_activities(**args)
        assert reads == ["/v2/account"]
    else:
        batch = await adapter.account_cash_activities(**args)
        assert batch.activities == () and batch.processed_through == f.now
        assert reads == ["/v2/account", ACTIVITY_PATH, "/v2/account", ACTIVITY_PATH, "/v2/account"]
