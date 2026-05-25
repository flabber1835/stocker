from datetime import date

import pytest

from app.staleness import count_missed_trading_days, is_stale, last_trading_day


# ── helpers ───────────────────────────────────────────────────────────────────

def _d(s: str) -> date:
    return date.fromisoformat(s)


# ═══════════════════════════════════════════════════════════════════════════════
# last_trading_day
# ═══════════════════════════════════════════════════════════════════════════════

class TestLastTradingDayWeekdays:
    """Baseline: regular weekdays with no holidays."""

    @pytest.mark.parametrize("d,expected", [
        ("2026-05-11", "2026-05-11"),  # Monday
        ("2026-05-12", "2026-05-12"),  # Tuesday
        ("2026-05-13", "2026-05-13"),  # Wednesday
        ("2026-05-14", "2026-05-14"),  # Thursday
        ("2026-05-15", "2026-05-15"),  # Friday
    ])
    def test_regular_weekday_returns_itself(self, d, expected):
        assert last_trading_day(_d(d)) == _d(expected)

    def test_saturday_returns_friday(self):
        assert last_trading_day(_d("2026-05-09")) == _d("2026-05-08")

    def test_sunday_returns_friday(self):
        assert last_trading_day(_d("2026-05-10")) == _d("2026-05-08")


class TestLastTradingDayMondayHolidays:
    """Monday holidays create a Fri→Tue 4-day gap; last session must be the
    preceding Friday, not the holiday Monday."""

    def test_memorial_day_2026(self):
        # THE BUG: was returning 2026-05-25 (Mon), must return 2026-05-22 (Fri)
        assert last_trading_day(_d("2026-05-25")) == _d("2026-05-22")

    def test_day_after_memorial_day_returns_itself(self):
        assert last_trading_day(_d("2026-05-26")) == _d("2026-05-26")

    def test_mlk_day_2026(self):
        assert last_trading_day(_d("2026-01-19")) == _d("2026-01-16")

    def test_day_after_mlk_returns_itself(self):
        assert last_trading_day(_d("2026-01-20")) == _d("2026-01-20")

    def test_labor_day_2026(self):
        assert last_trading_day(_d("2026-09-07")) == _d("2026-09-04")

    def test_day_after_labor_day_returns_itself(self):
        assert last_trading_day(_d("2026-09-08")) == _d("2026-09-08")

    def test_presidents_day_2026(self):
        assert last_trading_day(_d("2026-02-16")) == _d("2026-02-13")


class TestLastTradingDayFridayHolidays:
    """Friday holidays extend the weekend to Sat+Sun+Fri = 3 days; last
    session must be the Thursday before."""

    def test_good_friday_2026(self):
        assert last_trading_day(_d("2026-04-03")) == _d("2026-04-02")

    def test_day_after_good_friday_is_weekend(self):
        # Saturday after Good Friday → Thursday still
        assert last_trading_day(_d("2026-04-04")) == _d("2026-04-02")

    def test_monday_after_good_friday_returns_itself(self):
        assert last_trading_day(_d("2026-04-06")) == _d("2026-04-06")

    def test_july_4_observed_friday_2026(self):
        # July 4 is Saturday; NYSE observes the holiday on Friday Jul 3
        assert last_trading_day(_d("2026-07-03")) == _d("2026-07-02")

    def test_july_4_saturday_2026(self):
        # Saturday of the holiday weekend → Thursday Jul 2
        assert last_trading_day(_d("2026-07-04")) == _d("2026-07-02")

    def test_monday_after_july_4_weekend_returns_itself(self):
        assert last_trading_day(_d("2026-07-06")) == _d("2026-07-06")


class TestLastTradingDayThursdayHolidays:
    """Thursday holidays (Thanksgiving, Christmas 2025, New Year 2026)."""

    def test_thanksgiving_2026(self):
        assert last_trading_day(_d("2026-11-26")) == _d("2026-11-25")

    def test_black_friday_2026_returns_itself(self):
        # Black Friday: NYSE is open (half day)
        assert last_trading_day(_d("2026-11-27")) == _d("2026-11-27")

    def test_christmas_2025_thursday(self):
        assert last_trading_day(_d("2025-12-25")) == _d("2025-12-24")

    def test_christmas_eve_2025_returns_itself(self):
        assert last_trading_day(_d("2025-12-24")) == _d("2025-12-24")

    def test_friday_after_christmas_2025_returns_itself(self):
        # Dec 26 is a Friday — NYSE is open
        assert last_trading_day(_d("2025-12-26")) == _d("2025-12-26")

    def test_new_year_2026_thursday(self):
        assert last_trading_day(_d("2026-01-01")) == _d("2025-12-31")

    def test_new_year_eve_2025_returns_itself(self):
        assert last_trading_day(_d("2025-12-31")) == _d("2025-12-31")


class TestLastTradingDayHolidayPlusWeekend:
    """Holiday immediately before or after a weekend — the hardest case to get
    right with a naive weekend-only skip loop."""

    def test_holiday_monday_preceded_by_normal_weekend(self):
        # Sat+Sun before Memorial Day Monday → must go back to prior Friday
        assert last_trading_day(_d("2026-05-23")) == _d("2026-05-22")  # Sat
        assert last_trading_day(_d("2026-05-24")) == _d("2026-05-22")  # Sun
        assert last_trading_day(_d("2026-05-25")) == _d("2026-05-22")  # Mon holiday

    def test_holiday_friday_preceded_by_normal_thursday(self):
        # Good Friday: Thu is last session, Fri+Sat+Sun are all non-sessions
        assert last_trading_day(_d("2026-04-03")) == _d("2026-04-02")  # Fri holiday
        assert last_trading_day(_d("2026-04-04")) == _d("2026-04-02")  # Sat
        assert last_trading_day(_d("2026-04-05")) == _d("2026-04-02")  # Sun

    def test_holiday_thursday_with_open_friday(self):
        # Thanksgiving Thu: Wed is last before holiday, Fri is open
        assert last_trading_day(_d("2026-11-26")) == _d("2026-11-25")  # Thu holiday
        assert last_trading_day(_d("2026-11-27")) == _d("2026-11-27")  # Fri open

    def test_christmas_thursday_holiday_xmas_eve_open(self):
        # Christmas Thu 2025: Wed Dec 24 is open, Thu is holiday, Fri Dec 26 is open
        assert last_trading_day(_d("2025-12-25")) == _d("2025-12-24")  # Thu holiday
        assert last_trading_day(_d("2025-12-26")) == _d("2025-12-26")  # Fri open
        assert last_trading_day(_d("2025-12-27")) == _d("2025-12-26")  # Sat → Fri
        assert last_trading_day(_d("2025-12-28")) == _d("2025-12-26")  # Sun → Fri

    def test_new_year_thursday_holiday_new_year_eve_open(self):
        # New Year Thu 2026: Wed Dec 31 is open, Thu Jan 1 is holiday, Fri Jan 2 is open
        assert last_trading_day(_d("2026-01-01")) == _d("2025-12-31")  # Thu holiday
        assert last_trading_day(_d("2026-01-02")) == _d("2026-01-02")  # Fri open


class TestLastTradingDayChristmasNewYearBridge:
    """Back-to-back holiday cluster: Christmas (Thu Dec 25) + New Year (Thu Jan 1)
    with open days in between.  No two consecutive NYSE holidays exist in the
    same week in US markets, but two holiday-weekends in the same fortnight
    is the realistic stress test."""

    def test_week_between_christmas_and_new_year(self):
        # Dec 26 (Fri open), Dec 29 (Mon), Dec 30 (Tue), Dec 31 (Wed open),
        # Jan 1 (Thu holiday), Jan 2 (Fri open)
        assert last_trading_day(_d("2025-12-29")) == _d("2025-12-29")
        assert last_trading_day(_d("2025-12-30")) == _d("2025-12-30")
        assert last_trading_day(_d("2025-12-31")) == _d("2025-12-31")
        assert last_trading_day(_d("2026-01-01")) == _d("2025-12-31")  # holiday → Wed
        assert last_trading_day(_d("2026-01-02")) == _d("2026-01-02")  # Fri open


# ═══════════════════════════════════════════════════════════════════════════════
# count_missed_trading_days
# ═══════════════════════════════════════════════════════════════════════════════

class TestCountMissedTradingDaysBaseline:
    """Baseline cases without holidays — must still pass after the calendar fix."""

    def test_consecutive_weekdays_no_gap(self):
        assert count_missed_trading_days(_d("2026-05-11"), _d("2026-05-12")) == 0

    def test_one_missed_weekday(self):
        assert count_missed_trading_days(_d("2026-05-11"), _d("2026-05-13")) == 1

    def test_two_missed_weekdays(self):
        assert count_missed_trading_days(_d("2026-05-11"), _d("2026-05-14")) == 2

    def test_friday_to_monday_no_gap(self):
        assert count_missed_trading_days(_d("2026-05-08"), _d("2026-05-11")) == 0

    def test_friday_to_tuesday_one_gap(self):
        assert count_missed_trading_days(_d("2026-05-08"), _d("2026-05-12")) == 1

    def test_same_day_zero(self):
        assert count_missed_trading_days(_d("2026-05-11"), _d("2026-05-11")) == 0

    def test_today_before_last_run_zero(self):
        assert count_missed_trading_days(_d("2026-05-13"), _d("2026-05-11")) == 0

    def test_full_week_missed(self):
        # Monday → next Monday: Tue–Fri = 4 sessions
        assert count_missed_trading_days(_d("2026-05-11"), _d("2026-05-18")) == 4


class TestCountMissedMondayHoliday:
    """Monday market holiday: the holiday must NOT be counted as a missed day."""

    def test_friday_to_monday_memorial_day_zero(self):
        # THE BUG SCENARIO: Friday's data, check on Memorial Day Monday
        # Old behaviour: 1 (wrongly counted holiday as missed)
        # New behaviour: 0
        assert count_missed_trading_days(_d("2026-05-22"), _d("2026-05-25")) == 0

    def test_friday_to_tuesday_after_memorial_day_zero(self):
        # Friday's data, check Tuesday after Memorial Day — still no MISSED sessions
        # (Tuesday itself is today, excluded by definition)
        assert count_missed_trading_days(_d("2026-05-22"), _d("2026-05-26")) == 0

    def test_thursday_to_tuesday_after_memorial_day_one(self):
        # Thursday's data, check Tuesday — Friday (a real session) is missed,
        # but Monday (holiday) is not
        assert count_missed_trading_days(_d("2026-05-21"), _d("2026-05-26")) == 1

    def test_wednesday_to_tuesday_after_memorial_day_two(self):
        # Wednesday's data, check Tuesday — Thu + Fri are missed, Mon is not
        assert count_missed_trading_days(_d("2026-05-20"), _d("2026-05-26")) == 2

    def test_mlk_day_2026(self):
        assert count_missed_trading_days(_d("2026-01-16"), _d("2026-01-19")) == 0

    def test_labor_day_2026(self):
        assert count_missed_trading_days(_d("2026-09-04"), _d("2026-09-07")) == 0


class TestCountMissedFridayHoliday:
    """Friday market holiday: the holiday extends the weekend to Thu–Mon."""

    def test_thursday_to_monday_across_good_friday_zero(self):
        # Thu Apr 2 data, check Mon Apr 6 — Good Friday (Apr 3) is a holiday
        assert count_missed_trading_days(_d("2026-04-02"), _d("2026-04-06")) == 0

    def test_wednesday_to_monday_across_good_friday_one(self):
        # Wed Apr 1 data, check Mon Apr 6 — Thu Apr 2 is a real missed session
        assert count_missed_trading_days(_d("2026-04-01"), _d("2026-04-06")) == 1

    def test_wednesday_to_tuesday_across_good_friday_two(self):
        # Wed Apr 1 data, check Tue Apr 7 — Thu Apr 2 + Mon Apr 6 missed
        assert count_missed_trading_days(_d("2026-04-01"), _d("2026-04-07")) == 2

    def test_thursday_to_monday_across_july4_observed_zero(self):
        # Jul 4 is Saturday; Jul 3 (Fri) is the observed holiday
        # Thu Jul 2 data, check Mon Jul 6 — Fri Jul 3 is a holiday
        assert count_missed_trading_days(_d("2026-07-02"), _d("2026-07-06")) == 0

    def test_wednesday_to_monday_across_july4_observed_one(self):
        # Wed Jul 1 data, check Mon Jul 6 — Thu Jul 2 is a real missed session
        assert count_missed_trading_days(_d("2026-07-01"), _d("2026-07-06")) == 1

    def test_wednesday_to_tuesday_across_july4_two(self):
        # Wed Jul 1 data, check Tue Jul 7 — Thu Jul 2 + Mon Jul 6 missed
        assert count_missed_trading_days(_d("2026-07-01"), _d("2026-07-07")) == 2


class TestCountMissedThursdayHoliday:
    """Thursday market holiday: Thanksgiving, Christmas 2025, New Year 2026."""

    def test_wednesday_to_friday_across_thanksgiving_zero(self):
        # Wed Nov 25 data, check Fri Nov 27 — Thu Nov 26 (Thanksgiving) not counted
        assert count_missed_trading_days(_d("2026-11-25"), _d("2026-11-27")) == 0

    def test_wednesday_to_monday_thanksgiving_weekend_one(self):
        # Wed Nov 25 data, check Mon Nov 30 — Fri Nov 27 (Black Friday, open) is missed
        assert count_missed_trading_days(_d("2026-11-25"), _d("2026-11-30")) == 1

    def test_tuesday_to_monday_thanksgiving_week_two(self):
        # Tue Nov 24 data, check Mon Nov 30 — Wed Nov 25 + Fri Nov 27 missed
        assert count_missed_trading_days(_d("2026-11-24"), _d("2026-11-30")) == 2

    def test_wednesday_to_friday_across_christmas_zero(self):
        # Wed Dec 24 data, check Fri Dec 26 — Christmas (Thu Dec 25) not counted
        assert count_missed_trading_days(_d("2025-12-24"), _d("2025-12-26")) == 0

    def test_wednesday_to_monday_after_christmas_one(self):
        # Wed Dec 24 data, check Mon Dec 29 — Fri Dec 26 (open) is missed
        assert count_missed_trading_days(_d("2025-12-24"), _d("2025-12-29")) == 1

    def test_tuesday_to_monday_after_christmas_two(self):
        # Tue Dec 23 data, check Mon Dec 29 — Wed Dec 24 + Fri Dec 26 missed
        assert count_missed_trading_days(_d("2025-12-23"), _d("2025-12-29")) == 2

    def test_wednesday_dec31_to_friday_jan2_zero(self):
        # Dec 31 (Wed) data, check Jan 2 (Fri) — Jan 1 (Thu) is a holiday
        assert count_missed_trading_days(_d("2025-12-31"), _d("2026-01-02")) == 0

    def test_tuesday_dec30_to_monday_jan5_two(self):
        # Dec 30 (Tue) data, check Jan 5 (Mon) — Dec 31 + Jan 2 missed; Jan 1 is holiday
        assert count_missed_trading_days(_d("2025-12-30"), _d("2026-01-05")) == 2


class TestCountMissedChristmasNewYearBridge:
    """The full Christmas→New Year fortnight: two holiday clusters in 8 days."""

    def test_friday_before_christmas_to_friday_after_new_year(self):
        # Dec 19 (Fri) data, check Jan 9 (Fri 2026)
        # Missed sessions: Dec 22, 23, 24, 26, 29, 30, 31, Jan 2, 5, 6, 7, 8 = 12
        # Not missed: Dec 25 (Xmas), Jan 1 (New Year), weekends
        assert count_missed_trading_days(_d("2025-12-19"), _d("2026-01-09")) == 12

    def test_christmas_eve_to_new_year_day_one(self):
        # Dec 24 (open, Wed) data, check Jan 1 (holiday Thu)
        # Missed: Dec 26 (Fri), Dec 29 (Mon), Dec 30 (Tue), Dec 31 (Wed) = 4
        assert count_missed_trading_days(_d("2025-12-24"), _d("2026-01-01")) == 4


# ═══════════════════════════════════════════════════════════════════════════════
# is_stale
# ═══════════════════════════════════════════════════════════════════════════════

class TestIsStaleBaseline:
    """Baseline cases that must still pass after the calendar rewrite."""

    def test_none_always_stale(self):
        assert is_stale(None, _d("2026-05-17")) is True

    def test_same_day_not_stale(self):
        assert is_stale(_d("2026-05-17"), _d("2026-05-17")) is False

    def test_last_run_future_not_stale(self):
        assert is_stale(_d("2026-05-18"), _d("2026-05-17")) is False

    def test_consecutive_weekday_not_stale(self):
        assert is_stale(_d("2026-05-11"), _d("2026-05-12")) is False

    def test_one_missed_weekday_stale(self):
        assert is_stale(_d("2026-05-11"), _d("2026-05-13")) is True

    def test_friday_to_monday_not_stale(self):
        assert is_stale(_d("2026-05-08"), _d("2026-05-11")) is False

    def test_friday_to_tuesday_stale(self):
        assert is_stale(_d("2026-05-08"), _d("2026-05-12")) is True


class TestIsStaleHolidays:
    """Key insight: a market holiday is NOT a missed trading day, so checking
    ON a holiday or the day after a holiday weekend should not trigger a
    spurious stale flag."""

    def test_friday_data_on_memorial_day_not_stale(self):
        # THE TRIGGER CASE: scheduler runs on Memorial Day and sees Friday's data
        # Old behaviour: stale=True → triggers extra fetch
        # New behaviour: stale=False → correctly idle
        assert is_stale(_d("2026-05-22"), _d("2026-05-25")) is False

    def test_friday_data_on_tuesday_after_memorial_day_not_stale(self):
        # Tuesday is today (scheduled run), Friday is last data — no sessions missed
        assert is_stale(_d("2026-05-22"), _d("2026-05-26")) is False

    def test_thursday_data_on_tuesday_after_memorial_day_stale(self):
        # Thursday's data, now Tuesday — Friday was a real missed session
        assert is_stale(_d("2026-05-21"), _d("2026-05-26")) is True

    def test_friday_data_on_memorial_day_monday_then_tuesday_stale(self):
        # Chain: Friday data → Monday holiday (not stale) → Tuesday (not stale,
        # Tuesday is today and hasn't closed yet)
        assert is_stale(_d("2026-05-22"), _d("2026-05-25")) is False
        assert is_stale(_d("2026-05-22"), _d("2026-05-26")) is False

    def test_friday_data_on_good_friday_not_stale(self):
        assert is_stale(_d("2026-04-02"), _d("2026-04-03")) is False

    def test_thursday_data_on_monday_after_good_friday_not_stale(self):
        # Thu data, Mon Apr 6 is today — Good Friday was in between, no missed sessions
        assert is_stale(_d("2026-04-02"), _d("2026-04-06")) is False

    def test_wednesday_data_on_monday_after_good_friday_stale(self):
        # Wed data, Mon Apr 6 is today — Thursday Apr 2 was missed
        assert is_stale(_d("2026-04-01"), _d("2026-04-06")) is True

    def test_friday_data_on_thanksgiving_not_stale(self):
        assert is_stale(_d("2026-11-25"), _d("2026-11-26")) is False

    def test_wednesday_data_on_monday_after_thanksgiving_stale(self):
        # Wed data, Mon Nov 30 today — Black Friday (open) was missed
        assert is_stale(_d("2026-11-25"), _d("2026-11-30")) is True

    def test_friday_data_on_christmas_day_not_stale(self):
        assert is_stale(_d("2025-12-24"), _d("2025-12-25")) is False

    def test_wednesday_data_on_new_year_day_stale(self):
        # Dec 24 (Wed) data, Jan 1 today — Dec 26, 29, 30, 31 were all missed
        assert is_stale(_d("2025-12-24"), _d("2026-01-01")) is True

    def test_mlk_day_not_stale(self):
        assert is_stale(_d("2026-01-16"), _d("2026-01-19")) is False

    def test_labor_day_not_stale(self):
        assert is_stale(_d("2026-09-04"), _d("2026-09-07")) is False

    def test_july4_observed_friday_not_stale(self):
        assert is_stale(_d("2026-07-02"), _d("2026-07-03")) is False

    def test_presidents_day_not_stale(self):
        assert is_stale(_d("2026-02-13"), _d("2026-02-16")) is False


class TestIsStaleHolidayRandomisation:
    """Parameterised stress test: (last_run, today, expected_stale) triples
    drawn from several distinct holiday patterns to prevent any single
    holiday from masking others."""

    @pytest.mark.parametrize("last_run,today,stale,note", [
        # Memorial Day cluster (Mon)
        ("2026-05-22", "2026-05-25", False, "Fri data, check Memorial Day"),
        ("2026-05-22", "2026-05-26", False, "Fri data, check Tue after Memorial Day"),
        ("2026-05-21", "2026-05-26", True,  "Thu data, check Tue — Fri missed"),
        # Good Friday cluster (Fri)
        ("2026-04-02", "2026-04-03", False, "Thu data, check Good Friday"),
        ("2026-04-02", "2026-04-06", False, "Thu data, check Mon after Good Friday"),
        ("2026-04-01", "2026-04-06", True,  "Wed data, check Mon — Thu Apr 2 missed"),
        # July 4 observed Friday cluster
        ("2026-07-02", "2026-07-03", False, "Thu data, check observed Jul 4 Fri"),
        ("2026-07-02", "2026-07-06", False, "Thu data, check Mon after Jul 4 weekend"),
        ("2026-07-01", "2026-07-06", True,  "Wed data, check Mon — Thu Jul 2 missed"),
        # Thanksgiving cluster (Thu)
        ("2026-11-25", "2026-11-26", False, "Wed data, check Thanksgiving"),
        ("2026-11-25", "2026-11-27", False, "Wed data, check Black Friday (open)"),
        ("2026-11-25", "2026-11-30", True,  "Wed data, check Mon — Fri missed"),
        ("2026-11-26", "2026-11-30", True,  "Thanksgiving data, check Mon — Black Friday (open) was missed"),
        # Christmas 2025 cluster (Thu)
        ("2025-12-24", "2025-12-25", False, "Xmas Eve data, check Christmas"),
        ("2025-12-24", "2025-12-26", False, "Xmas Eve data, check Fri Dec 26"),
        ("2025-12-24", "2025-12-29", True,  "Xmas Eve data, check Mon — Fri Dec 26 missed"),
        ("2025-12-26", "2025-12-29", False, "Fri Dec 26 data, check Mon Dec 29"),
        # New Year 2026 cluster (Thu)
        ("2025-12-31", "2026-01-01", False, "NYE data, check New Year's Day"),
        ("2025-12-31", "2026-01-02", False, "NYE data, check Fri Jan 2"),
        ("2025-12-30", "2026-01-02", True,  "Tue Dec 30 data, check Fri — Dec 31 missed"),
        # MLK Day (Mon) + Presidents Day (Mon) back-to-back month
        ("2026-01-16", "2026-01-19", False, "Fri data, check MLK Day"),
        ("2026-01-16", "2026-01-20", False, "Fri data, check Tue after MLK"),
        ("2026-02-13", "2026-02-16", False, "Fri data, check Presidents Day"),
        ("2026-02-13", "2026-02-17", False, "Fri data, check Tue after Presidents Day"),
    ])
    def test_holiday_stale_matrix(self, last_run, today, stale, note):
        assert is_stale(_d(last_run), _d(today)) is stale, note
