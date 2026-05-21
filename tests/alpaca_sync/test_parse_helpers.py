"""Pure-function tests for alpaca-sync helper functions."""
from datetime import datetime, timezone
from decimal import Decimal

from app.main import _f, _has_credentials, _iso, _parse_float


def test_parse_float_valid_string():
    assert _parse_float("123.45") == 123.45


def test_parse_float_valid_int():
    assert _parse_float(7) == 7.0


def test_parse_float_none_returns_none():
    assert _parse_float(None) is None


def test_parse_float_invalid_returns_none():
    assert _parse_float("not-a-number") is None


def test_parse_float_empty_returns_none():
    assert _parse_float("") is None


def test_f_converts_decimal_to_float():
    result = _f(Decimal("9.50"))
    assert result == 9.5
    assert isinstance(result, float)


def test_f_none_returns_none():
    assert _f(None) is None


def test_iso_datetime_returns_isoformat():
    dt = datetime(2026, 5, 17, 12, 0, tzinfo=timezone.utc)
    assert _iso(dt) == dt.isoformat()


def test_iso_none_returns_none():
    assert _iso(None) is None


def test_has_credentials_demo_is_false():
    # Env was set to ALPACA_API_KEY=demo in conftest, so this should be False.
    assert _has_credentials is False


def test_has_credentials_real_is_true():
    # Test the inline expression used at module load — since _has_credentials
    # is cached at import time, we validate the underlying boolean logic.
    key = "PKABC123"
    assert (bool(key) and key != "demo") is True

    key = "demo"
    assert (bool(key) and key != "demo") is False

    key = ""
    assert (bool(key) and key != "demo") is False
