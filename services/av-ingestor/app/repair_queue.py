"""Field-regression repair queue for fundamentals (layer 4 of the PBR armor).

The transport layer already retries HTTP failures; this module handles the
SEMANTIC failure the PBR incident exposed: a fetch that "succeeds" but returns a
previously-populated field as null (AV served Petrobras totalAssets=None once;
the true value was back within hours). Without repair, the degraded row persists
for the full weekly refresh cadence while downstream layers (LKG read, quality
fallback, gate-gap hold) can only mask it.

Flow:
  detect  — at upsert time, diff the new row's fields against the ticker's
            previous row; populated→null = regression → enqueue.
  repair  — at the start of the next fetch-data run, unresolved tickers with
            attempts < FUND_REPAIR_MAX_ATTEMPTS are force-refreshed (they bypass
            the weekly _should_skip_fundamentals window); attempts increment.
  resolve — when a later upsert shows ALL of the queued regressed fields
            non-null again, the entry is marked resolved. Resolution checks the
            QUEUED field list, not "no new regressions" — after the degraded row
            becomes the previous row, a still-null field produces no new
            regression signal, so that weaker check would self-resolve wrongly.
  give up — attempts >= cap stays unresolved but is no longer scheduled
            (a delisting legitimately loses coverage; don't hammer AV forever).
            Still visible in the table for the ops eye / evaluator health.
"""
from __future__ import annotations

import json
from typing import Optional

from sqlalchemy import text

# The numeric fundamentals fields the factor pipeline consumes — a regression in
# any of these is worth a targeted re-fetch. Mirrors _upsert_fundamentals.
REGRESSION_FIELDS = (
    "pe_ratio", "pb_ratio", "roe", "debt_to_equity",
    "revenue_growth", "eps_growth", "market_cap", "avg_volume",
    "gross_profit", "total_assets",
    "shares_outstanding", "shares_outstanding_prior",
)


def detect_field_regressions(prev_row: Optional[dict], new_params: dict,
                             fields=REGRESSION_FIELDS) -> list[str]:
    """Fields that were populated in the ticker's PREVIOUS row and are null in
    the new fetch. No previous row → nothing can regress (a first-ever fetch
    with gaps is normal sparse coverage, not a regression). Pure."""
    if not prev_row:
        return []
    return [
        f for f in fields
        if prev_row.get(f) is not None and new_params.get(f) is None
    ]


def regression_resolved(queued_fields: list[str], new_params: dict) -> bool:
    """True when EVERY queued regressed field is non-null in the new fetch.
    Partial recovery keeps the entry open (the missing field is still the
    factor-killing gap). Empty queue list is vacuously resolved. Pure."""
    return all(new_params.get(f) is not None for f in queued_fields)


async def load_repair_set(engine, max_attempts: int) -> set[str]:
    """Unresolved tickers still under the attempt cap — the force-refresh set
    for this run."""
    async with engine.connect() as conn:
        rows = await conn.execute(text(
            "SELECT ticker FROM fundamentals_repair_queue "
            "WHERE resolved_at IS NULL AND attempts < :cap"
        ), {"cap": max_attempts})
        return {r.ticker for r in rows.fetchall()}


async def bump_attempts(engine, tickers: set[str]) -> None:
    """Record that this run is attempting these repairs (scheduled = attempted;
    a crash mid-run still counts the attempt, which errs on the give-up side)."""
    if not tickers:
        return
    async with engine.begin() as conn:
        await conn.execute(text(
            "UPDATE fundamentals_repair_queue "
            "SET attempts = attempts + 1, last_attempt = NOW() "
            "WHERE ticker = ANY(:tk) AND resolved_at IS NULL"
        ), {"tk": sorted(tickers)})


async def record_check(session, ticker: str, prev_row: Optional[dict],
                       new_params: dict) -> Optional[str]:
    """Called inside the fundamentals upsert transaction. Returns 'enqueued',
    'resolved', or None (no queue action) — callers only log.

    - New regressions → enqueue / refresh the entry. A regression arriving on a
      previously RESOLVED entry is a NEW incident: attempts and first_detected
      reset (the old counters belong to the old incident).
    - No regressions and an OPEN entry whose queued fields are all non-null now
      → resolved.
    """
    regressed = detect_field_regressions(prev_row, new_params)
    if regressed:
        await session.execute(text(
            "INSERT INTO fundamentals_repair_queue (ticker, regressed_fields) "
            "VALUES (:t, CAST(:rf AS jsonb)) "
            "ON CONFLICT (ticker) DO UPDATE SET "
            "  regressed_fields = EXCLUDED.regressed_fields, "
            "  attempts = CASE WHEN fundamentals_repair_queue.resolved_at IS NOT NULL "
            "                  THEN 0 ELSE fundamentals_repair_queue.attempts END, "
            "  first_detected = CASE WHEN fundamentals_repair_queue.resolved_at IS NOT NULL "
            "                        THEN NOW() ELSE fundamentals_repair_queue.first_detected END, "
            "  resolved_at = NULL"
        ), {"t": ticker, "rf": json.dumps(regressed)})
        return "enqueued"

    open_row = (await session.execute(text(
        "SELECT regressed_fields FROM fundamentals_repair_queue "
        "WHERE ticker = :t AND resolved_at IS NULL"
    ), {"t": ticker})).fetchone()
    if open_row is not None:
        queued = open_row[0] or []
        if regression_resolved(list(queued), new_params):
            await session.execute(text(
                "UPDATE fundamentals_repair_queue SET resolved_at = NOW() "
                "WHERE ticker = :t"
            ), {"t": ticker})
            return "resolved"
    return None
