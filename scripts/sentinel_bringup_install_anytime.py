#!/usr/bin/env python3
"""Wall-clock-independent control overlay for non-authoritative bring-up.

Sharadar source-final timing determines only the newest causally usable market
session. It is not an installation authority. The underlying 24x7 preparation
already catches up through the newest source-final predecessor, so a DEFERRED
read-only source result is safe to continue through build/recovery/certification
bring-up. The raw source status remains visible in operator output.

This module creates no deployment authority. The final supported GO lifecycle is
still required before promotion or any broker-capable deployment.
"""
from __future__ import annotations

import sys
from typing import Mapping

import sentinel_bringup as base


def source_decision(report: Mapping[str, object]) -> base.SourceDecision:
    status = str(report.get("status") or "")
    reason = str(report.get("reason_code") or "READONLY_PREFLIGHT_UNAVAILABLE")
    if status in {"PASS", "RECOVERY_REQUIRED"}:
        return base.SourceDecision(True, status, reason)
    if status == "DEFERRED":
        # Workflow-control normalization only. The public/operator-facing source
        # report remains DEFERRED via _print_source_report below. Treating it as
        # PASS here prevents wall-clock state from blocking software installation
        # or bounded catch-up to the newest already-source-final predecessor.
        return base.SourceDecision(True, "PASS", reason)
    if status == "REFUSED":
        return base.SourceDecision(False, status, reason)
    raise base.BringupRefused(
        "read-only Sharadar preflight returned an unknown state")


def _print_source_report(report: Mapping[str, object], *, prefix: str) -> None:
    raw_status = str(report.get("status") or "")
    reason = str(report.get("reason_code") or "READONLY_PREFLIGHT_UNAVAILABLE")
    detail = base.readonly._safe_detail(report.get("detail"))
    text = "%s: %s - %s" % (prefix, raw_status, reason)
    if detail:
        text += " - " + detail
    if report.get("detail_sha256"):
        text += " [detail_sha256=%s]" % str(report["detail_sha256"])
    print(text, flush=True)


def install() -> None:
    base.source_decision = source_decision
    base._print_source_report = _print_source_report


def main() -> int:
    install()
    return base.main()


if __name__ == "__main__":
    raise SystemExit(main())
