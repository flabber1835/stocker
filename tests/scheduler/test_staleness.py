from datetime import date

import pytest

from app.staleness import count_missed_trading_days, is_stale, last_trading_day


# ── count_missed_trading_days ─────────────────────────────────────────────────

class TestCountMissedTradingDays:

    def test_consecutive_weekdays_no_gap(self):
        # Monday run, check Tuesday morning — no closed days in between
        assert count_missed_trading_days(date(2026, 5, 11), date(2026, 5, 12)) == 0

    def test_one_missed_weekday(self):
        # Monday run, check Wednesday — Tuesday is missed
        assert count_missed_trading_days(date(2026, 5, 11), date(2026, 5, 13)) == 1

    def test_two_missed_weekdays(self):
        # Monday run, check Thursday — Tuesday and Wednesday missed
        assert count_missed_trading_days(date(2026, 5, 11), date(2026, 5, 14)) == 2

    def test_friday_to_monday_no_gap(self):
        # System off over weekend — Saturday and Sunday don't count
        assert count_missed_trading_days(date(2026, 5, 8), date(2026, 5, 11)) == 0

    def test_friday_to_tuesday_one_gap(self):
        # System off over weekend and Monday — Monday is missed
        assert count_missed_trading_days(date(2026, 5, 8), date(2026, 5, 12)) == 1

    def test_friday_to_wednesday_two_gaps(self):
        # Monday and Tuesday missed
        assert count_missed_trading_days(date(2026, 5, 8), date(2026, 5, 13)) == 2

    def test_same_day_zero(self):
        assert count_missed_trading_days(date(2026, 5, 11), date(2026, 5, 11)) == 0

    def test_today_before_last_run_zero(self):
        # Shouldn't happen in practice but must not error or go negative
        assert count_missed_trading_days(date(2026, 5, 13), date(2026, 5, 11)) == 0

    def test_full_week_missed(self):
        # Monday → next Monday: Tue, Wed, Thu, Fri = 4 missed
        assert count_missed_trading_days(date(2026, 5, 11), date(2026, 5, 18)) == 4

    def test_two_weekends_spanned(self):
        # Friday → Monday two weeks later: Mon+Tue+Wed+Thu+Fri = 5 missed
        assert count_missed_trading_days(date(2026, 5, 8), date(2026, 5, 18)) == 5

    def test_last_run_saturday_to_monday(self):
        # Unusual: run recorded on Saturday (e.g. manual), today Monday → no weekdays between
        assert count_missed_trading_days(date(2026, 5, 9), date(2026, 5, 11)) == 0

    def test_last_run_saturday_to_tuesday(self):
        # Run on Saturday, back Monday — no weekdays between Sat and Mon (exclusive)
        assert count_missed_trading_days(date(2026, 5, 9), date(2026, 5, 11)) == 0
        # Run on Saturday, back Tuesday — Monday is missed
        assert count_missed_trading_days(date(2026, 5, 9), date(2026, 5, 12)) == 1


# ── is_stale ──────────────────────────────────────────────────────────────────

class TestIsStale:

    def test_none_always_stale(self):
        assert is_stale(None, date(2026, 5, 17)) is True

    def test_same_day_not_stale(self):
        assert is_stale(date(2026, 5, 17), date(2026, 5, 17)) is False

    def test_last_run_in_future_not_stale(self):
        # Clock skew / edge case
        assert is_stale(date(2026, 5, 18), date(2026, 5, 17)) is False

    def test_consecutive_weekday_not_stale(self):
        # Ran Monday, checking Tuesday morning — market hasn't closed yet
        assert is_stale(date(2026, 5, 11), date(2026, 5, 12)) is False

    def test_one_missed_weekday_stale(self):
        # Ran Monday, checking Wednesday — missed Tuesday
        assert is_stale(date(2026, 5, 11), date(2026, 5, 13)) is True

    def test_friday_to_monday_not_stale(self):
        # Computer off over weekend — no trading days missed
        assert is_stale(date(2026, 5, 8), date(2026, 5, 11)) is False

    def test_friday_to_tuesday_stale(self):
        # Monday's data missed
        assert is_stale(date(2026, 5, 8), date(2026, 5, 12)) is True

    def test_three_day_outage_stale(self):
        # Monday run, back Thursday — missed Tue + Wed
        assert is_stale(date(2026, 5, 11), date(2026, 5, 15)) is True

    def test_long_holiday_weekend_stale(self):
        # e.g. ran Thursday before 4-day weekend, back Tuesday
        # Fri + Mon missed (holiday treated as missed — acceptable false positive)
        assert is_stale(date(2026, 5, 7), date(2026, 5, 13)) is True

    def test_full_week_outage_stale(self):
        # Ran Friday, back the following Friday — entire week missed
        assert is_stale(date(2026, 5, 8), date(2026, 5, 17)) is True

    def test_ran_today_saturday_not_stale(self):
        # Manual run on a Saturday — still current for the weekend
        assert is_stale(date(2026, 5, 16), date(2026, 5, 16)) is False

    def test_friday_run_saturday_check_not_stale(self):
        # Ran Friday, checking Saturday — no trading day closed since
        assert is_stale(date(2026, 5, 9), date(2026, 5, 10)) is False


# ── last_trading_day ──────────────────────────────────────────────────────────

class TestLastTradingDay:

    def test_weekday_returns_itself(self):
        assert last_trading_day(date(2026, 5, 11)) == date(2026, 5, 11)  # Monday

    def test_saturday_returns_friday(self):
        assert last_trading_day(date(2026, 5, 9)) == date(2026, 5, 8)   # Sat → Fri

    def test_sunday_returns_friday(self):
        assert last_trading_day(date(2026, 5, 10)) == date(2026, 5, 8)  # Sun → Fri

    def test_friday_returns_itself(self):
        assert last_trading_day(date(2026, 5, 8)) == date(2026, 5, 8)

    def test_monday_returns_itself(self):
        assert last_trading_day(date(2026, 5, 12)) == date(2026, 5, 12)
