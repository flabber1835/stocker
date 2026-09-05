#!/usr/bin/env python3
"""Wall-clock-independent control overlay for non-authoritative bring-up.

Bring-up now performs only lightweight read-only liveness. A source-final wait is
therefore diagnostic context, not installation authority. Full source observation,
recovery, and certification remain exclusively in GO.
"""
from __future__ import annotations

import sys
from typing import Mapping

import sentinel_bringup as base


def source_decision(report: Mapping[str, object]) -> base.SourceDecision:
    status = str(report.get("status") or "")
    reason = str(report.get("reason_code") or "BRINGUP_LIVENESS_UNAVAILABLE")
    if status in {"PASS", "RECOVERY_REQUIRED"}:
        return base.SourceDecision(True, status, reason)
    if status == "DEFERRED":
        # Workflow-control normalization only. The raw DEFERRED status remains
        # visible to the operator, while GO later applies the authoritative
        # source-final rule at its actual source/preparation boundary.
        return base.SourceDecision(True, "PASS", reason)
    if status == "REFUSED":
        return base.SourceDecision(False, status, reason)
    raise base.BringupRefused("source liveness probe returned an unknown state")


def _print_source_report(report: Mapping[str, object], *, prefix: str) -> None:
    raw_status = str(report.get("status") or "")
    reason = str(report.get("reason_code") or "BRINGUP_LIVENESS_UNAVAILABLE")
    detail = base.liveness.safe_detail(report.get("detail"))
    text = "%s: %s - %s" % (prefix, raw_status, reason)
    if detail:
        text += " - " + detail
    if report.get("detail_sha256"):
        text += " [detail_sha256=%s]" % str(report["detail_sha256"])
    followup = report.get("local_followup")
    if isinstance(followup, list) and followup:
        text += " [local_followup=%s]" % ",".join(str(item) for item in followup)
    print(text, flush=True)


def install() -> None:
    base.source_decision = source_decision
    base._print_source_report = _print_source_report


def main() -> int:
    install()
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
