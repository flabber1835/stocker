from __future__ import annotations

import math
from datetime import datetime, timezone

import pytest

from sentinel.feed import sharadar, source_state
from sentinel.feed.domains import normalise_sep_rows
from stock_strategy_shared.wealth_core.eligibility import (
    EligibilityConfig,
    EligibilityInput,
    EligibilityReason,
    TerminalState,
    adv20_dollars,
    evaluate,
    signal_day_dollar_volume,
)
from stock_strategy_shared.wealth_core.sharadar_domains import raw_compatible_volume


# ── economic domain ──────────────────────────────────────────────────────────


def test_real_split_affected_row_preserves_dollar_liquidity() -> None:
    # Real shape from the supplied 2007 SEP corpus.
    adjusted_close = 8.52
    raw_close = 1.42
    reported_volume = 254_133.3
    raw_volume = raw_compatible_volume(adjusted_close, raw_close, reported_volume)
    assert raw_volume == pytest.approx(1_524_799.8)
    assert raw_close * raw_volume == pytest.approx(adjusted_close * reported_volume)


@pytest.mark.parametrize("adjusted,raw,reported", [
    (100.0, 100.0, 1_000_000.0),     # ordinary/no split
    (50.0, 100.0, 2_000_000.0),      # forward-split domain divergence
    (100.0, 20.0, 300_000.0),        # reverse-split domain divergence
])
def test_liquidity_invariant_holds_across_split_directions(adjusted, raw, reported):
    converted = raw_compatible_volume(adjusted, raw, reported)
    assert converted is not None
    assert raw * converted == pytest.approx(adjusted * reported)


def test_non_split_volume_is_unchanged() -> None:
    assert raw_compatible_volume(28.35, 28.35, 3_200_000) == pytest.approx(3_200_000)


def test_invalid_volume_domain_inputs_fail_closed() -> None:
    for values in [
        (None, 10, 100), (10, None, 100), (10, 10, None),
        (10, 0, 100), (10, 10, 0), (math.inf, 10, 100),
        (10, math.nan, 100),
    ]:
        assert raw_compatible_volume(*values) is None


def test_normaliser_emits_only_raw_compatible_liquidity_volume() -> None:
    row = {
        "ticker": "MGRM1", "date": "2007-12-31", "open": 7.92,
        "close": 8.52, "closeunadj": 1.42, "volume": 254_133.3,
    }
    [bar] = list(normalise_sep_rows([row]))
    assert bar.vendor.raw_close == pytest.approx(1.42)
    assert bar.vendor.volume == pytest.approx(1_524_799.8)
    assert bar.vendor.raw_close * bar.vendor.volume == pytest.approx(
        row["close"] * row["volume"])
    assert bar.vendor.tradeable is True


def test_dollar_volume_helpers_expect_raw_compatible_volume() -> None:
    assert signal_day_dollar_volume(1.0, 5_000_000.0) == pytest.approx(5_000_000.0)
    assert adv20_dollars([10.0] * 20, [2_000_000.0] * 20) == pytest.approx(20_000_000.0)


def _eligible_input(*, price=1.0, adv20=20_000_000.0,
                    signal_dv=5_000_000.0) -> EligibilityInput:
    closes = [100.0 + i * 0.1 for i in range(127)]
    return EligibilityInput(
        security_id="P:X", ticker="X", category="Domestic Common Stock",
        issuer_group_key="P:X", issuer_key_source="PERMATICKER",
        listed_on_session=True, unadjusted_signal_price=price,
        adv20_dollars=adv20, signal_dollar_volume=signal_dv,
        signal_closes_split_adj_div_unadj=closes,
        history_contiguous=True, terminal_state=TerminalState.NORMAL)


def test_all_three_liquidity_price_floors_are_inclusive() -> None:
    result = evaluate(_eligible_input(), EligibilityConfig())
    assert result.eligible is True
    assert result.reason is EligibilityReason.ELIGIBLE


@pytest.mark.parametrize("kwargs,reason", [
    ({"price": 0.999999}, EligibilityReason.PRICE_BELOW_MINIMUM),
    ({"adv20": 19_999_999.99}, EligibilityReason.ADV20_BELOW_MINIMUM),
    ({"signal_dv": 4_999_999.99}, EligibilityReason.SIGNAL_DOLLAR_VOLUME_BELOW_MINIMUM),
])
def test_just_below_financial_floors_fails(kwargs, reason) -> None:
    result = evaluate(_eligible_input(**kwargs), EligibilityConfig())
    assert result.eligible is False
    assert result.reason is reason


# ── mutation cursor / reconciliation schedule ────────────────────────────────


def test_mutation_query_is_inclusive_at_published_watermark() -> None:
    assert source_state.mutation_params("2026-08-17", "2026-08-18") == {
        "lastupdated.gte": "2026-08-17",
        "lastupdated.lte": "2026-08-18",
    }


def test_old_session_mutated_today_triggers_historical_year_refresh() -> None:
    scan = source_state.consume_mutations([
        {"ticker": "OLD", "date": "2007-12-31", "lastupdated": "2026-08-18"},
        {"ticker": "NEW", "date": "2026-08-18", "lastupdated": "2026-08-18"},
    ], current_overlap_start="2026-08-04", corpus_start="1998-01-01")
    assert scan.max_lastupdated == "2026-08-18"
    assert scan.historical_years == {2007}


def test_legacy_publication_without_mutation_cursor_fails_closed() -> None:
    with pytest.raises(source_state.SepMutationBaselineRequired):
        source_state.require_sep_watermark({})


def test_reconciliation_cursor_rotates_closed_years_and_repeats_after_wrap() -> None:
    assert source_state.next_reconciliation_year(
        {}, corpus_start="1998-01-01", through="2026-08-18") == 1998
    assert source_state.next_reconciliation_year(
        {"sep_reconciliation_last_year": 1998},
        corpus_start="1998-01-01", through="2026-08-18") == 1999
    assert source_state.next_reconciliation_year(
        {"sep_reconciliation_last_year": 2025},
        corpus_start="1998-01-01", through="2026-08-18") == 1998


# ── strict wire protocol ─────────────────────────────────────────────────────


def _sep_columns():
    return [{"name": name} for name in (
        "ticker", "date", "open", "close", "closeunadj", "closeadj",
        "volume", "lastupdated")]


def _valid_sep_payload(*, cursor=None, columns=None, rows=None):
    return {
        "datatable": {
            "columns": columns or _sep_columns(),
            "data": rows if rows is not None else [[
                "AAPL", "2026-08-18", 100.0, 101.0, 101.0, 101.0,
                1_000_000.0, "2026-08-18"]],
        },
        "meta": {"next_cursor_id": cursor},
    }


class _Response:
    status_code = 200
    headers: dict[str, str] = {}

    def __init__(self, payload) -> None:
        self.payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self):
        return self.payload


class _Client:
    def __init__(self, owner, timeout) -> None:
        self.owner = owner
        owner.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, *_args) -> None:
        return None

    def get(self, _url, *, params):
        self.owner.calls += 1
        self.owner.last_params = params
        index = min(self.owner.calls - 1, len(self.owner.payloads) - 1)
        return _Response(self.owner.payloads[index])


class _Http:
    def __init__(self, *payloads) -> None:
        self.payloads = list(payloads)
        self.calls = 0
        self.timeout = None
        self.last_params = None

    def Client(self, *, timeout):  # noqa: N802 - mirrors httpx API
        return _Client(self, timeout)


def _with_key(monkeypatch) -> None:
    monkeypatch.setenv("SHARADAR_API_KEY", "secret-that-must-not-leak")


def test_malformed_200_response_is_protocol_failure_without_retry(monkeypatch) -> None:
    _with_key(monkeypatch)
    http = _Http({})
    with pytest.raises(sharadar.SharadarProtocolError, match="datatable"):
        list(sharadar.fetch_table("SEP", http=http, sleep=lambda _delay: None))
    assert http.calls == 1
    assert http.timeout == sharadar.FETCH_TIMEOUT_SECS


def test_row_width_mismatch_is_protocol_failure(monkeypatch) -> None:
    _with_key(monkeypatch)
    http = _Http(_valid_sep_payload(rows=[["AAPL"]]))
    with pytest.raises(sharadar.SharadarProtocolError, match="1 values for 8 columns"):
        list(sharadar.fetch_table("SEP", http=http, sleep=lambda _delay: None))
    assert http.calls == 1


@pytest.mark.parametrize("payload,match", [
    ({"datatable": {"columns": [], "data": []},
      "meta": {"next_cursor_id": None}}, "columns"),
    ({"datatable": {"columns": _sep_columns() + [{"name": "ticker"}], "data": []},
      "meta": {"next_cursor_id": None}}, "repeats column"),
    ({"datatable": {"columns": _sep_columns(), "data": []}}, "meta"),
    ({"datatable": {"columns": _sep_columns(), "data": []}, "meta": {}},
     "next_cursor_id"),
])
def test_successful_http_with_malformed_envelope_never_yields(monkeypatch, payload, match):
    _with_key(monkeypatch)
    with pytest.raises(sharadar.SharadarProtocolError, match=match):
        list(sharadar.fetch_table("SEP", http=_Http(payload),
                                  sleep=lambda _delay: None))


def test_required_consumer_column_cannot_disappear(monkeypatch) -> None:
    _with_key(monkeypatch)
    cols = [c for c in _sep_columns() if c["name"] != "closeunadj"]
    with pytest.raises(sharadar.SharadarProtocolError, match="closeunadj"):
        list(sharadar.fetch_table(
            "SEP", http=_Http(_valid_sep_payload(columns=cols, rows=[])),
            sleep=lambda _delay: None))


def test_schema_cannot_change_between_cursor_pages(monkeypatch) -> None:
    _with_key(monkeypatch)
    first = _valid_sep_payload(cursor="page-2")
    second_cols = _sep_columns() + [{"name": "surprise"}]
    second = _valid_sep_payload(columns=second_cols,
                                rows=[["AAPL", "2026-08-18", 1, 1, 1, 1, 1,
                                       "2026-08-18", "x"]])
    with pytest.raises(sharadar.SharadarProtocolError, match="schema changed"):
        list(sharadar.fetch_table(
            "SEP", http=_Http(first, second), sleep=lambda _delay: None))


def test_caller_cannot_override_auth_or_cursor(monkeypatch) -> None:
    _with_key(monkeypatch)
    for params in ({"api_key": "attacker"}, {"qopts.cursor_id": "skip"},
                   {"QOPTS.CURSOR_ID": "skip"}):
        with pytest.raises(sharadar.SharadarTransportConfigError,
                           match="transport-owned"):
            list(sharadar.fetch_table("SEP", params=params,
                                      http=_Http(_valid_sep_payload()),
                                      sleep=lambda _delay: None))


def test_retry_after_parses_delta_and_http_date() -> None:
    now = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    assert sharadar.parse_retry_after("123", now=now) == pytest.approx(123)
    assert sharadar.parse_retry_after(
        "Tue, 18 Aug 2026 12:02:00 GMT", now=now) == pytest.approx(120)


def test_retry_after_applies_to_503_not_only_429() -> None:
    now = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)
    assert sharadar.retry_delay(0, 503, "120", now=now) == pytest.approx(120)


def test_secret_is_removed_from_rendered_request_target() -> None:
    rendered = sharadar._safe_request_target(
        "https://data.nasdaq.com/api/v3/datatables/SHARADAR/SEP.json",
        {"api_key": "super-secret", "date.gte": "2026-08-18"})
    assert "super-secret" not in rendered
    assert "api_key" not in rendered
