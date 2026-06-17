"""Canonical order-status tokens for `alpaca_orders.status` — single source of truth.

These are the tokens actually PERSISTED in `alpaca_orders.status`. They must be
the SAME tokens every reader queries. Divergence here is a confirmed split-brain
bug class: alpaca-sync persisted a partial fill as `partial_fill` while
trade-executor and risk-service queried `partially_filled` (the un-normalized
broker spelling that never lands in the DB), so a partially-filled order was
invisible to idempotency/dedup (→ double-submit) and to the risk MAX_POSITIONS
exit-detection / turnover cap (→ capacity & churn miscount). Importing from here
makes "the token we write" == "the token we query" by construction.

Spelling notes (canonical DB tokens, NOT the Alpaca broker spellings):
  - partial fill → `partial_fill`   (alpaca-sync writes this; dashboard.js reads it)
  - the broker→DB mapping lives in alpaca-sync `_ALPACA_TO_STATUS`.
"""
from __future__ import annotations

# An order that is QUEUED or WORKING at the broker (NOT terminal). Used for
# idempotency ("does this intent already have an open order?"), per-ticker dedup,
# and the risk-service MAX_POSITIONS projected-book / exit-detection. Includes
# `deferred` (the after-close fill-gated-drain queue state) and `partial_fill`
# (a partially-filled order is still working its remainder).
OPEN_ORDER_STATUSES: tuple[str, ...] = (
    "pending", "submitted", "deferred", "accepted", "new", "partial_fill",
)

# Statuses that count toward the daily sell-side turnover cap: an order is "churn"
# once it is queued/working OR already filled. = OPEN_ORDER_STATUSES + `filled`.
# MUST include `deferred` (the normal after-close queued-sell state) or a full
# rotation of deferred sells slips past MAX_DAILY_TURNOVER_PCT.
TURNOVER_STATUSES: tuple[str, ...] = OPEN_ORDER_STATUSES + ("filled",)


def open_status_sql() -> str:
    """Comma-separated single-quoted literals for inlining into `status IN (...)`.
    These are fixed code constants — never user input — so inlining is safe."""
    return ", ".join(f"'{s}'" for s in OPEN_ORDER_STATUSES)


def turnover_status_sql() -> str:
    return ", ".join(f"'{s}'" for s in TURNOVER_STATUSES)
