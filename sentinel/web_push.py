"""First-party RFC 8291/8292 Web Push transport.

Endpoints and key material are secrets. Exceptions intentionally contain only
subscription digests, response classes, and HTTP status codes.
"""
from __future__ import annotations

import base64
import hashlib
import json
import re
import secrets
import time
from contextlib import closing
from dataclasses import dataclass
from typing import Callable, Mapping, Optional
from urllib.parse import urlsplit

import httpx
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


MAX_PAYLOAD_BYTES = 3000
RECORD_SIZE = 4096
_BASE64URL = re.compile(r"[A-Za-z0-9_-]+\Z")


def b64url_encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def b64url_decode(value: str) -> bytes:
    if not isinstance(value, str) or _BASE64URL.fullmatch(value) is None:
        raise ValueError("base64url value is not canonical URL-safe encoding")
    try:
        decoded = base64.b64decode(
            value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, TypeError) as exc:
        raise ValueError("invalid base64url value") from exc
    if b64url_encode(decoded) != value:
        raise ValueError("base64url value is not canonical URL-safe encoding")
    return decoded


def subscription_id(endpoint: str) -> str:
    return hashlib.sha256(
        ("sentinel.web-push-subscription/1\0" + endpoint)
        .encode("utf-8")).hexdigest()


def validate_subscription(endpoint: str, p256dh: str, auth: str) -> None:
    parsed = urlsplit(endpoint)
    if (parsed.scheme != "https" or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or len(endpoint) > 4096):
        raise ValueError("push endpoint must be a bounded HTTPS URL without userinfo")
    public_bytes = b64url_decode(p256dh)
    auth_bytes = b64url_decode(auth)
    if len(public_bytes) != 65 or public_bytes[0] != 4:
        raise ValueError("push p256dh must be an uncompressed P-256 public key")
    if len(auth_bytes) != 16:
        raise ValueError("push auth secret must be exactly 16 bytes")
    ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public_bytes)


@dataclass(frozen=True)
class VapidCredentials:
    private_key: ec.EllipticCurvePrivateKey
    public_key_bytes: bytes
    subject: str

    @classmethod
    def from_base64url(
            cls, *, private_key: str, public_key: str,
            subject: str) -> "VapidCredentials":
        private_bytes = b64url_decode(private_key)
        public_bytes = b64url_decode(public_key)
        if len(private_bytes) != 32:
            raise ValueError("VAPID private key must be a 32-byte scalar")
        if len(public_bytes) != 65 or public_bytes[0] != 4:
            raise ValueError("VAPID public key must be uncompressed P-256")
        normalized_subject = str(subject).strip()
        if not (normalized_subject.startswith("mailto:")
                or normalized_subject.startswith("https://")):
            raise ValueError("VAPID subject must use mailto: or https:")
        scalar = int.from_bytes(private_bytes, "big")
        if scalar == 0:
            raise ValueError("VAPID private scalar is invalid")
        private = ec.derive_private_key(scalar, ec.SECP256R1())
        derived = private.public_key().public_bytes(
            serialization.Encoding.X962,
            serialization.PublicFormat.UncompressedPoint)
        if not secrets.compare_digest(derived, public_bytes):
            raise ValueError("VAPID public/private keys do not match")
        return cls(private, public_bytes, normalized_subject)


def _jwt(credentials: VapidCredentials, endpoint: str, *, now: int) -> str:
    parsed = urlsplit(endpoint)
    audience = f"{parsed.scheme}://{parsed.netloc}"
    header = b64url_encode(json.dumps(
        {"alg": "ES256", "typ": "JWT"}, sort_keys=True,
        separators=(",", ":")).encode("ascii"))
    claims = b64url_encode(json.dumps(
        {"aud": audience, "exp": now + 12 * 60 * 60,
         "sub": credentials.subject}, sort_keys=True,
        separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header}.{claims}".encode("ascii")
    der = credentials.private_key.sign(
        signing_input, ec.ECDSA(hashes.SHA256()))
    r, s = decode_dss_signature(der)
    signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    return f"{header}.{claims}.{b64url_encode(signature)}"


def encrypt(
        payload: bytes, *, p256dh: str, auth: str,
        ephemeral_private_key: Optional[ec.EllipticCurvePrivateKey] = None,
        salt: Optional[bytes] = None) -> bytes:
    """Encrypt one bounded aes128gcm record as specified by RFC 8291."""
    if len(payload) > MAX_PAYLOAD_BYTES:
        raise ValueError("Web Push payload exceeds reviewed bound")
    ua_public_bytes = b64url_decode(p256dh)
    auth_secret = b64url_decode(auth)
    validate_subscription("https://validation.invalid/push", p256dh, auth)
    ua_public = ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256R1(), ua_public_bytes)
    ephemeral = ephemeral_private_key or ec.generate_private_key(ec.SECP256R1())
    as_public_bytes = ephemeral.public_key().public_bytes(
        serialization.Encoding.X962,
        serialization.PublicFormat.UncompressedPoint)
    shared_secret = ephemeral.exchange(ec.ECDH(), ua_public)
    key_info = b"WebPush: info\x00" + ua_public_bytes + as_public_bytes
    ikm = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=auth_secret,
        info=key_info).derive(shared_secret)
    record_salt = salt or secrets.token_bytes(16)
    if len(record_salt) != 16:
        raise ValueError("Web Push salt must be exactly 16 bytes")
    cek = HKDF(
        algorithm=hashes.SHA256(), length=16, salt=record_salt,
        info=b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(
        algorithm=hashes.SHA256(), length=12, salt=record_salt,
        info=b"Content-Encoding: nonce\x00").derive(ikm)
    plaintext = payload + b"\x02"
    ciphertext = AESGCM(cek).encrypt(nonce, plaintext, None)
    return (
        record_salt + RECORD_SIZE.to_bytes(4, "big")
        + bytes((len(as_public_bytes),)) + as_public_bytes + ciphertext)


def request_parts(
        *, endpoint: str, p256dh: str, auth: str, payload: Mapping,
        credentials: VapidCredentials, now: Optional[int] = None
        ) -> tuple[bytes, dict[str, str]]:
    validate_subscription(endpoint, p256dh, auth)
    raw = json.dumps(
        dict(payload), sort_keys=True, separators=(",", ":"),
        ensure_ascii=False).encode("utf-8")
    body = encrypt(raw, p256dh=p256dh, auth=auth)
    token = _jwt(credentials, endpoint, now=int(time.time()) if now is None else now)
    return body, {
        "Authorization": (
            f"vapid t={token}, k={b64url_encode(credentials.public_key_bytes)}"),
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
        "TTL": "86400",
        "Urgency": "high",
    }


class WebPushDeliveryFailure(RuntimeError):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = bool(retryable)


Sender = Callable[[str, bytes, Mapping[str, str], float], int]


def _default_sender(
        endpoint: str, body: bytes, headers: Mapping[str, str],
        timeout_seconds: float) -> int:
    with httpx.Client(timeout=timeout_seconds, follow_redirects=False) as client:
        response = client.post(endpoint, content=body, headers=dict(headers))
    return int(response.status_code)


def notification_payload(alert) -> dict:
    details = dict(alert.payload)
    if alert.event_type == "BROKER_FILL":
        side = str(details.get("side") or "FILL").upper()
        ticker = str(details.get("ticker") or details.get("security_id") or "")
        title = f"{side} {ticker} filled".strip()
        body = (
            f"{details.get('quantity')} @ ${details.get('price')} · "
            f"{details.get('filled_at')}")
    elif alert.event_type == "PUSH_ENROLLMENT_TEST":
        title = "Caesar's Palace notifications enabled"
        body = "Test notification requested from this device."
    else:
        critical = str(alert.severity).upper() == "CRITICAL"
        title = (
            "Caesar's Palace — action required" if critical
            else "Caesar's Palace — automatic recovery")
        body = str(
            details.get("reason") or details.get("detail")
            or alert.event_type)[:240]
    return {
        "schema": "caesars-palace.web-push/1",
        "alert_id": alert.alert_id,
        "title": title,
        "body": body,
        "tag": alert.alert_id,
        "url": "/",
        "icon": "/static/caesars-palace-192.png",
        "badge": "/static/caesars-palace-192.png",
    }


class WebPushAlertAdapter:
    """Retry-safe, per-device fan-out behind one durable outbox claim."""

    def __init__(
            self, *, connection_factory, credentials: VapidCredentials,
            timeout_seconds: float = 10.0,
            sender: Optional[Sender] = None) -> None:
        if not callable(connection_factory):
            raise TypeError("connection_factory must be callable")
        if timeout_seconds <= 0 or timeout_seconds > 30:
            raise ValueError("Web Push timeout must be in (0,30]")
        self._connection_factory = connection_factory
        self._credentials = credentials
        self._timeout = timeout_seconds
        self._sender = sender or _default_sender

    def _initialize_fanout(self, alert) -> tuple[int, bool]:
        target = (
            str(alert.payload.get("subscription_id") or "")
            if alert.event_type == "PUSH_ENROLLMENT_TEST" else "")
        with closing(self._connection_factory()) as conn:
            try:
                with conn.cursor() as cur:
                    cur.execute(
                        "INSERT INTO sentinel_web_push_fanouts"
                        " (alert_id,recipient_count,delivery_required)"
                        " SELECT %s,COUNT(s.subscription_id),"
                        "        (%s >= p.web_push_activated_at)"
                        " FROM sentinel_notification_policy p"
                        " LEFT JOIN sentinel_web_push_subscriptions s"
                        "   ON s.retired_at IS NULL"
                        "  AND (%s='' OR s.subscription_id=%s)"
                        "  AND s.created_at<=%s"
                        "  AND %s >= p.web_push_activated_at"
                        " WHERE p.id=1"
                        " GROUP BY p.web_push_activated_at"
                        " ON CONFLICT (alert_id) DO NOTHING"
                        " RETURNING recipient_count,delivery_required",
                        (alert.alert_id, alert.created_at, target, target,
                         alert.created_at, alert.created_at))
                    created = cur.fetchone()
                    if created is not None and bool(created[1]):
                        cur.execute(
                            "INSERT INTO sentinel_web_push_deliveries"
                            " (alert_id,subscription_id,state)"
                            " SELECT %s,subscription_id,'PENDING'"
                            " FROM sentinel_web_push_subscriptions"
                            " WHERE retired_at IS NULL"
                            " AND (%s='' OR subscription_id=%s)"
                            " AND created_at<=%s"
                            " ORDER BY subscription_id",
                            (alert.alert_id, target, target,
                             alert.created_at))
                    cur.execute(
                        "SELECT recipient_count,delivery_required"
                        " FROM sentinel_web_push_fanouts"
                        " WHERE alert_id=%s", (alert.alert_id,))
                    row = cur.fetchone()
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        if row is None:
            raise RuntimeError("Web Push notification policy singleton is absent")
        return int(row[0]), bool(row[1])

    def _recipients(self, alert_id: str) -> list[tuple]:
        with closing(self._connection_factory()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT d.subscription_id,s.endpoint,s.p256dh,s.auth,"
                    " s.retired_at FROM sentinel_web_push_deliveries d"
                    " JOIN sentinel_web_push_subscriptions s"
                    "   ON s.subscription_id=d.subscription_id"
                    " WHERE d.alert_id=%s AND d.state='PENDING'"
                    " ORDER BY d.subscription_id", (alert_id,))
                return list(cur.fetchall())

    def _record(
            self, *, alert_id: str, sub_id: str, state: str,
            status_code: Optional[int], error: Optional[str],
            retire_subscription: bool = False,
            retire_reason: Optional[str] = None, claim=None, claim_seconds=60) -> None:
        with closing(self._connection_factory()) as conn:
            try:
                if claim is not None:
                    from sentinel.automation.outbox import renew_claim
                    renew_claim(conn, alert=claim, claim_seconds=claim_seconds)
                with conn.cursor() as cur:
                    if retire_subscription:
                        cur.execute(
                            "UPDATE sentinel_web_push_subscriptions"
                            " SET retired_at=COALESCE(retired_at,clock_timestamp()),"
                            " retire_reason=COALESCE(retire_reason,%s)"
                            " WHERE subscription_id=%s",
                            (retire_reason or f"push service HTTP {status_code}",
                             sub_id))
                    cur.execute(
                        "UPDATE sentinel_web_push_subscriptions SET"
                        " last_successful_push_at=CASE WHEN %s::text='DELIVERED'"
                        "   THEN clock_timestamp() ELSE last_successful_push_at END,"
                        " last_failed_push_at=CASE WHEN %s::text IS NOT NULL"
                        "   THEN clock_timestamp() ELSE last_failed_push_at END"
                        " WHERE subscription_id=%s",
                        (state, error, sub_id))
                    cur.execute(
                        "UPDATE sentinel_web_push_deliveries"
                        " SET state=%s,attempt_count=attempt_count+1,"
                        " last_status_code=%s,last_error=%s,"
                        " delivered_at=CASE WHEN %s='DELIVERED'"
                        " THEN clock_timestamp() ELSE NULL END,"
                        " updated_at=clock_timestamp()"
                        " WHERE alert_id=%s AND subscription_id=%s"
                        " AND state='PENDING'",
                        (state, status_code, error, state, alert_id, sub_id))
                conn.commit()
            except BaseException:
                conn.rollback()
                raise

    def _fanout_counts(self, alert_id: str) -> dict[str, int]:
        with closing(self._connection_factory()) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT state,COUNT(*) FROM sentinel_web_push_deliveries"
                    " WHERE alert_id=%s GROUP BY state", (alert_id,))
                return {str(state): int(count) for state, count in cur.fetchall()}

    def deliver_fenced(self, alert, idempotency_key: str, *, claim_seconds: int):
        if claim_seconds <= self._timeout:
            raise ValueError('alert claim must exceed one bounded push request')
        return self.deliver(alert, idempotency_key, claim_seconds=claim_seconds, claimed=True)

    def deliver(self, alert, idempotency_key: str, *, claim_seconds=60, claimed=False) -> None:
        del idempotency_key  # alert_id is the immutable notification tag
        def record(**kwargs):
            self._record(**kwargs, claim=alert if claimed else None, claim_seconds=claim_seconds)
        if (str(alert.severity).upper() == "INFO"
                and alert.event_type != "PUSH_ENROLLMENT_TEST"):
            # Webhook-era informational rows may still exist in the durable
            # outbox. Consume them successfully without initializing fan-out:
            # quiet green must not become either a push or a dead letter.
            return
        recipient_count, delivery_required = self._initialize_fanout(alert)
        if not delivery_required:
            # The migration boundary is durable. Quietly close historical
            # webhook-era rows instead of replaying them to a newly enrolled
            # Home Screen app.
            return
        if recipient_count == 0:
            raise WebPushDeliveryFailure(
                "no active Web Push subscriptions", retryable=False)
        payload = notification_payload(alert)
        failures: list[tuple[str, bool]] = []
        for sub_id, endpoint, p256dh, auth, retired_at in self._recipients(
                alert.alert_id):
            if claimed:
                from sentinel.automation.outbox import renew_claim
                with closing(self._connection_factory()) as conn:
                    renew_claim(conn, alert=alert, claim_seconds=claim_seconds)
                    conn.commit()
            if retired_at is not None:
                record(
                    alert_id=alert.alert_id, sub_id=str(sub_id),
                    state="RETIRED", status_code=None,
                    error="subscription retired before delivery")
                continue
            try:
                body, headers = request_parts(
                    endpoint=str(endpoint), p256dh=str(p256dh), auth=str(auth),
                    payload=payload, credentials=self._credentials)
                status = self._sender(
                    str(endpoint), body, headers, self._timeout)
                if isinstance(status, bool) or not isinstance(status, int):
                    raise ValueError("Web Push sender returned no HTTP status")
            except ValueError:
                message = f"{sub_id}: invalid subscription evidence"
                record(
                    alert_id=alert.alert_id, sub_id=str(sub_id), state="RETIRED",
                    status_code=None, error=message, retire_subscription=True,
                    retire_reason="invalid subscription evidence")
                continue
            except Exception as exc:                              # noqa: BLE001
                message = f"{sub_id}: transport {type(exc).__name__}"
                record(
                    alert_id=alert.alert_id, sub_id=str(sub_id), state="PENDING",
                    status_code=None, error=message)
                failures.append((message, True))
                continue
            if 200 <= status < 300:
                record(
                    alert_id=alert.alert_id, sub_id=str(sub_id),
                    state="DELIVERED", status_code=status, error=None)
            elif status in {404, 410}:
                record(
                    alert_id=alert.alert_id, sub_id=str(sub_id), state="RETIRED",
                    status_code=status, error=f"push service HTTP {status}",
                    retire_subscription=True)
            else:
                retryable = status in {408, 425, 429} or status >= 500
                message = f"{sub_id}: push service HTTP {status}"
                record(
                    alert_id=alert.alert_id, sub_id=str(sub_id), state="PENDING",
                    status_code=status, error=message)
                failures.append((message, retryable))
        if failures:
            retryable = all(item[1] for item in failures)
            raise WebPushDeliveryFailure(
                f"{len(failures)} Web Push recipient(s) failed",
                retryable=retryable)
        counts = self._fanout_counts(alert.alert_id)
        if counts.get("DELIVERED", 0) == 0:
            raise WebPushDeliveryFailure(
                "all captured Web Push subscriptions were retired",
                retryable=False)


__all__ = [
    "MAX_PAYLOAD_BYTES", "VapidCredentials", "WebPushAlertAdapter",
    "WebPushDeliveryFailure", "b64url_decode", "b64url_encode", "encrypt",
    "notification_payload", "request_parts", "subscription_id",
    "validate_subscription",
]
