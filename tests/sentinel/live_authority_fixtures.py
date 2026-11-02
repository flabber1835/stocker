"""Generated, in-memory offline issuer for LIVE software boundary tests only."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sentinel.authority.canonical import _b64url_encode, canonical_json_bytes, key_id_for_public_key
from sentinel.authority.live import (
    LIVE_CERTIFICATE_SCHEMA, LIVE_QUALIFICATION_FIELDS, LiveAdapterAdmission,
    LiveAuthorityContext, LiveTrustRoot,
)
from sentinel.execution.native_readonly import ExecutionSubject


def signed_live(claims, private_key, key_id, *, schema=LIVE_CERTIFICATE_SCHEMA):
    unsigned = {"schema": schema, "algorithm": "Ed25519", "key_id": key_id, "claims": claims}
    return canonical_json_bytes({
        **unsigned, "signature": _b64url_encode(private_key.sign(canonical_json_bytes(unsigned))),
    })


def live_fixture(now=None, *, operations=("READ", "SUBMIT", "CANCEL", "AUTOMATION"), **subject_changes):
    now = datetime.now(timezone.utc) if now is None else now
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key_id = key_id_for_public_key(public_key)
    subject = ExecutionSubject(**{
        "deployment_id": "offline-live-tests", "account_id": "11111111-1111-1111-1111-111111111111",
        "takeover_epoch": 1, "environment": "ALPACA_LIVE", "base_url": "https://api.alpaca.markets",
        **subject_changes,
    })
    bindings = {
        "runtime_image_digest": "sha256:" + "a" * 64,
        "sentinel_source_sha256": "b" * 64,
        "runtime_identity_sha256": "c" * 64,
        "strategy_identity_sha256": "d" * 64,
        "execution_config_sha256": "e" * 64,
    }
    claims = {
        "certificate_id": "generated-offline-live-test",
        "issued_at": (now - timedelta(minutes=1)).isoformat(),
        "not_before": (now - timedelta(minutes=1)).isoformat(),
        "expires_at": (now + timedelta(hours=1)).isoformat(),
        "subject": subject.model_dump(mode="json"), "runtime_bindings": dict(bindings),
        "limits": {"max_capital": "10000", "max_order_principal": "1000",
                   "max_daily_buy_commitment": "3000", "max_buy_premium_bps": 100},
        "qualification_receipts": {name: "f" * 64 for name in LIVE_QUALIFICATION_FIELDS},
        "permitted_operations": list(operations),
    }
    roots = {key_id: LiveTrustRoot(public_key, now - timedelta(days=1), now + timedelta(days=1), status="ENROLLED")}
    context = LiveAuthorityContext(subject, dict(bindings))
    admission = LiveAdapterAdmission(signed_live(claims, private_key, key_id), context, roots)
    return SimpleNamespace(now=now, private_key=private_key, public_key=public_key, key_id=key_id,
                           subject=subject, bindings=bindings, claims=claims, roots=roots,
                           context=context, admission=admission)
