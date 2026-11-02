"""Generated accepted-contract fixtures; never actual Alpaca qualification."""
from dataclasses import replace
from datetime import timedelta
from types import SimpleNamespace

from sentinel.execution.live_native_funding import (
    NATIVE_FUNDING_SCHEMA, NativeFundingContractAdmission, parse_alpaca_funding_facts,
)
from tests.sentinel.live_authority_fixtures import signed_live
from tests.sentinel.live_order_fixtures import NOW, funding, order_fixture


def native_fixture(**payload_changes):
    fixture = order_fixture()
    payload = {"id": fixture.subject.account_id, "currency": "USD",
        "cash": "1000", "buying_power": "1000", "non_marginable_buying_power": "800",
        "long_market_value": "0", "short_market_value": "0", **payload_changes}
    facts = parse_alpaca_funding_facts(payload, account=fixture.account,
        base_url=fixture.subject.base_url, observed_at=NOW)
    fixture.account = replace(fixture.account, native_funding=facts)
    generated = funding(fixture)
    root = replace(generated.root, not_before=NOW-timedelta(days=2), not_after=NOW+timedelta(days=40))
    claims = {"contract_id": "generated-offline-contract", "subject": fixture.subject.model_dump(mode="json"),
        "issued_at": (NOW-timedelta(days=1)).isoformat(), "not_before": (NOW-timedelta(minutes=1)).isoformat(),
        "expires_at": (NOW+timedelta(days=1)).isoformat(),
        "source_profile": "ALPACA_ACCOUNT_DECIMAL_FIELDS_V1", "endpoint_path": "/v2/account",
        "currency": "USD", "settled_cash_field": "non_marginable_buying_power",
        "spendable_cash_field": "buying_power",
        "reservation_contract": "BUYING_POWER_CEILING_AND_DURABLE_PROMISES_V1",
        "max_observation_age_seconds": 30,
        "qualification_receipts": generated.claims["qualification_receipts"]}
    admission = NativeFundingContractAdmission(
        signed_live(claims, generated.private_key, generated.key_id, schema=NATIVE_FUNDING_SCHEMA),
        {generated.key_id: root})
    return fixture, SimpleNamespace(admission=admission, claims=claims, payload=payload,
        private_key=generated.private_key, key_id=generated.key_id, root=root)


def resigned_native(source, **changes):
    return replace(source.admission, certificate=signed_live({**source.claims, **changes},
        source.private_key, source.key_id, schema=NATIVE_FUNDING_SCHEMA))
