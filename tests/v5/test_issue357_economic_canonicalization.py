"""Issue #357 — exact split-domain economics across publication rebases."""
from copy import deepcopy
from dataclasses import replace
from decimal import Decimal

import pytest

from sentinel import shadow_observation as SO
from sentinel.feed import calendar
from sentinel.feed.domains import normalise_sep_rows
from tests.v5.test_shadow_publication_identity import (
    identity,
    runtime_for_gate,
    session_input,
    warmup,
)


RAW_CLOSE = Decimal("210")
RAW_VOLUME = 1_234_800
RAW_DIVIDEND = Decimal("2.10")
FACTORS = (3, 5, 7, 10)


def _source_values(factor: int = 1, *, reciprocal: bool = False,
                   raw_close: Decimal = RAW_CLOSE,
                   raw_volume: int = RAW_VOLUME,
                   raw_dividend: Decimal = RAW_DIVIDEND):
    f = Decimal(factor)
    if factor == 1:
        return raw_close, raw_volume, raw_dividend
    if reciprocal:
        # Reciprocal rebase: adjusted price is on a larger share-unit basis.
        return raw_close * f, raw_volume // factor, raw_dividend * f
    return raw_close / f, raw_volume * factor, raw_dividend / f


def _normalise_one(*, adjusted_close, raw_close=RAW_CLOSE, volume=RAW_VOLUME,
                   dividend=RAW_DIVIDEND, session="2026-01-02"):
    row = {
        "date": session,
        "ticker": "AAA",
        "close": str(adjusted_close),
        "closeunadj": str(raw_close),
        "open": str(adjusted_close),
        "volume": volume,
    }
    result = list(normalise_sep_rows(
        [row], resolve_identity=lambda ticker, day: "1",
        dividends={("AAA", session): str(dividend)}))
    assert len(result) == 1
    return result[0]


@pytest.mark.parametrize("factor", FACTORS)
@pytest.mark.parametrize("reciprocal", [False, True])
def test_equivalent_source_rebases_canonicalize_volume_dividend_and_liquidity(
        factor, reciprocal):
    baseline = _normalise_one(adjusted_close=RAW_CLOSE)
    adjusted, volume, dividend = _source_values(
        factor, reciprocal=reciprocal)
    rebased = _normalise_one(
        adjusted_close=adjusted, volume=volume, dividend=dividend)

    assert rebased.vendor.volume == baseline.vendor.volume == float(RAW_VOLUME)
    assert (rebased.vendor.dividend_per_share
            == baseline.vendor.dividend_per_share == float(RAW_DIVIDEND))
    assert (rebased.vendor.raw_close * rebased.vendor.volume
            == baseline.vendor.raw_close * baseline.vendor.volume)


def _publication_rows(axis, *, factor=1, reciprocal=False,
                      volume_correction=0, dividend_correction=Decimal(0)):
    rows = []
    dividends = {}
    for i, day in enumerate(axis):
        # Every raw price remains exactly divisible by 3, 5, 7 and 10 in finite
        # decimal arithmetic, so the rebases below are genuinely equivalent.
        raw = RAW_CLOSE + Decimal(i) * Decimal("10.5")
        adjusted, volume, dividend = _source_values(
            factor, reciprocal=reciprocal, raw_close=raw,
            raw_volume=RAW_VOLUME, raw_dividend=RAW_DIVIDEND)
        if i == 70:
            volume += volume_correction
            dividend += dividend_correction
            dividends[("AAA", day)] = str(dividend)
        rows.append({
            "date": day,
            "ticker": "AAA",
            "close": str(adjusted),
            "closeunadj": str(raw),
            "open": str(adjusted),
            "volume": volume,
        })
    return rows, dividends


def _populate(window, axis, *, factor=1, reciprocal=False,
              volume_correction=0, dividend_correction=Decimal(0)):
    rows, dividends = _publication_rows(
        axis, factor=factor, reciprocal=reciprocal,
        volume_correction=volume_correction,
        dividend_correction=dividend_correction)
    normalized = list(normalise_sep_rows(
        rows, resolve_identity=lambda ticker, day: "1", dividends=dividends))
    assert len(normalized) == len(axis)
    for item in normalized:
        window.bars_by_session[item.vendor.session] = [
            replace(item.vendor, signal_close=item.close_signal)]
    return window


@pytest.mark.parametrize("factor", FACTORS)
@pytest.mark.parametrize("reciprocal", [False, True])
def test_equivalent_raw_publications_preserve_warmup_identity_and_revision_gate(
        factor, reciprocal):
    axis, template = warmup()
    baseline = _populate(deepcopy(template), axis)
    rebased = _populate(
        deepcopy(template), axis, factor=factor, reciprocal=reciprocal)

    assert identity(rebased) == identity(baseline)
    assert runtime_for_gate(baseline, rebased)._require_current_warmup_input() \
        == identity(baseline)["warmup_input_sha256"]


def _daily_identity(*, factor=1, reciprocal=False,
                    volume_correction=0,
                    dividend_correction=Decimal(0)):
    published = session_input()
    axis = calendar.previous_sessions(published.session, 2)
    rows, dividends = _publication_rows(
        axis, factor=factor, reciprocal=reciprocal,
        volume_correction=volume_correction,
        dividend_correction=dividend_correction)
    bars = [replace(item.vendor, signal_close=item.close_signal)
            for item in normalise_sep_rows(
                rows, resolve_identity=lambda ticker, day: "1",
                dividends=dividends)]
    return SO._economic_input_identity(replace(
        published, bars=[bars[-1]], signal_basis_anchors={"1": bars[0]}))


@pytest.mark.parametrize("factor", FACTORS)
@pytest.mark.parametrize("reciprocal", [False, True])
def test_equivalent_raw_publications_preserve_daily_economic_identity(
        factor, reciprocal):
    assert _daily_identity(factor=factor, reciprocal=reciprocal) \
        == _daily_identity()


def test_genuine_volume_and_dividend_corrections_remain_visible():
    baseline = _daily_identity()
    assert _daily_identity(factor=5, volume_correction=1) != baseline
    assert _daily_identity(
        factor=5, dividend_correction=Decimal("0.000001")) != baseline
