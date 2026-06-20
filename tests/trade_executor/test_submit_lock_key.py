"""Unit tests for submit_lock_key (audit #8 — atomic approve-and-reserve).

The advisory-lock key must be:
  - deterministic / stable across processes and runs (two submits for the same
    (account, trading_day) MUST collide on the same lock),
  - a valid Postgres bigint (signed 64-bit),
  - distinct for distinct accounts or distinct days (so they do NOT serialize
    against each other).

These are pure-function properties — no DB needed.
"""
from app.submit_lock import submit_lock_key

_INT64_MIN = -(2 ** 63)
_INT64_MAX = (2 ** 63) - 1


def test_key_is_deterministic():
    a = submit_lock_key("alpaca-paper", "2026-06-19")
    b = submit_lock_key("alpaca-paper", "2026-06-19")
    assert a == b


def test_key_in_signed_64bit_range():
    # A spread of inputs must all land inside Postgres bigint range.
    for acct in ("alpaca-paper", "alpaca-live", "x"):
        for day in ("2026-06-19", "2026-01-01", "1999-12-31", "2030-02-28"):
            k = submit_lock_key(acct, day)
            assert isinstance(k, int)
            assert _INT64_MIN <= k <= _INT64_MAX


def test_distinct_days_distinct_keys():
    k1 = submit_lock_key("alpaca-paper", "2026-06-19")
    k2 = submit_lock_key("alpaca-paper", "2026-06-20")
    assert k1 != k2


def test_distinct_accounts_distinct_keys():
    k1 = submit_lock_key("alpaca-paper", "2026-06-19")
    k2 = submit_lock_key("alpaca-live", "2026-06-19")
    assert k1 != k2


def test_no_collisions_over_a_year_of_days():
    # Sanity: a full year of trading days for one account should produce all-distinct
    # keys (64-bit space makes accidental collision astronomically unlikely; a
    # collision here would mean a hashing regression).
    import datetime as _dt

    keys = set()
    d = _dt.date(2026, 1, 1)
    for _ in range(366):
        keys.add(submit_lock_key("alpaca-paper", d.isoformat()))
        d += _dt.timedelta(days=1)
    assert len(keys) == 366
