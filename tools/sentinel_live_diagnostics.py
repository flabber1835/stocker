from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
from typing import Callable, Mapping

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sentinel.execution.alpaca_history import HistoryLimits, read_account_history
from sentinel.execution.live_funding import FundingEvidence, assess_live_funding
from sentinel.execution.native_readonly import (
    ExecutionSubject, NativeReadRefused, ReadOnlyAlpacaClient, ReadOnlyLimits,
)
from sentinel.trading_environment import TradingEndpoint


_ENV_NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
_SAFE_REASON = re.compile(r"NATIVE_READ_[A-Z_]{1,80}\Z")
_GUARANTEES = (
    "native_history_completeness", "late_publication_finality", "settlement",
    "close_cash_finality", "restore_grade_order_recovery", "live_authority",
)


class DiagnosticInputs(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")
    base_url: str
    expected_account: str
    deployment_id: str
    takeover_epoch: int = Field(strict=True, gt=0)
    api_key_env: str
    secret_key_env: str
    after: datetime
    through: datetime

    @field_validator("api_key_env", "secret_key_env")
    @classmethod
    def explicit_environment_name(cls, value):
        if not _ENV_NAME.fullmatch(value):
            raise ValueError("EXPLICIT_CREDENTIAL_ENV_NAME_REQUIRED")
        return value

    @model_validator(mode="after")
    def explicit_inputs(self):
        if self.api_key_env == self.secret_key_env:
            raise ValueError("DISTINCT_CREDENTIAL_ENV_NAMES_REQUIRED")
        if (self.after.tzinfo is None or self.through.tzinfo is None or self.after > self.through):
            raise ValueError("AWARE_DIAGNOSTIC_INTERVAL_REQUIRED")
        self.subject()
        return self

    def subject(self) -> ExecutionSubject:
        endpoint = TradingEndpoint.parse(self.base_url)
        if endpoint.base_url != self.base_url:
            raise ValueError("EXACT_CANONICAL_ORIGIN_REQUIRED")
        return ExecutionSubject(deployment_id=self.deployment_id, account_id=self.expected_account,
                                takeover_epoch=self.takeover_epoch, environment=endpoint.environment,
                                base_url=endpoint.base_url)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(now: Callable) -> datetime:
    value = now()
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("DIAGNOSTIC_CLOCK_REFUSED")
    return value.astimezone(timezone.utc)


async def diagnose(inputs: DiagnosticInputs, *, environ: Mapping[str, str],
                   http_client=None, limits: ReadOnlyLimits | None = None,
                   history_limits: HistoryLimits | None = None,
                   now: Callable = _utc_now) -> dict:
    subject = inputs.subject()
    started = _timestamp(now)
    report = {
        "schema": "sentinel.native-readonly-diagnostic/1",
        "status": "NOT_PROVEN",
        "reason": "READ_ONLY_DIAGNOSTIC_NOT_COMPLETED",
        "environment": subject.environment.value,
        "origin": subject.base_url,
        "subject_sha256": subject.sha256,
        "started_at": started.isoformat(),
        "requested_after": inputs.after.isoformat(),
        "requested_through": inputs.through.isoformat(),
        "order_authority": "NONE",
        "broker_mutation_attempts": 0,
        "funding_status": "DEFERRED",
        "funding_checks": "DEFERRED_NATIVE_ACCOUNT_QUALIFICATION",
        "native_guarantees": {name: "NOT_PROVEN" for name in _GUARANTEES},
        "capabilities_promoted": [],
        "raw_recordings_exported": False,
    }
    client = None
    try:
        key = environ.get(inputs.api_key_env, "")
        secret = environ.get(inputs.secret_key_env, "")
        effective_limits = limits or ReadOnlyLimits()
        effective_history = history_limits or HistoryLimits(max_seconds=float(effective_limits.max_seconds),
                                                            max_bytes=effective_limits.max_bytes)
        client = ReadOnlyAlpacaClient(subject, api_key=key, secret_key=secret,
                                     limits=effective_limits, http_client=http_client)
        async with client:
            account = await client.verify_account()
            observed_at = _timestamp(now)
            batch = await read_account_history(client, after=inputs.after, through=inputs.through,
                                               limits=effective_history)
            if not batch.traversal_exhausted:
                report["reason"] = "NATIVE_HISTORY_TRAVERSAL_NOT_PROVEN"
            else:
                raw = account.raw
                evidence = FundingEvidence(
                    subject=subject, observed_at=observed_at,
                    cash=raw.get("cash"), buying_power=raw.get("buying_power"),
                    multiplier=raw.get("multiplier"), status=raw.get("status"),
                    trading_blocked=raw.get("trading_blocked"),
                    account_blocked=raw.get("account_blocked"),
                    trade_suspended_by_user=raw.get("trade_suspended_by_user"),
                    provenance="NATIVE")
                funding = assess_live_funding(evidence, expected_subject=subject, now=_timestamp(now))
                if funding.status != "DEFERRED" or funding.spendable_budget != 0 or funding.order_authority != "NONE":
                    raise ValueError("UNQUALIFIED_FUNDING_PROMOTION_REFUSED")
                report.update(status="PASS_READ_ONLY_DIAGNOSTIC", reason="ACCOUNT_AND_HISTORY_RESPONSE_OBSERVED",
                              account_identity_bracketed=True,
                              history_traversal_exhausted=True,
                              parser_projection_ready=batch.projection_ready,
                              history_evidence_sha256=batch.evidence_sha256,
                              observed_event_count=len(batch.events),
                              observed_fill_count=len(batch.fills),
                              observed_cash_event_count=len(batch.cash_activities),
                              quarantined_event_count=len(batch.quarantines),
                              funding_reasons=list(funding.reasons))
    except NativeReadRefused as exc:
        report["reason"] = exc.code if _SAFE_REASON.fullmatch(exc.code) else "READ_ONLY_DIAGNOSTIC_REFUSED"
    except Exception:
        report["reason"] = "READ_ONLY_DIAGNOSTIC_REFUSED"
    finally:
        if client is not None:
            report.update(request_count=client.requests_used, response_bytes=client.bytes_used)
        try:
            finished = _timestamp(now)
            if finished < started:
                raise ValueError("DIAGNOSTIC_CLOCK_REFUSED")
            report["completed_at"] = finished.isoformat()
        except Exception:
            report.update(status="NOT_PROVEN", reason="DIAGNOSTIC_CLOCK_REFUSED")
    return report


def _write_report(path: Path, report: Mapping) -> None:
    payload = (json.dumps(report, sort_keys=True, indent=2) + "\n").encode()
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as handle:
        handle.write(payload)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--expected-account", required=True)
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--takeover-epoch", required=True, type=int)
    parser.add_argument("--api-key-env", required=True)
    parser.add_argument("--secret-key-env", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--through", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-requests", type=int, default=256)
    parser.add_argument("--max-bytes", type=int, default=16 * 1024 * 1024)
    parser.add_argument("--max-seconds", type=float, default=60)
    args = parser.parse_args(argv)
    try:
        inputs = DiagnosticInputs(**{name: getattr(args, name) for name in (
            "base_url", "expected_account", "deployment_id", "takeover_epoch",
            "api_key_env", "secret_key_env", "after", "through")})
        limits = ReadOnlyLimits(max_requests=args.max_requests, max_bytes=args.max_bytes,
                                max_seconds=args.max_seconds)
        report = asyncio.run(diagnose(inputs, environ=os.environ, limits=limits))
        _write_report(args.output, report)
    except Exception:
        print(json.dumps({"status": "NOT_PROVEN", "reason": "EXPLICIT_INPUT_OR_OUTPUT_REFUSED"}))
        return 2
    print(json.dumps({key: report[key] for key in ("status", "reason", "funding_status")}))
    return 0 if report["status"] == "PASS_READ_ONLY_DIAGNOSTIC" else 1


if __name__ == "__main__":
    raise SystemExit(main())
