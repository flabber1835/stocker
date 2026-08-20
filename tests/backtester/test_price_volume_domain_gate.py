from __future__ import annotations

import pathlib

import pytest

from app.wealth_core_replay import (
    PRICE_VOLUME_DOMAIN,
    RawPriceDomainUnavailable,
    assert_raw_price_domain,
)


class _Result:
    def __init__(self, row):
        self.row = row

    def mappings(self):
        return self

    def first(self):
        return self.row


class _Conn:
    def __init__(self, rows=None, error=None):
        self.rows = list(rows or [])
        self.error = error
        self.sql = []

    def execute(self, stmt, params=None):
        self.sql.append(str(stmt))
        if self.error is not None:
            raise self.error
        if not self.rows:
            raise AssertionError("unexpected query")
        return _Result(self.rows.pop(0))


def test_canonical_replay_refuses_unproven_volume_singleton_before_price_scan():
    conn = _Conn([{
        "domain_version": PRICE_VOLUME_DOMAIN,
        "proven": False,
        "note": "legacy populated corpus requires volume-domain migration",
    }])
    with pytest.raises(RawPriceDomainUnavailable) as caught:
        assert_raw_price_domain(conn, "2020-01-01", "2020-12-31")
    message = str(caught.value)
    assert PRICE_VOLUME_DOMAIN in message
    assert "volume_domain_migration" in message
    assert len(conn.sql) == 1
    assert "bt_price_volume_domain_state" in conn.sql[0]


def test_canonical_replay_accepts_proven_epoch_then_uses_retained_raw_coverage():
    conn = _Conn([
        {"domain_version": PRICE_VOLUME_DOMAIN, "proven": True,
         "note": "complete migration"},
        {"n": 1000, "n_raw": 995},
    ])
    assert assert_raw_price_domain(
        conn, "2020-01-01", "2020-12-31") == pytest.approx(0.995)
    assert len(conn.sql) == 2
    assert "COUNT(close_unadjusted)" in conn.sql[1]


def test_missing_semantic_epoch_schema_is_a_named_refusal():
    conn = _Conn(error=RuntimeError("relation bt_price_volume_domain_state does not exist"))
    with pytest.raises(RawPriceDomainUnavailable) as caught:
        assert_raw_price_domain(conn, "2020-01-01", "2020-12-31")
    assert "cannot prove" in str(caught.value)
    assert "volume_domain_migration" in str(caught.value)


def test_public_facade_retains_original_replay_as_separate_implementation_blob():
    root = pathlib.Path(__file__).resolve().parents[2]
    facade = (root / "services" / "backtester" / "app" /
              "wealth_core_replay.py").read_text()
    retained = root / "services" / "backtester" / "app" / "wealth_core_replay_impl.py"
    assert retained.exists()
    assert "wealth_core_replay_impl as _impl" in facade
    assert "_impl.assert_raw_price_domain = assert_raw_price_domain" in facade
    assert "_ORIGINAL_ASSERT_RAW_PRICE_DOMAIN" in facade
    assert "for _name in dir(_impl)" in facade
