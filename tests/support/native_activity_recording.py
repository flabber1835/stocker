from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any, Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from sentinel.execution.native_readonly import ExecutionSubject
from sentinel.trading_environment import TradingEnvironment


FIXTURE_KEY = "native-offline-key"
FIXTURE_SECRET = "native-offline-secret"
AFTER = datetime(2026, 10, 16, 0, 0, tzinfo=timezone.utc)
THROUGH = datetime(2026, 10, 17, 0, 0, tzinfo=timezone.utc)
ACCOUNT_UUID = "00000000-0000-4000-8000-000000000001"
ORDER_UUID = "00000000-0000-4000-8000-000000000002"
ASSET_UUID = "00000000-0000-4000-8000-000000000003"
SCENARIO_IDS = (
    "valid-native-fill", "dividend-fee-transfer", "tied-created-at",
    "duplicate-replay", "same-id-changed", "unknown-event",
    "correction-quarantine", "security-transfer-quarantine",
    "truncated-pagination", "cursor-cycle", "wrong-account",
    "malformed-decimal", "empty-history", "late-business-time",
    "exact-order-enrichment", "mismatched-exact-order",
)


def wire_json(value) -> str:
    if value is None or isinstance(value, (str, bool)) or type(value) is int:
        return json.dumps(value, ensure_ascii=True, allow_nan=False)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("NONFINITE_RECORDING_NUMBER")
        token = str(value)
        return token if any(char in token for char in ".eE") else token + "e0"
    if isinstance(value, list):
        return "[" + ",".join(wire_json(item) for item in value) + "]"
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return "{" + ",".join(json.dumps(key) + ":" + wire_json(item) for key, item in value.items()) + "}"
    raise ValueError("NON_EXACT_RECORDING_JSON")


def _unique_fields(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("DUPLICATE_RECORDING_FIELD")
        result[key] = value
    return result


def _nonfinite(_value):
    raise ValueError("NONFINITE_RECORDING_NUMBER")


class RecordedExchange(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    method: Literal["GET"] = "GET"
    path: str
    params: tuple[tuple[str, str], ...] = ()
    status: int = Field(default=200, ge=200, le=599)
    payload: Any

    @field_validator("path")
    @classmethod
    def fixed_path(cls, value):
        if not value.startswith("/v2/") or any(char in value for char in ("?", "#", "\\")):
            raise ValueError("RECORDING_PATH_REFUSED")
        return value

    @field_validator("payload")
    @classmethod
    def json_payload(cls, value):
        if not isinstance(value, (dict, list)):
            raise ValueError("RECORDING_PAYLOAD_REFUSED")
        wire_json(value)
        return value


class ActivityRecording(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)
    schema_version: Literal["sentinel.native-activity-recording/1"] = Field(alias="schema")
    provenance: Literal["SIMULATION_ONLY", "RECORDED_REPLAY"]
    subject: ExecutionSubject
    after: datetime
    through: datetime
    page_size: int = Field(default=100, ge=1, le=100, strict=True)
    exchanges: tuple[RecordedExchange, ...] = Field(min_length=2, max_length=256)

    @model_validator(mode="after")
    def bounded_interval(self):
        if self.after.tzinfo is None or self.through.tzinfo is None or self.after >= self.through:
            raise ValueError("RECORDING_INTERVAL_REFUSED")
        return self


def fixture_subject() -> ExecutionSubject:
    return ExecutionSubject(deployment_id="native-offline", account_id=ACCOUNT_UUID,
                            takeover_epoch=1, environment=TradingEnvironment.LIVE,
                            base_url="https://api.alpaca.markets")


def account_payload(account_id=ACCOUNT_UUID) -> dict:
    return dict(id=account_id, account_number="fixture-account",
                cash="0", equity="0", buying_power="0", multiplier="1", status="ACTIVE",
                trading_blocked=False, account_blocked=False, trade_suspended_by_user=False)


def fill_payload(activity_id="activity-1", **updates) -> dict:
    return dict(id=activity_id, activity_type="FILL", order_id=ORDER_UUID,
                asset_id=ASSET_UUID, side="buy", qty="2", price="10.25",
                transaction_time="2026-10-16T14:31:00+00:00",
                created_at="2026-10-16T14:32:00+00:00") | updates


def cash_payload(activity_id, kind="DIV", **updates) -> dict:
    return dict(id=activity_id, activity_type=kind, date="2026-10-16", net_amount="1.25",
                created_at="2026-10-16T15:00:00+00:00") | updates


def order_payload(**updates) -> dict:
    return dict(id=ORDER_UUID, asset_id=ASSET_UUID, side="buy", filled_qty="2", filled_avg_price="10.25",
                submitted_at="2026-10-16T14:30:00+00:00",
                filled_at="2026-10-16T14:31:00+00:00", account_id=ACCOUNT_UUID,
                client_order_id="fixture-client-key") | updates


def load_recording(path: Path, expected_sha256: str) -> ActivityRecording:
    with path.open("rb") as handle:
        payload = handle.read(16 * 1024 * 1024 + 1)
    if len(payload) > 16 * 1024 * 1024:
        raise ValueError("RECORDING_RESOURCE_LIMIT")
    if hashlib.sha256(payload).hexdigest() != expected_sha256:
        raise ValueError("RECORDING_HASH_MISMATCH")
    decoded = json.loads(payload, parse_float=Decimal, parse_constant=_nonfinite,
                         object_pairs_hook=_unique_fields)
    return ActivityRecording.model_validate(decoded)


def recording_bytes(recording: ActivityRecording) -> bytes:
    document = dict(schema=recording.schema_version, provenance=recording.provenance,
                    subject=recording.subject.to_dict(), after=recording.after.isoformat(),
                    through=recording.through.isoformat(), page_size=recording.page_size,
                    exchanges=[dict(method=item.method, path=item.path, params=[list(pair) for pair in item.params],
                                    status=item.status, payload=item.payload) for item in recording.exchanges])
    return wire_json(document).encode()


def history_params(*, page_size=2, token=None) -> tuple[tuple[str, str], ...]:
    result = dict(after=AFTER.isoformat(), until=THROUGH.isoformat(), direction="asc", page_size=str(page_size))
    if token is not None:
        result["page_token"] = token
    return tuple(result.items())


def scenario_recording(name: str):
    from sentinel.execution.alpaca_history import HistoryLimits
    from sentinel.execution.native_activity import normalize_activity

    if name not in SCENARIO_IDS:
        raise ValueError("UNKNOWN_MANDATORY_SCENARIO")
    rows = [fill_payload()]
    order = order_payload()
    pages = None
    prior = ()
    max_pages = 4
    final_account = account_payload()
    if name == "dividend-fee-transfer":
        rows = [cash_payload("dividend-1"), cash_payload("fee-1", "FEE", net_amount="-0.25"),
                cash_payload("transfer-1", "CSD", net_amount="5.00")]
    elif name == "tied-created-at":
        rows = [cash_payload("tie-1"), cash_payload("tie-2")]
    elif name in {"duplicate-replay", "same-id-changed"}:
        original = fill_payload(qty="1") if name == "same-id-changed" else rows[0]
        accepted = normalize_activity(original, subject_sha256=fixture_subject().sha256,
                                      account_id=ACCOUNT_UUID, order=order)
        if accepted.disposition != "ACCEPTED":
            raise AssertionError("FIXTURE_PRIOR_EVIDENCE_NOT_ACCEPTED")
        prior = (accepted.evidence,)
    elif name == "unknown-event":
        rows = [cash_payload("unknown-1", "NEW_PROVIDER_TYPE")]
    elif name == "correction-quarantine":
        rows = [fill_payload(execution_type="trade_bust")]
    elif name == "security-transfer-quarantine":
        rows = [cash_payload("security-transfer-1", "JNLS")]
    elif name in {"truncated-pagination", "cursor-cycle"}:
        rows = [cash_payload("page-1"), cash_payload("page-2")]
        if name == "truncated-pagination":
            max_pages = 1
            pages = [rows]
        else:
            pages = [rows, [rows[-1]]]
    elif name == "wrong-account":
        final_account = account_payload("00000000-0000-4000-8000-000000000099")
    elif name == "malformed-decimal":
        rows = [fill_payload(qty="NaN")]
    elif name == "empty-history":
        rows = []
    elif name == "late-business-time":
        rows = [fill_payload(transaction_time="2020-10-16T14:31:00+00:00")]
        order = order_payload(submitted_at="2020-10-16T14:30:00+00:00", filled_at="2020-10-16T14:31:00+00:00")
    elif name == "exact-order-enrichment":
        del rows[0]["asset_id"]
        del rows[0]["side"]
    elif name == "mismatched-exact-order":
        order = order_payload(id="00000000-0000-4000-8000-000000000099")
    if pages is None:
        pages = [rows[index:index + 2] for index in range(0, len(rows), 2)]
        if not rows or len(rows) % 2 == 0:
            pages.append([])
    exchanges = [RecordedExchange(path="/v2/account", payload=account_payload())]
    token = None
    order_seen = False
    if prior:
        exchanges.append(RecordedExchange(path="/v2/orders/" + ORDER_UUID, payload=order))
        order_seen = True
    for page in pages:
        exchanges.append(RecordedExchange(path="/v2/account/activities", params=history_params(token=token), payload=page))
        for event in page:
            if event.get("activity_type") == "FILL" and not order_seen:
                exchanges.append(RecordedExchange(path="/v2/orders/" + ORDER_UUID, payload=order))
                order_seen = True
        if page:
            token = page[-1]["id"]
    exchanges.append(RecordedExchange(path="/v2/account", payload=final_account))
    recording = ActivityRecording(schema="sentinel.native-activity-recording/1", provenance="SIMULATION_ONLY",
                                  subject=fixture_subject(), after=AFTER, through=THROUGH, page_size=2,
                                  exchanges=tuple(exchanges))
    return recording, HistoryLimits(page_size=2, max_pages=max_pages), prior


class RecordingReplay:
    def __init__(self, exchanges: tuple[RecordedExchange, ...], *, base_url: str):
        self._exchanges = exchanges
        self._base_url = base_url
        self._position = 0
        self.requests = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        if request.method != "GET":
            raise AssertionError("RECORDING_MUTATION_FORBIDDEN")
        if request.headers.get("APCA-API-KEY-ID") != FIXTURE_KEY or request.headers.get("APCA-API-SECRET-KEY") != FIXTURE_SECRET:
            raise AssertionError("RECORDING_FIXTURE_CREDENTIALS_REQUIRED")
        if self._position >= len(self._exchanges):
            raise AssertionError("RECORDING_EXHAUSTED")
        expected = self._exchanges[self._position]
        observed = (request.method, str(request.url.copy_with(query=None)), tuple(sorted(request.url.params.multi_items())))
        wanted = (expected.method, self._base_url + expected.path, tuple(sorted(expected.params)))
        if observed != wanted or request.content:
            raise AssertionError("RECORDING_REQUEST_MISMATCH")
        self.requests.append((request.method, request.url.path))
        self._position += 1
        return httpx.Response(expected.status, content=wire_json(expected.payload).encode(),
                              headers={"Content-Type": "application/json"})

    def assert_consumed(self) -> None:
        if self._position != len(self._exchanges):
            raise AssertionError("RECORDING_NOT_CONSUMED")

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle), follow_redirects=False)
