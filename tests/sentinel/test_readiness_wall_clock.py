import os
from pathlib import Path

from sentinel.feed import calendar as exchange_calendar


ROOT = Path(os.environ.get("SENTINEL_REPO_ROOT")
            or Path(__file__).resolve().parents[2])


def test_operational_readiness_defaults_to_a_real_instant_not_midnight():
    source = (ROOT / "sentinel" / "feed" / "readiness.py").read_text(
        encoding="utf-8")

    # No-argument check-data is an operational question: is this corpus ready
    # now? A date-only default is interpreted as exchange-local midnight and can
    # therefore pass Friday's frontier after Monday has already closed.
    assert "today = today or _dt.date.today().isoformat()" not in source
    assert (
        "today = today or _dt.datetime.now(_dt.timezone.utc).isoformat()"
        in source
    )

    # Explicit --today remains a caller-supplied historical observation point;
    # only the omitted/default case is replaced by the wall-clock instant.
    assert "fresh = _cal.freshness(frontier, now_et=today)" in source


def test_utc_wall_clock_and_explicit_date_have_the_intended_close_semantics():
    # 20:28 UTC is 16:28 ET on 2026-08-17, after the normal XNYS close. The
    # operational instant must therefore make Monday itself the latest closed
    # session, while an explicit date-only observation remains midnight ET and
    # conservatively refers to Friday's close.
    assert exchange_calendar.latest_closed_session(
        "2026-08-17T20:28:03+00:00") == "2026-08-17"
    assert exchange_calendar.latest_closed_session("2026-08-17") == "2026-08-14"
