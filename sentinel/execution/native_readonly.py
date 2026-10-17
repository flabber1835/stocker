from __future__ import annotations

import asyncio
from collections.abc import Mapping
from datetime import datetime
from decimal import Decimal
import hashlib
import json
import math
import re
import time
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sentinel.execution.contract import BrokerAccountIdentity
from sentinel.trading_environment import TradingEndpoint, TradingEnvironment


class NativeReadRefused(RuntimeError):
    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


class ExecutionSubject(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    subject_version: Literal["native-read-subject/1"] = "native-read-subject/1"
    broker: Literal["alpaca"] = "alpaca"
    deployment_id: str = Field(strict=True, min_length=1, max_length=256)
    account_id: str = Field(strict=True, min_length=1, max_length=256)
    takeover_epoch: int = Field(strict=True, gt=0)
    environment: TradingEnvironment
    base_url: str = Field(strict=True)

    @field_validator("deployment_id", "account_id")
    @classmethod
    def exact_identifier(cls, value: str) -> str:
        if value != value.strip() or any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError("an exact nonempty identifier is required")
        return value

    @field_validator("account_id")
    @classmethod
    def exact_native_account_id(cls, value: str) -> str:
        if str(UUID(value)) != value:
            raise ValueError("an exact native account UUID is required")
        return value

    @model_validator(mode="after")
    def exact_origin(self) -> ExecutionSubject:
        endpoint = TradingEndpoint.parse(self.base_url)
        if endpoint.base_url != self.base_url or endpoint.environment is not self.environment:
            raise ValueError("subject origin and environment must agree exactly")
        return self

    @property
    def broker_account_id(self) -> str:
        return self.account_id

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")

    @property
    def sha256(self) -> str:
        raw = json.dumps(self.to_dict(), sort_keys=True, separators=(",", ":"), allow_nan=False)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class ReadOnlyLimits(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_requests: int = Field(default=256, strict=True, ge=1, le=10000)
    max_bytes: int = Field(default=16 * 1024 * 1024, strict=True, ge=1, le=64 * 1024 * 1024)
    max_seconds: float = Field(default=60, gt=0, le=600, allow_inf_nan=False)
    request_timeout: float = Field(default=15, gt=0, le=60, allow_inf_nan=False)


_FIXED_PATHS = frozenset({
    "/v2/account", "/v2/positions", "/v2/orders",
    "/v2/account/activities", "/v2/clock",
})
_PARAMETERS = {
    "/v2/orders": frozenset({"status", "limit", "after", "until", "direction", "nested"}),
    "/v2/account/activities": frozenset({
        "activity_types", "after", "until", "direction", "page_size", "page_token",
    }),
}


def _request_parameters(path: str, params: Mapping | None) -> dict:
    if not isinstance(path, str):
        raise NativeReadRefused("NATIVE_READ_ROUTE_REFUSED")
    if path not in _FIXED_PATHS:
        order_id = path.removeprefix("/v2/orders/")
        try:
            valid = path == "/v2/orders/" + str(UUID(order_id))
        except (ValueError, AttributeError):
            valid = False
        if not valid:
            raise NativeReadRefused("NATIVE_READ_ROUTE_REFUSED")
    if params is None:
        return {}
    if not isinstance(params, dict) or set(params) - _PARAMETERS.get(path, frozenset()):
        raise NativeReadRefused("NATIVE_READ_PARAMETERS_REFUSED")
    result = {}
    for name, value in params.items():
        if type(value) not in (str, int):
            raise NativeReadRefused("NATIVE_READ_PARAMETERS_REFUSED")
        text = str(value)
        if not text or len(text) > 512 or any(ord(char) < 32 or ord(char) == 127 for char in text):
            raise NativeReadRefused("NATIVE_READ_PARAMETERS_REFUSED")
        if name in {"after", "until"}:
            try:
                instant = datetime.fromisoformat(text.replace("Z", "+00:00"))
                valid = instant.utcoffset() is not None
            except ValueError:
                valid = False
        elif name in {"limit", "page_size"}:
            maximum = 500 if name == "limit" else 100
            valid = bool(re.fullmatch(r"[1-9][0-9]*", text)) and int(text) <= maximum
        elif name == "direction":
            valid = text in {"asc", "desc"}
        elif name == "status":
            valid = text in {"open", "closed", "all"}
        elif name == "nested":
            valid = text in {"true", "false"}
        elif name == "activity_types":
            valid = bool(re.fullmatch(r"[A-Z][A-Z0-9_]{0,31}(,[A-Z][A-Z0-9_]{0,31})*", text))
        elif name == "page_token":
            valid = bool(re.fullmatch(r"[A-Za-z0-9_.:-]{1,256}", text))
        else:
            valid = False
        if not valid:
            raise NativeReadRefused("NATIVE_READ_PARAMETERS_REFUSED")
        result[name] = value
    return result


def _unique_object(pairs):
    result = {}
    for name, value in pairs:
        if name in result:
            raise ValueError("duplicate JSON field")
        result[name] = value
    return result


def _invalid_constant(_value):
    raise ValueError("nonfinite JSON number")


class ReadOnlyAlpacaClient:
    def __init__(self, subject: ExecutionSubject, *, api_key: str, secret_key: str,
                 limits: ReadOnlyLimits | None = None, clock=time.monotonic,
                 http_client=None) -> None:
        if not isinstance(subject, ExecutionSubject):
            raise NativeReadRefused("NATIVE_READ_SUBJECT_REQUIRED")
        for credential in (api_key, secret_key):
            if (not isinstance(credential, str) or not credential
                    or len(credential) > 1024 or credential != credential.strip()
                    or any(ord(char) < 33 or ord(char) == 127 for char in credential)):
                raise NativeReadRefused("NATIVE_READ_CREDENTIALS_REQUIRED")
        try:
            self._subject = ExecutionSubject.model_validate(subject.to_dict())
        except ValueError:
            raise NativeReadRefused("NATIVE_READ_SUBJECT_REQUIRED") from None
        self._limits = limits or ReadOnlyLimits()
        if not isinstance(self._limits, ReadOnlyLimits):
            raise NativeReadRefused("NATIVE_READ_LIMITS_REQUIRED")
        self._clock = clock
        self._started = self._instant()
        self._last_clock = self._started
        self._deadline = self._started + self._limits.max_seconds
        self._headers = {"APCA-API-KEY-ID": api_key, "APCA-API-SECRET-KEY": secret_key,
                         "Accept-Encoding": "identity"}
        self._http_client = http_client
        self._owns_client = http_client is None
        self._closed = False
        self._requests = 0
        self._bytes = 0
        self._account_evidence = None
        self._refused = False
        self._lock = asyncio.Lock()

    @property
    def subject(self) -> ExecutionSubject:
        return self._subject

    @property
    def requests_used(self) -> int:
        return self._requests

    @property
    def bytes_used(self) -> int:
        return self._bytes

    def _instant(self) -> float:
        try:
            value = float(self._clock())
        except Exception:
            raise NativeReadRefused("NATIVE_READ_CLOCK_REFUSED") from None
        if not math.isfinite(value):
            raise NativeReadRefused("NATIVE_READ_CLOCK_REFUSED")
        return value

    def _remaining(self) -> float:
        if self._closed or self._refused:
            raise NativeReadRefused("NATIVE_READ_CLIENT_CLOSED")
        now = self._instant()
        if now < self._last_clock:
            self._refused = True
            raise NativeReadRefused("NATIVE_READ_CLOCK_REFUSED")
        self._last_clock = now
        remaining = self._deadline - now
        if remaining <= 0:
            raise NativeReadRefused("NATIVE_READ_DEADLINE_EXCEEDED")
        return remaining

    def _account_identity(self, payload) -> BrokerAccountIdentity:
        if not isinstance(payload, dict):
            raise NativeReadRefused("NATIVE_READ_ACCOUNT_MALFORMED")
        identifiers = []
        for field in ("id", "account_number"):
            value = payload.get(field)
            if value is not None:
                if (not isinstance(value, str) or not value or value != value.strip()
                        or len(value) > 256
                        or any(ord(char) < 32 or ord(char) == 127 for char in value)):
                    raise NativeReadRefused("NATIVE_READ_ACCOUNT_MALFORMED")
                identifiers.append((field, value))
        evidence = tuple(identifiers)
        if (payload.get("id") != self.subject.account_id
                or (self._account_evidence is not None and self._account_evidence != evidence)):
            self._refused = True
            raise NativeReadRefused("NATIVE_READ_ACCOUNT_MISMATCH")
        self._account_evidence = evidence
        return BrokerAccountIdentity(broker="alpaca", account_id=self.subject.account_id, raw=payload)

    async def _request(self, path: str, params: dict):
        remaining = self._remaining()
        if self._requests >= self._limits.max_requests:
            raise NativeReadRefused("NATIVE_READ_REQUEST_LIMIT_EXCEEDED")
        if self._bytes >= self._limits.max_bytes:
            raise NativeReadRefused("NATIVE_READ_BYTE_LIMIT_EXCEEDED")
        if self._http_client is None:
            import httpx
            self._http_client = httpx.AsyncClient(follow_redirects=False, trust_env=False)
        self._requests += 1
        try:
            async with asyncio.timeout(min(remaining, self._limits.request_timeout)):
                async with self._http_client.stream(
                        "GET", self.subject.base_url + path, params=params,
                        headers=self._headers, follow_redirects=False,
                        timeout=min(remaining, self._limits.request_timeout)) as response:
                    if not 200 <= response.status_code < 300:
                        raise NativeReadRefused("NATIVE_READ_HTTP_STATUS_REFUSED")
                    if response.headers.get("content-encoding", "identity").lower() != "identity":
                        raise NativeReadRefused("NATIVE_READ_RESPONSE_ENCODING_REFUSED")
                    length = response.headers.get("content-length")
                    if length is not None:
                        if not re.fullmatch(r"[0-9]+", length):
                            raise NativeReadRefused("NATIVE_READ_RESPONSE_MALFORMED")
                        if int(length) > self._limits.max_bytes - self._bytes:
                            raise NativeReadRefused("NATIVE_READ_BYTE_LIMIT_EXCEEDED")
                    body = bytearray()
                    async for chunk in response.aiter_bytes(chunk_size=65536):
                        self._remaining()
                        self._bytes += len(chunk)
                        if self._bytes > self._limits.max_bytes:
                            raise NativeReadRefused("NATIVE_READ_BYTE_LIMIT_EXCEEDED")
                        body.extend(chunk)
                    self._remaining()
                    try:
                        return json.loads(body.decode("utf-8"), parse_float=Decimal,
                                          parse_constant=_invalid_constant,
                                          object_pairs_hook=_unique_object)
                    except (UnicodeError, ValueError, RecursionError):
                        raise NativeReadRefused("NATIVE_READ_RESPONSE_MALFORMED") from None
        except NativeReadRefused:
            raise
        except TimeoutError:
            raise NativeReadRefused("NATIVE_READ_TIMEOUT") from None
        except Exception:
            raise NativeReadRefused("NATIVE_READ_TRANSPORT_REFUSED") from None

    async def get(self, path: str, params: dict | None = None):
        parameters = _request_parameters(path, params)
        async with self._lock:
            if path != "/v2/account" and self._account_evidence is None:
                account = await self._request("/v2/account", {})
                self._account_identity(account)
            result = await self._request(path, parameters)
            if path == "/v2/account":
                self._account_identity(result)
            return result

    async def verify_account(self) -> BrokerAccountIdentity:
        return self._account_identity(await self.get("/v2/account"))

    async def submit(self, *args, **kwargs):
        raise NativeReadRefused("NATIVE_READ_MUTATION_REFUSED")

    async def cancel(self, *args, **kwargs):
        raise NativeReadRefused("NATIVE_READ_MUTATION_REFUSED")

    async def aclose(self) -> None:
        self._closed = True
        if self._owns_client and self._http_client is not None:
            await self._http_client.aclose()

    async def __aenter__(self) -> ReadOnlyAlpacaClient:
        self._remaining()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()
