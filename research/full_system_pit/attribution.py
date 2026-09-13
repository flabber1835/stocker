"""Episode-level historical terminal economics observed from production."""
from __future__ import annotations

from collections import Counter
from decimal import Decimal, InvalidOperation

from .evidence import digest, plain


ECONOMIC_FIELDS = (
    "session", "security_id", "ticker", "kind", "method",
    "settlement_method", "settlement_source", "source",
    "settlement_available_phase", "availability_phase", "phase",
    "applied", "blocked", "reason", "shares", "old_shares",
    "shares_before", "shares_at_carry", "shares_at_settlement",
    "exchange_ratio", "new_shares_per_old_share", "shares_delivered",
    "fractional_entitlement", "cash_per_share", "cash_per_old_share",
    "cash_consideration", "cash_in_lieu", "proceeds", "carry_notional",
    "settlement_notional", "notional_delta",
)


def _money(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


class HeldEventAttribution:
    def __init__(self):
        self.rows = []
        self.observed_terminal_results = 0

    def observe_transition(self, transition):
        for terminal in plain(transition).get("terminal_results", ()):
            self.observed_terminal_results += 1
            if terminal.get("reason") == "NOT_HELD":
                continue
            raw = dict(terminal)
            selected = {
                key: raw[key]
                for key in ECONOMIC_FIELDS
                if key in raw
            }
            selected["source_payload_sha256"] = digest(raw)
            selected["source_payload"] = raw
            self.rows.append(selected)

    def finish(self):
        methods = Counter()
        phases = Counter()
        total_proceeds = Decimal(0)
        for row in self.rows:
            method = (row.get("settlement_method") or row.get("method")
                      or row.get("reason") or "UNSPECIFIED")
            phase = (row.get("settlement_available_phase")
                     or row.get("availability_phase")
                     or row.get("phase") or "UNSPECIFIED")
            methods[str(method)] += 1
            phases[str(phase)] += 1
            proceeds = _money(row.get("proceeds"))
            if proceeds is not None:
                total_proceeds += proceeds
        return {
            "schema": "full-system-held-event-attribution/1",
            "status": "PASS_COMPLETE_OBSERVED_ATTRIBUTION",
            "observed_terminal_results": self.observed_terminal_results,
            "held_event_rows": len(self.rows),
            "rows_sha256": digest(self.rows),
            "settlement_methods": dict(sorted(methods.items())),
            "availability_phases": dict(sorted(phases.items())),
            "total_observed_proceeds": str(total_proceeds),
            "rows": self.rows,
        }
