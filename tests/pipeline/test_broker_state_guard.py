"""
Unit tests for the delta broker-state reliability guard.

The delta step suppresses buy-side intents (entry / buy_add) when the latest
alpaca-sync snapshot can't be trusted. Without this, a stale or empty snapshot
makes every target ticker look un-held, flooding entries that exceed buying
power and bounce at Alpaca for insufficient funds (the production incident this
guards against).

These exercise the pure decision function `_broker_state_unreliable` directly.
"""
from datetime import datetime, timedelta, timezone

from app.main import _broker_state_unreliable

NOW = datetime(2026, 5, 29, 12, 0, tzinfo=timezone.utc)


def _call(**kw):
    base = dict(
        no_sync_data=False,
        sync_completed_at=NOW,
        account_value=100_000.0,
        cash=5_000.0,
        live_positions_empty=False,
        max_age_hours=12.0,
        now=NOW,
    )
    base.update(kw)
    return _broker_state_unreliable(**base)


class TestBrokerStateUnreliable:
    def test_healthy_snapshot_is_reliable(self):
        """Fresh sync, positions present, deployed capital → safe to trade."""
        unreliable, reason = _call()
        assert unreliable is False and reason == ""

    def test_no_sync_data_is_unreliable(self):
        unreliable, reason = _call(no_sync_data=True, sync_completed_at=None,
                                   account_value=None, cash=None, live_positions_empty=True)
        assert unreliable is True
        assert "no successful alpaca-sync" in reason

    def test_stale_sync_is_unreliable(self):
        """Latest sync older than the age threshold → unreliable even with positions."""
        unreliable, reason = _call(sync_completed_at=NOW - timedelta(hours=20))
        assert unreliable is True
        assert "old" in reason

    def test_fresh_sync_just_under_threshold_is_reliable(self):
        unreliable, _ = _call(sync_completed_at=NOW - timedelta(hours=11, minutes=59))
        assert unreliable is False

    def test_funded_account_no_positions_low_cash_is_unreliable(self):
        """The production tell: account funded, capital deployed (cash << value),
        yet zero positions captured → inconsistent snapshot, do not buy."""
        unreliable, reason = _call(live_positions_empty=True, account_value=100_000.0, cash=1_000.0)
        assert unreliable is True
        assert "inconsistent" in reason

    def test_genuine_all_cash_account_is_reliable(self):
        """An all-cash account (cash ≈ value, no positions) is legitimately ready
        to invest — must NOT be flagged, or the first buy could never happen."""
        unreliable, reason = _call(live_positions_empty=True, account_value=100_000.0, cash=99_000.0)
        assert unreliable is False and reason == ""

    def test_unknown_cash_with_no_positions_is_unreliable(self):
        """Funded account, no positions, cash unrecorded → treat conservatively."""
        unreliable, _ = _call(live_positions_empty=True, account_value=100_000.0, cash=None)
        assert unreliable is True

    def test_empty_unfunded_account_is_reliable(self):
        """No positions and account_value 0/None (e.g. no creds) → not flagged by
        the inconsistency rule (nothing to trade anyway)."""
        unreliable, _ = _call(live_positions_empty=True, account_value=0.0, cash=0.0)
        assert unreliable is False

    def test_naive_timestamp_treated_as_utc(self):
        """A naive completed_at (timestamp without tz) must not crash the age math."""
        naive = (NOW - timedelta(hours=20)).replace(tzinfo=None)
        unreliable, reason = _call(sync_completed_at=naive)
        assert unreliable is True and "old" in reason
