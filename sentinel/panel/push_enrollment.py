"""Narrow non-financial browser write boundary for Web Push subscriptions."""
from __future__ import annotations

import json
import os
import re
from contextlib import closing
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from sentinel.automation import outbox
from sentinel.panel.sources import _bounded_dsn
from sentinel.web_push import b64url_decode, subscription_id, validate_subscription


router = APIRouter()
_TEST_ID = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def _public_origin() -> str:
    value = os.environ.get("SENTINEL_PUBLIC_ORIGIN", "").strip().rstrip("/")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or parsed.path or parsed.query or parsed.fragment):
        raise RuntimeError("SENTINEL_PUBLIC_ORIGIN must be one HTTPS origin")
    return value


def _database_url() -> str:
    value = os.environ.get("SENTINEL_DATABASE_URL", "").strip()
    if not value:
        raise RuntimeError("SENTINEL_DATABASE_URL is unset")
    return value


def _require_same_origin(request: Request) -> None:
    try:
        expected = _public_origin()
    except RuntimeError as exc:
        raise HTTPException(503, "push enrollment is not configured") from exc
    if request.headers.get("origin", "").rstrip("/") != expected:
        raise HTTPException(403, "push enrollment requires the configured origin")


async def _body(request: Request) -> dict:
    length = request.headers.get("content-length")
    if length is not None:
        try:
            if int(length) > 12_000:
                raise HTTPException(413, "push enrollment body is too large")
        except ValueError as exc:
            raise HTTPException(400, "invalid content length") from exc
    raw = await request.body()
    if len(raw) > 12_000:
        raise HTTPException(413, "push enrollment body is too large")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(400, "invalid push enrollment JSON") from exc
    if not isinstance(value, dict):
        raise HTTPException(400, "invalid push enrollment object")
    return value


def _subscription(value: dict) -> tuple[str, str, str]:
    endpoint = value.get("endpoint")
    keys = value.get("keys")
    if (not isinstance(endpoint, str) or not isinstance(keys, dict)
            or not isinstance(keys.get("p256dh"), str)
            or not isinstance(keys.get("auth"), str)):
        raise ValueError("subscription is incomplete")
    p256dh, auth = keys["p256dh"], keys["auth"]
    validate_subscription(endpoint, p256dh, auth)
    return endpoint, p256dh, auth


def _previous_endpoint(value) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("previous subscription endpoint is invalid")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname
            or parsed.username is not None or parsed.password is not None
            or len(value) > 4096):
        raise ValueError("previous subscription endpoint is invalid")
    return value


def _upsert_subscription(
        cur, *, endpoint: str, p256dh: str, auth: str,
        user_agent: str) -> str:
    sub_id = subscription_id(endpoint)
    cur.execute(
        "INSERT INTO sentinel_web_push_subscriptions"
        " (subscription_id,endpoint,p256dh,auth,user_agent)"
        " VALUES (%s,%s,%s,%s,%s)"
        " ON CONFLICT (subscription_id) DO UPDATE SET"
        " endpoint=EXCLUDED.endpoint,p256dh=EXCLUDED.p256dh,"
        " auth=EXCLUDED.auth,user_agent=EXCLUDED.user_agent,"
        " created_at=CASE WHEN"
        " sentinel_web_push_subscriptions.retired_at IS NOT NULL"
        " THEN clock_timestamp() ELSE"
        " sentinel_web_push_subscriptions.created_at END,"
        " refreshed_at=clock_timestamp(),retired_at=NULL,"
        " retire_reason=NULL",
        (sub_id, endpoint, p256dh, auth, user_agent[:512]))
    return sub_id


@router.get("/push/config")
def push_config() -> JSONResponse:
    public = os.environ.get("SENTINEL_WEB_PUSH_VAPID_PUBLIC_KEY", "").strip()
    try:
        key = b64url_decode(public)
        if len(key) != 65 or key[0] != 4:
            raise ValueError("wrong P-256 key shape")
    except ValueError as exc:
        raise HTTPException(503, "Web Push public key is not configured") from exc
    return JSONResponse(
        {"applicationServerKey": public},
        headers={"Cache-Control": "no-store"})


@router.post("/push/subscriptions")
async def enroll(request: Request) -> JSONResponse:
    _require_same_origin(request)
    value = await _body(request)
    try:
        endpoint, p256dh, auth = _subscription(value)
        test_id = str(value.get("test_id") or "").lower()
        if _TEST_ID.fullmatch(test_id) is None:
            raise ValueError("test id is not a UUID v4")
    except ValueError as exc:
        # Never echo the endpoint or key input in a validation response.
        raise HTTPException(400, "invalid Web Push subscription") from exc
    sub_id = subscription_id(endpoint)
    from sentinel.feed import store as feed_store
    try:
        with closing(feed_store.connect(_bounded_dsn(_database_url()))) as conn:
            with conn.cursor() as cur:
                _upsert_subscription(
                    cur, endpoint=endpoint, p256dh=p256dh, auth=auth,
                    user_agent=request.headers.get("user-agent", ""))
            outbox.enqueue(
                conn,
                idempotency_key=f"push-enrollment-test:{sub_id}:{test_id}",
                event_type="PUSH_ENROLLMENT_TEST", severity="INFO",
                payload={"subscription_id": sub_id, "test_id": test_id},
                max_attempts=3)
    except HTTPException:
        raise
    except Exception as exc:                                  # noqa: BLE001
        raise HTTPException(
            503, f"push enrollment unavailable: {type(exc).__name__}") from exc
    return JSONResponse(
        {"status": "subscribed", "subscription_id": sub_id},
        status_code=201, headers={"Cache-Control": "no-store"})


@router.post("/push/subscriptions/refresh")
async def refresh(request: Request) -> JSONResponse:
    """Replace only a browser notification capability; queue no test push."""
    _require_same_origin(request)
    value = await _body(request)
    try:
        raw_subscription = value.get("subscription")
        if not isinstance(raw_subscription, dict):
            raise ValueError("replacement subscription is incomplete")
        endpoint, p256dh, auth = _subscription(raw_subscription)
        previous = _previous_endpoint(value.get("previous_endpoint"))
    except ValueError as exc:
        raise HTTPException(400, "invalid Web Push subscription") from exc
    from sentinel.feed import store as feed_store
    try:
        with closing(feed_store.connect(_bounded_dsn(_database_url()))) as conn:
            with conn.cursor() as cur:
                sub_id = _upsert_subscription(
                    cur, endpoint=endpoint, p256dh=p256dh, auth=auth,
                    user_agent=request.headers.get("user-agent", ""))
                if previous is not None and previous != endpoint:
                    cur.execute(
                        "UPDATE sentinel_web_push_subscriptions"
                        " SET retired_at=COALESCE(retired_at,clock_timestamp()),"
                        " retire_reason=COALESCE("
                        " retire_reason,'replaced by browser')"
                        " WHERE subscription_id=%s AND subscription_id<>%s",
                        (subscription_id(previous), sub_id))
            conn.commit()
    except Exception as exc:                                  # noqa: BLE001
        raise HTTPException(
            503, f"push refresh unavailable: {type(exc).__name__}") from exc
    return JSONResponse(
        {"status": "refreshed", "subscription_id": sub_id},
        headers={"Cache-Control": "no-store"})


@router.post("/push/subscriptions/remove")
async def remove(request: Request) -> JSONResponse:
    _require_same_origin(request)
    value = await _body(request)
    endpoint = value.get("endpoint")
    if not isinstance(endpoint, str) or len(endpoint) > 4096:
        raise HTTPException(400, "invalid Web Push subscription")
    sub_id = subscription_id(endpoint)
    from sentinel.feed import store as feed_store
    try:
        with closing(feed_store.connect(_bounded_dsn(_database_url()))) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE sentinel_web_push_subscriptions"
                    " SET retired_at=COALESCE(retired_at,clock_timestamp()),"
                    " retire_reason=COALESCE(retire_reason,'removed by device')"
                    " WHERE subscription_id=%s", (sub_id,))
            conn.commit()
    except Exception as exc:                                  # noqa: BLE001
        raise HTTPException(
            503, f"push removal unavailable: {type(exc).__name__}") from exc
    return JSONResponse(
        {"status": "removed", "subscription_id": sub_id},
        headers={"Cache-Control": "no-store"})


__all__ = ["router"]
