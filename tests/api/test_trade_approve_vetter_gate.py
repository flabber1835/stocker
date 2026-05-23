"""
Tests for the vetter-exclusion gate in /trade/approve.

Background: delta_intents is created by the pipeline BEFORE the LLM vetter
runs. So an excluded ticker can still appear with action='entry' in
delta_intents. Portfolio-builder drops excluded tickers from the target
portfolio, but it never rewrites delta_intents — the entry intent persists.

Without this gate, both manual approval and the dashboard auto-approve
loop would happily forward the excluded entry to trade-executor, which has
no vetter awareness. The result: an approved trade for a ticker the LLM
flagged as risky.

The gate sits in services/api/app/main.py:approve_trade and refuses
entry/buy_add intents whose ticker appears in the most-recent successful
vetter run's exclusion set. Exits and sell_trims are never blocked —
closing/reducing an excluded position must always remain possible.
"""
from __future__ import annotations


# ── Simulated gate logic (mirrors services/api/app/main.py:approve_trade) ────

def _check_vetter_gate(
    intent: dict,
    vetter_runs: list[dict],
    vetter_exclusions: list[dict],
) -> dict | None:
    """Return {ticker, reason} if blocked, None if allowed.

    Mirrors the SQL JOIN in approve_trade:
      SELECT di.ticker, ve.reason
      FROM delta_intents di
      JOIN vetter_exclusions ve ON ve.ticker = di.ticker
      JOIN vetter_runs vr ON vr.run_id = ve.run_id
      WHERE di.id = :iid
        AND di.action IN ('entry', 'buy_add')
        AND vr.status = 'success'
        AND vr.started_at = (max started_at over successful vetter_runs)
    """
    if intent["action"] not in ("entry", "buy_add"):
        return None
    successful = [r for r in vetter_runs if r["status"] == "success"]
    if not successful:
        return None
    latest = max(successful, key=lambda r: r["started_at"])
    for exc in vetter_exclusions:
        if exc["run_id"] == latest["run_id"] and exc["ticker"] == intent["ticker"]:
            return {"ticker": intent["ticker"], "reason": exc.get("reason")}
    return None


# ── Tests ─────────────────────────────────────────────────────────────────────

class TestVetterGate:
    """The core safety property: excluded BUYs are refused, everything else proceeds."""

    def test_excluded_entry_is_blocked(self):
        """The PARR scenario: vetter excludes PARR but delta_intents still has entry."""
        intent = {"id": "i1", "ticker": "PARR", "action": "entry"}
        runs = [{"run_id": "r1", "status": "success", "started_at": 100}]
        exclusions = [{"run_id": "r1", "ticker": "PARR", "reason": "refinery margin compression"}]
        blocked = _check_vetter_gate(intent, runs, exclusions)
        assert blocked is not None
        assert blocked["ticker"] == "PARR"
        assert "margin" in blocked["reason"]

    def test_excluded_buy_add_is_blocked(self):
        """buy_add is also a position-increasing action — vetter exclusion must apply."""
        intent = {"id": "i1", "ticker": "PARR", "action": "buy_add"}
        runs = [{"run_id": "r1", "status": "success", "started_at": 100}]
        exclusions = [{"run_id": "r1", "ticker": "PARR", "reason": "risk"}]
        assert _check_vetter_gate(intent, runs, exclusions) is not None

    def test_excluded_exit_is_allowed(self):
        """Closing a position must always be possible, even if vetter excluded the ticker."""
        intent = {"id": "i1", "ticker": "PARR", "action": "exit"}
        runs = [{"run_id": "r1", "status": "success", "started_at": 100}]
        exclusions = [{"run_id": "r1", "ticker": "PARR", "reason": "risk"}]
        assert _check_vetter_gate(intent, runs, exclusions) is None

    def test_excluded_sell_trim_is_allowed(self):
        """Reducing a position must always be possible — the exclusion is a flag against ADDING."""
        intent = {"id": "i1", "ticker": "PARR", "action": "sell_trim"}
        runs = [{"run_id": "r1", "status": "success", "started_at": 100}]
        exclusions = [{"run_id": "r1", "ticker": "PARR", "reason": "risk"}]
        assert _check_vetter_gate(intent, runs, exclusions) is None

    def test_non_excluded_entry_is_allowed(self):
        intent = {"id": "i1", "ticker": "AAPL", "action": "entry"}
        runs = [{"run_id": "r1", "status": "success", "started_at": 100}]
        exclusions = [{"run_id": "r1", "ticker": "PARR", "reason": "risk"}]
        assert _check_vetter_gate(intent, runs, exclusions) is None


class TestVetterRunSelection:
    """Only the MOST RECENT successful run's exclusions apply.

    If yesterday's vetter run excluded PARR but today's run cleared it, today's
    decision must win. This matters when a stock's risk profile changes."""

    def test_older_run_exclusion_ignored_when_newer_run_clears(self):
        intent = {"id": "i1", "ticker": "PARR", "action": "entry"}
        runs = [
            {"run_id": "old", "status": "success", "started_at": 100},
            {"run_id": "new", "status": "success", "started_at": 200},  # most recent
        ]
        exclusions = [
            {"run_id": "old", "ticker": "PARR", "reason": "old risk"},
            # 'new' run does NOT exclude PARR
        ]
        assert _check_vetter_gate(intent, runs, exclusions) is None

    def test_failed_runs_are_skipped(self):
        """A failed vetter run must not be treated as authoritative."""
        intent = {"id": "i1", "ticker": "PARR", "action": "entry"}
        runs = [
            {"run_id": "success_old", "status": "success", "started_at": 100},
            {"run_id": "failed_new",  "status": "failed",  "started_at": 999},
        ]
        exclusions = [
            {"run_id": "success_old", "ticker": "PARR", "reason": "real risk"},
            # if we wrongly picked failed_new, we'd miss this exclusion
        ]
        blocked = _check_vetter_gate(intent, runs, exclusions)
        assert blocked is not None, "must fall back to the most recent SUCCESSFUL run"

    def test_no_successful_run_means_no_gate(self):
        """If vetter has never run successfully, we do not block trades — vetter is advisory.
        The portfolio-builder still applies its own filters; this gate is the executor's
        last-mile safety net."""
        intent = {"id": "i1", "ticker": "PARR", "action": "entry"}
        runs = [{"run_id": "x", "status": "failed", "started_at": 100}]
        exclusions = [{"run_id": "x", "ticker": "PARR", "reason": "risk"}]
        assert _check_vetter_gate(intent, runs, exclusions) is None


class TestAutoApproveSkip:
    """The dashboard auto-approve loop must skip excluded BUYs to avoid 409 noise.

    This mirrors the inline check in services/dashboard/app/main.py:_auto_approve_bg."""

    def _should_auto_approve(self, intent: dict) -> bool:
        action = intent.get("action")
        if action not in ("entry", "exit"):
            return False
        if action == "entry" and intent.get("vetter_excluded"):
            return False
        return True

    def test_excluded_entry_skipped(self):
        assert not self._should_auto_approve(
            {"action": "entry", "vetter_excluded": True}
        )

    def test_non_excluded_entry_approved(self):
        assert self._should_auto_approve(
            {"action": "entry", "vetter_excluded": False}
        )

    def test_entry_with_null_exclusion_approved(self):
        """vetter_excluded=None (no vetter run yet) → still approve."""
        assert self._should_auto_approve(
            {"action": "entry", "vetter_excluded": None}
        )

    def test_exit_always_approved(self):
        """Exits proceed even if the ticker was excluded by vetter."""
        assert self._should_auto_approve(
            {"action": "exit", "vetter_excluded": True}
        )

    def test_hold_never_auto_approved(self):
        """hold/watch/at_risk/buy_add/sell_trim are not in the auto-approve set
        (they require manual review)."""
        for action in ("hold", "watch", "at_risk", "buy_add", "sell_trim"):
            assert not self._should_auto_approve({"action": action})
