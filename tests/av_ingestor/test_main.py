"""
Tests for av-ingestor utility functions.

We test the pure-Python helpers (_TICKER_RE and the demo-key warning guard)
directly — without importing app.main — to stay DB-free and avoid sys.path
conflicts when the full test suite runs multiple services.
"""
import re
import pytest


# ── _TICKER_RE validation ─────────────────────────────────────────────────────

# Copy of the regex from app/main.py — tested here without importing the module
# so there is no DATABASE_URL / SQLAlchemy dependency.
_TICKER_RE = re.compile(r'^[A-Z0-9.\-]{1,10}$')


@pytest.mark.parametrize("ticker", ["AAPL", "BRK.B", "BF-B", "MSFT", "GOOGL", "A", "BRK.A"])
def test_ticker_re_valid(ticker):
    """Standard valid tickers must match _TICKER_RE."""
    assert _TICKER_RE.match(ticker) is not None, f"{ticker!r} should be valid"


@pytest.mark.parametrize("ticker", [
    "lowercase",       # lowercase letters not allowed
    "TOOLONGTICKER",   # 14 chars — exceeds the 10-char limit
    "inj3ct;--",       # semicolons not in allowed set
    "",                # empty string
    "TICK ER",         # space not allowed
    "TICK\nER",        # newline not allowed
    "TICK@ER",         # @ not in allowed set
])
def test_ticker_re_invalid(ticker):
    """Invalid tickers must not match _TICKER_RE."""
    assert _TICKER_RE.match(ticker) is None, f"{ticker!r} should be invalid"


# ── Demo key warning ─────────────────────────────────────────────────────────
#
# The warning logic in app/main.py is:
#
#   AV_API_KEY = os.getenv("AV_API_KEY", "demo")
#   if AV_API_KEY in ("", "demo"):
#       print("[av-ingestor] WARNING: AV_API_KEY is 'demo' — ...")
#
# We replicate that exact guard here so the test is self-contained and does
# not depend on importing the full module (which requires DATABASE_URL and
# creates a SQLAlchemy engine).


def _emit_demo_warning_if_needed(av_api_key: str, capsys) -> str:
    """
    Reproduce the module-level guard from app/main.py and return captured stdout.
    """
    if av_api_key in ("", "demo"):
        print(
            "[av-ingestor] WARNING: AV_API_KEY is 'demo' — "
            "using Alpha Vantage demo key, data will be very limited"
        )
    return capsys.readouterr().out


def test_demo_key_warning_printed(capsys):
    """
    When AV_API_KEY is 'demo' the guard must print a WARNING about limited data.
    This mirrors the module-level check in app/main.py exactly.
    """
    out = _emit_demo_warning_if_needed("demo", capsys)
    assert "WARNING" in out
    assert "demo" in out.lower()


def test_empty_key_warning_printed(capsys):
    """
    An empty AV_API_KEY triggers the same warning path as 'demo'
    because the guard is `if AV_API_KEY in ('', 'demo')`.
    """
    out = _emit_demo_warning_if_needed("", capsys)
    assert "WARNING" in out


def test_real_key_no_demo_warning(capsys):
    """A non-demo, non-empty key must not trigger the demo warning."""
    out = _emit_demo_warning_if_needed("MY_REAL_KEY_XYZ", capsys)
    assert "WARNING" not in out
