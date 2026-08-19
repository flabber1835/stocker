from __future__ import annotations

import pytest

from app.sharadar_adapter import map_sep_row


def test_sep_split_row_persists_raw_compatible_volume() -> None:
    row = {
        "ticker": "MGRM1",
        "date": "2007-12-31",
        "open": 7.92,
        "high": 8.7,
        "low": 7.86,
        "close": 8.52,
        "closeadj": 1.327,
        "closeunadj": 1.42,
        "volume": 254_133.3,
    }

    mapped = map_sep_row(row)

    assert mapped["close"] == pytest.approx(8.52)
    assert mapped["close_unadjusted"] == pytest.approx(1.42)
    assert mapped["volume"] == pytest.approx(1_524_799.8)
    assert mapped["close_unadjusted"] * mapped["volume"] == pytest.approx(
        row["close"] * row["volume"]
    )


def test_sep_non_split_row_preserves_volume() -> None:
    mapped = map_sep_row({
        "ticker": "AA",
        "date": "2025-06-13",
        "close": 28.35,
        "closeadj": 28.35,
        "closeunadj": 28.35,
        "volume": 3_200_000,
    })

    assert mapped["volume"] == pytest.approx(3_200_000)


def test_sep_does_not_invent_liquidity_domain_without_raw_close() -> None:
    mapped = map_sep_row({
        "ticker": "X",
        "date": "2025-06-13",
        "close": 10,
        "volume": 50_000,
    })

    assert mapped["close_unadjusted"] is None
    assert mapped["volume"] is None
