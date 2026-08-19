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
    def __init__(self, row=None, error=None):
        self.row = row
        self.error = error
        self.sql = None

    def execute(self, stmt, params=None):
        self.sql = str(stmt)
        if self.error is not None:
            raise self.error
        return _Result(self.row)


def test_canonical_replay_refuses_even_one_legacy_volume_row():
    conn = _Conn({"n": 1000, "n_raw": 1000, "n_legacy": 1})
    with pytest.raises(RawPriceDomainUnavailable) as caught:
        assert_raw_price_domain(conn, "2020-01-01", "2020-12-31")
    message = str(caught.value)
    assert PRICE_VOLUME_DOMAIN in message
    assert "volume_domain_migration" in message
    assert "volume_domain_version" in conn.sql


def test_canonical_replay_accepts_fully_rewritten_volume_epoch():
    conn = _Conn({"n": 1000, "n_raw": 995, "n_legacy": 0})
    assert assert_raw_price_domain(
        conn, "2020-01-01", "2020-12-31") == pytest.approx(0.995)


def test_missing_semantic_epoch_schema_is_a_named_refusal():
    conn = _Conn(error=RuntimeError("column volume_domain_version does not exist"))
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
    assert "for _name in dir(_impl)" in facade
