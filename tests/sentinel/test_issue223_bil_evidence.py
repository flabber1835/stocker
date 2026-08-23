"""Issue #223 — BIL is published evidence, never an SEP/cash substitute."""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from sentinel import identity, paper, trial
from sentinel.execution.projection import project
from sentinel.execution import reconcile
from sentinel.feed import coherence, ingest_impl
from sentinel.feed import runtime_schema
from sentinel.feed import store as feed_store


class _Cursor:
    def __init__(self, owner):
        self.owner = owner
        self.rows = []

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def execute(self, statement, params=()):
        self.owner.statements.append((str(statement), params))
        self.rows = list(self.owner.results.pop(0))

    def executemany(self, statement, rows):
        materialized = list(rows)
        self.owner.statements.append((str(statement), materialized))

    def fetchall(self):
        return list(self.rows)

    def fetchone(self):
        return self.rows[0] if self.rows else None


class _Connection:
    def __init__(self, *results):
        self.results = [list(result) for result in results]
        self.statements = []
        self.commits = 0

    def cursor(self):
        return _Cursor(self)

    def commit(self):
        self.commits += 1


def test_bounded_sfp_observation_is_partitioned_without_broadening_sep(
        monkeypatch):
    calls = []
    monkeypatch.setattr(
        feed_store, "write_spy_total_return",
        lambda _conn, rows, **kwargs: (
            calls.append(("SPY", list(rows), kwargs)) or len(calls[-1][1])))
    monkeypatch.setattr(
        feed_store, "write_defensive_bars",
        lambda _conn, rows, **kwargs: (
            calls.append(("BIL", list(rows), kwargs)) or len(calls[-1][1])))

    written = ingest_impl._write_sfp_reference_rows(  # noqa: SLF001
        object(), [
            {"ticker": "SPY", "date": "2026-08-20", "open": 699,
             "close": 700, "closeadj": 700, "closeunadj": 700},
            {"ticker": "BIL", "date": "2026-08-20",
             "open": 91.3, "close": 91.4, "closeadj": 91.5,
             "closeunadj": 91.4},
        ], run_id="run-223")

    assert written == 2
    assert [call[0] for call in calls] == ["SPY", "BIL"]
    assert [[row["ticker"] for row in call[1]] for call in calls] == [
        ["SPY"], ["BIL"]]
    assert all(call[2]["require_lock"] is True for call in calls)


def test_bounded_sfp_observation_refuses_an_unrequested_fund(monkeypatch):
    monkeypatch.setattr(
        feed_store, "write_spy_total_return",
        lambda *_args, **_kwargs: pytest.fail("writer must not be reached"))
    with pytest.raises(ValueError, match="unexpected tickers"):
        ingest_impl._write_sfp_reference_rows(  # noqa: SLF001
            object(), [{"ticker": "TLT", "date": "2026-08-20"}],
            run_id="run-223")


def test_defensive_writer_pins_identity_and_retains_scalar_source_fields():
    conn = _Connection()

    assert feed_store.write_defensive_bars(conn, [{
        "ticker": "bil", "date": "2026-08-20",
        "open": "91.20", "close": "91.25", "closeadj": "91.30",
        "closeunadj": "91.24",
    }], run_id="4f1d3021-8700-42b5-9866-ad7f6a4af014") == 1

    statement, payload = conn.statements[0]
    assert "sentinel_defensive_bars" in statement
    assert "'SENTINEL:BIL'" in statement and "'BIL'" in statement
    assert payload == [(
        "2026-08-20", 91.20, 91.25, 91.30, 91.24,
        "4f1d3021-8700-42b5-9866-ad7f6a4af014")]


@pytest.mark.parametrize(
    ("field", "value"),
    [("open", None), ("close", 0), ("closeadj", float("nan")),
     ("closeunadj", float("inf"))],
)
def test_defensive_writer_refuses_missing_nonpositive_or_nonfinite_source_field(
        field, value):
    row = {
        "ticker": "BIL", "date": "2026-08-20", "open": 91.20,
        "close": 91.25, "closeadj": 91.30, "closeunadj": 91.24,
    }
    row[field] = value
    with pytest.raises(
            ValueError, match="open/close/closeadj/closeunadj"):
        feed_store.write_defensive_bars(
            _Connection(), [row])


def test_defensive_runtime_schema_names_every_scalar_source_field():
    columns = runtime_schema._COLUMNS["sentinel_defensive_bars"]  # noqa: SLF001
    assert set(columns) >= {
        "open_signal", "close_signal", "close_adjusted", "close_unadjusted"}
    witnesses = runtime_schema._CONSTRAINT_WITNESSES[  # noqa: SLF001
        "sentinel_defensive_bars"]
    for field in (
            "open_signal", "close_signal", "close_adjusted",
            "close_unadjusted"):
        assert any(field in tokens and ">" in tokens
                   for kind, tokens in witnesses if kind == "c")


def test_published_defensive_reader_exposes_every_scalar_identity_input():
    conn = _Connection([(
        date(2026, 8, 20), "SENTINEL:BIL", "BIL",
        91.20, 91.25, 91.30, 91.24,
    )])

    assert feed_store.published_defensive_bars(
        conn, "2026-08-20", "2026-08-20") == [(
            "2026-08-20", "SENTINEL:BIL", "BIL",
            91.20, 91.25, 91.30, 91.24)]
    statement, _params = conn.statements[0]
    assert all(field in statement for field in (
        "open_signal", "close_signal", "close_adjusted", "close_unadjusted"))


@pytest.mark.parametrize(("field_index", "restated"), [
    (3, 91.19),  # source open
    (4, 91.26),  # source close
    (5, 91.31),  # total-return closeadj
    (6, 91.23),  # broker-mark closeunadj
])
def test_publication_identity_changes_for_every_retained_bil_field(
        monkeypatch, field_index, restated):
    baseline = (
        "2026-08-20", "SENTINEL:BIL", "BIL",
        91.20, 91.25, 91.30, 91.24,
    )
    rows = [baseline]
    monkeypatch.setattr(
        feed_store, "published_defensive_bars",
        lambda *_args, **_kwargs: list(rows))
    first = identity._defensive_bars_identity(  # noqa: SLF001
        object(), "2026-08-20", "2026-08-20")
    changed = list(baseline)
    changed[field_index] = restated
    rows[:] = [tuple(changed)]

    assert identity._defensive_bars_identity(  # noqa: SLF001
        object(), "2026-08-20", "2026-08-20") != first


def test_sfp_stability_identity_includes_the_raw_bil_mark():
    common = {"ticker": "BIL", "date": "2026-08-20",
              "open": 91.20, "close": 91.25, "closeadj": 91.30}
    first = coherence.observe_sfp([{**common, "closeunadj": 91.24}])
    restated = coherence.observe_sfp([{**common, "closeunadj": 91.23}])

    assert first.digest != restated.digest


@pytest.mark.parametrize(("field", "restated"), [
    ("open", 91.19), ("closeadj", 91.31),
])
def test_sfp_stability_identity_includes_scalar_return_fields(field, restated):
    row = {"ticker": "BIL", "date": "2026-08-20", "open": 91.20,
           "close": 91.25, "closeadj": 91.30, "closeunadj": 91.24}
    first = coherence.observe_sfp([row])
    changed = coherence.observe_sfp([{**row, field: restated}])

    assert first.digest != changed.digest


def test_paper_planning_resolves_fixed_bil_mark_and_sizes_the_sleeve(
        monkeypatch):
    conn = _Connection(
        [("SEC-A", "AAA", Decimal("100"))],
        [("SENTINEL:BIL", Decimal("90"))])
    monkeypatch.setattr(
        paper, "shadow_target",
        lambda _state: SimpleNamespace(
            shares={"SEC-A": Decimal("100")},
            tickers={"SEC-A": "AAA"}))

    marks, tickers = paper._load_marks_and_tickers(  # noqa: SLF001
        conn, object(), "2026-08-20")
    sized = project(
        shadow_weights={"SEC-A": Decimal("1")},
        exposure=Decimal("0.55"), nav=Decimal("10000"),
        marks=marks, defensive_security="SENTINEL:BIL",
        defensive_weight=Decimal("0.45"), lot=Decimal("1"))

    assert marks == {
        "SEC-A": Decimal("100"), "SENTINEL:BIL": Decimal("90")}
    assert tickers == {"SEC-A": "AAA", "SENTINEL:BIL": "BIL"}
    assert sized.quantities == {"SEC-A": Decimal("55")}
    assert sized.defensive_quantity == Decimal("50")
    assert sized.cash_residual == Decimal("0")
    assert "sentinel_bars" in conn.statements[0][0]
    assert "sentinel_defensive_bars" in conn.statements[1][0]


def test_trial_marks_synthetic_identity_from_provider_bil_relation():
    conn = _Connection([
        ("SENTINEL:BIL", "BIL", Decimal("91.25")),
    ])

    marks, value = trial._marks(  # noqa: SLF001
        conn, date(2026, 8, 20), {"SENTINEL:BIL": "3"})

    assert marks == {"SENTINEL:BIL": {"ticker": "BIL", "close": "91.25"}}
    assert value == Decimal("273.75")
    assert len(conn.statements) == 1
    assert "sentinel_defensive_bars" in conn.statements[0][0]


def test_corporate_action_mapping_resolves_bil_to_the_fixed_identity():
    conn = _Connection(
        [(date(2026, 8, 20), None, "action-2", "spinoff", "BIL", "NEW")],
        [],
        [("SENTINEL:BIL", date(2026, 8, 20), "BIL",
          Decimal("91"), Decimal("91"), date(2026, 8, 19),
          Decimal("91"), Decimal("91"), "legacy", 0, "legacy", 0)],
        [])

    lookup = reconcile.corpus_action_lookup(
        conn, start=date(2026, 8, 19), end=date(2026, 8, 20))

    events = lookup.material_events_for(security_ids=("SENTINEL:BIL",))
    assert len(events) == 1
    assert events[0].security_id == "SENTINEL:BIL"
    assert events[0].source_row_id == "action-2"
    assert any("sentinel_defensive_bars" in statement
               for statement, _params in conn.statements)


def test_execution_uses_sharadar_direct_reverse_split_multiplier_without_inversion(
        monkeypatch):
    from sentinel.feed import calendar

    monkeypatch.setattr(
        calendar, "action_date_window", lambda *_: ("2026-08-20", "2026-08-20"))
    monkeypatch.setattr(calendar, "session_on_or_after", lambda *_: "2026-08-20")
    canonical = Decimal(1) / Decimal(30)
    conn = _Connection(
        [(date(2026, 8, 20), canonical, "action-split", "split", "AAA", None)],
        [], [],
        [(1, "SPLIT_AUTHORITATIVE_APPLIED", "AAA", date(2026, 8, 20),
          f"stated={canonical} applied={canonical}", None, None, 0)],
        [("SEC-A", canonical, "legacy", 0)],
    )

    lookup = reconcile.corpus_action_lookup(
        conn, start=date(2026, 8, 19), end=date(2026, 8, 20))

    assert lookup("SEC-A") == canonical
    assert lookup("SEC-A") != Decimal(30), "Sharadar split is never inverted"
    assert "sentinel_bar_split_repairs" in conn.statements[1][0]


def test_execution_refuses_accepted_disposition_that_conflicts_with_raw_terms(
        monkeypatch):
    from sentinel.feed import calendar

    monkeypatch.setattr(
        calendar, "action_date_window", lambda *_: ("2026-08-20", "2026-08-20"))
    monkeypatch.setattr(calendar, "session_on_or_after", lambda *_: "2026-08-20")
    conn = _Connection(
        [(date(2026, 8, 20), Decimal(3), "action-split", "split", "AAA", None)],
        [], [],
        [(1, "SPLIT_AUTHORITATIVE_APPLIED", "AAA", date(2026, 8, 20),
          "stated=2 applied=2", None, None, 0)],
        [("SEC-A", Decimal(2), "legacy", 0)],
    )

    lookup = reconcile.corpus_action_lookup(
        conn, start=date(2026, 8, 19), end=date(2026, 8, 20))

    assert lookup("SEC-A") == Decimal(1)
    material = lookup.material_events_for(security_ids={"SEC-A"})
    assert len(material) == 1
    assert "conflicts with ACTIONS terms" in material[0].reason


def test_disposition_requires_one_exact_applied_evidence_token(monkeypatch):
    from sentinel.feed import calendar

    monkeypatch.setattr(
        calendar, "action_date_window", lambda *_: ("2026-08-20", "2026-08-20"))
    monkeypatch.setattr(calendar, "session_on_or_after", lambda *_: "2026-08-20")
    conn = _Connection(
        [(date(2026, 8, 20), Decimal(2), "action-split", "split", "AAA", None)],
        [], [],
        [(1, "SPLIT_AUTHORITATIVE_APPLIED", "AAA", date(2026, 8, 20),
          "stated=2 not_applied=2", None, None, 0)],
        [("SEC-A", Decimal(2), "legacy", 0)],
    )

    lookup = reconcile.corpus_action_lookup(
        conn, start=date(2026, 8, 19), end=date(2026, 8, 20))

    assert lookup("SEC-A") == Decimal(1)
    material, = lookup.material_events_for(security_ids={"SEC-A"})
    assert "accepted published split disposition conflicts" in material.reason


def test_ticker_level_disposition_cannot_fan_out_to_two_security_ids():
    session = date(2026, 8, 20)
    conn = _Connection(
        [],
        [
            ("SEC-A", session, "AAA", Decimal(2), "run-a", 7),
            ("SEC-B", session, "AAA", Decimal(2), "run-b", 7),
        ],
        [],
        [(1, "SPLIT_CORROBORATED_DERIVED", "AAA", session,
          "stated=2 derived=2 applied=2", None, "run-a", 7)],
    )

    lookup = reconcile.corpus_action_lookup(
        conn, start=date(2026, 8, 19), end=session)

    assert lookup("SEC-A") == lookup("SEC-B") == Decimal(1)
    for security_id in ("SEC-A", "SEC-B"):
        material = lookup.material_events_for(security_ids={security_id})
        assert len(material) == 1
        assert "ambiguous ticker/session security mapping" in material[0].reason


def test_execution_corroborates_bil_direct_reverse_multiplier_from_price_domains(
        monkeypatch):
    from sentinel.feed import calendar

    monkeypatch.setattr(
        calendar, "action_date_window", lambda *_: ("2026-08-20", "2026-08-20"))
    monkeypatch.setattr(calendar, "session_on_or_after", lambda *_: "2026-08-20")
    monkeypatch.setattr(
        calendar, "previous_sessions",
        lambda *_: ["2026-08-19", "2026-08-20"])
    canonical = Decimal(1) / Decimal(3)
    conn = _Connection(
        [(date(2026, 8, 20), canonical, "action-bil-split", "split", "BIL", None)],
        [],
        [("SENTINEL:BIL", date(2026, 8, 20), "BIL",
          Decimal(100), Decimal(300), date(2026, 8, 19),
          Decimal(100), Decimal(100), "legacy", 0, "legacy", 0)],
        [],
    )

    lookup = reconcile.corpus_action_lookup(
        conn, start=date(2026, 8, 19), end=date(2026, 8, 20))

    assert lookup("SENTINEL:BIL") == pytest.approx(canonical)
    assert lookup.material_events_for(
        security_ids={"SENTINEL:BIL"}) == ()


@pytest.mark.parametrize(("stated", "prior_session", "prior_close", "prior_raw"), [
    (Decimal(1) / Decimal(3), None, None, None),
    (Decimal(3), date(2026, 8, 19), Decimal(100), Decimal(100)),
])
def test_execution_blocks_bil_when_required_split_evidence_is_absent_or_conflicts(
        monkeypatch, stated, prior_session, prior_close, prior_raw):
    from sentinel.feed import calendar

    monkeypatch.setattr(
        calendar, "action_date_window", lambda *_: ("2026-08-20", "2026-08-20"))
    monkeypatch.setattr(calendar, "session_on_or_after", lambda *_: "2026-08-20")
    monkeypatch.setattr(
        calendar, "previous_sessions",
        lambda *_: ["2026-08-19", "2026-08-20"])
    conn = _Connection(
        [(date(2026, 8, 20), stated, "action-bil-split", "split", "BIL", None)],
        [],
        [("SENTINEL:BIL", date(2026, 8, 20), "BIL",
          Decimal(100), Decimal(300), prior_session, prior_close, prior_raw,
          "legacy", 0, "legacy", 0)],
        [],
    )

    lookup = reconcile.corpus_action_lookup(
        conn, start=date(2026, 8, 19), end=date(2026, 8, 20))

    assert lookup("SENTINEL:BIL") == Decimal(1)
    material = lookup.material_events_for(security_ids={"SENTINEL:BIL"})
    assert len(material) == 1
    assert "immediately consecutive" in material[0].reason


def test_fresh_bil_target_is_fenced_by_ticker_only_unresolved_action(
        monkeypatch):
    from sentinel.execution.plan import ExecutionPlan

    observed_symbols = []
    event = reconcile.CorporateActionEvent(
        security_id=None, ticker="BIL", session=date(2026, 8, 20),
        action="split", value=30, contraticker=None,
        source_row_id="action-unmapped", reason="published bar absent")

    class _Lookup:
        def __call__(self, _security_id):
            return Decimal(1)

        def material_events_for(self, *, security_ids, symbols):
            observed_symbols.append(set(symbols))
            return (event,) if "BIL" in symbols else ()

    monkeypatch.setattr(
        paper, "shadow_target",
        lambda _state: SimpleNamespace(
            shares={}, tickers={}, pending_open_shares={}, held_shares={},
            pending_close_shares={}))
    monkeypatch.setattr(paper.journal, "load_commands", lambda *_: [])
    monkeypatch.setattr(
        paper.reconciliation, "expected_book_from_commands", lambda *_args, **_kw: {})
    plan = ExecutionPlan(
        plan_id="bil-action-fence", decision_session=date(2026, 8, 19),
        effective_session=date(2026, 8, 20), target_exposure=Decimal(0),
        target_basket={"SENTINEL:BIL": Decimal(12)})
    binding = SimpleNamespace(identity=object())
    broker = SimpleNamespace(capabilities=SimpleNamespace(
        minimum_quantity_increment=Decimal(1)))

    with pytest.raises(paper.PaperActivationRefused, match="corporate action"):
        paper._target_projection_or_refuse(  # noqa: SLF001
            object(), state=SimpleNamespace(state_hash=plan.shadow_snapshot_hash),
            plan=plan, binding=binding,
            broker=broker, through=date(2026, 8, 20),
            actions=_Lookup(), target_actions=_Lookup())

    assert observed_symbols and all("BIL" in symbols for symbols in observed_symbols)


def test_missing_bil_mark_is_explicitly_unpriced_not_a_cash_decision():
    sized = project(
        shadow_weights={"SEC-A": Decimal("1")},
        exposure=Decimal("0.55"), nav=Decimal("10000"),
        marks={"SEC-A": Decimal("100")},
        defensive_security="SENTINEL:BIL",
        defensive_weight=Decimal("0.45"), lot=Decimal("1"))

    assert sized.quantities == {"SEC-A": Decimal("55")}
    assert sized.defensive_quantity == 0
    assert sized.cash_residual == Decimal("4500")
    assert sized.unpriced == ("SENTINEL:BIL",)


def _previous_bil_book(*, position="12", commands=(), reason_codes=()):
    return {
        "session": "2026-08-19",
        "verdict": "NOT_VERIFIED" if reason_codes else "VERIFIED",
        "reason_codes": list(reason_codes),
        "reconciliation": {"positions": {"SENTINEL:BIL": position}},
        "commands": list(commands),
    }


def test_bil_distribution_is_evidence_only_on_raw_paper_shares(monkeypatch):
    from sentinel.feed import calendar

    monkeypatch.setattr(
        calendar, "action_date_window", lambda *_: ("2026-08-19", "2026-08-19"))
    monkeypatch.setattr(calendar, "session_on_or_after", lambda value: str(value))
    conn = _Connection(
        [(date(2026, 8, 19), "dividend", Decimal("0.25"), "action-1")],
        [(Decimal("91"), Decimal("91"))],
    )

    entitlement = trial._expected_defensive_dividends(  # noqa: SLF001
        conn, date(2026, 8, 19), {"SENTINEL:BIL": "12"}, [])

    assert entitlement == [{
        "security_id": "SENTINEL:BIL", "ticker": "BIL",
        "accrued_session": "2026-08-19", "shares": "12",
        "per_share": "0.25", "amount": "3.00",
        "reported_per_share": "0.25", "source_row_ids": ["action-1"],
        "source": "SHARADAR_ACTIONS", "settlement_lag_sessions": None,
    }]


def test_held_bil_distribution_without_price_basis_refuses(monkeypatch):
    from sentinel.feed import calendar

    monkeypatch.setattr(
        calendar, "action_date_window", lambda *_: ("2026-08-19", "2026-08-19"))
    monkeypatch.setattr(calendar, "session_on_or_after", lambda value: str(value))
    conn = _Connection(
        [(date(2026, 8, 19), "specialdividend", Decimal("0.25"), "action-1")],
        [],
    )

    with pytest.raises(trial.TrialEvidenceRefused, match="price-domain evidence"):
        trial._expected_defensive_dividends(  # noqa: SLF001
            conn, date(2026, 8, 19), {"SENTINEL:BIL": "12"}, [])


def test_ex_date_bil_buy_does_not_manufacture_distribution(monkeypatch):
    from sentinel.feed import calendar

    monkeypatch.setattr(
        calendar, "action_date_window", lambda *_: ("2026-08-19", "2026-08-19"))
    monkeypatch.setattr(calendar, "session_on_or_after", lambda value: str(value))
    conn = _Connection([
        (date(2026, 8, 19), "dividend", Decimal("0.25"), "action-1")])
    commands = [{
        "client_key": "buy-bil", "security_id": "SENTINEL:BIL",
        "side": "BUY", "filled_quantity": "12",
    }]

    assert trial._expected_defensive_dividends(  # noqa: SLF001
        conn, date(2026, 8, 19), {"SENTINEL:BIL": "12"}, commands) == []
    assert len(conn.statements) == 1  # no price lookup for zero entitlement


def test_effective_session_equity_dividend_uses_pre_open_paper_shares(
        monkeypatch):
    from sentinel.feed import calendar

    monkeypatch.setattr(
        calendar, "action_date_window", lambda *_: ("2026-08-20", "2026-08-20"))
    monkeypatch.setattr(calendar, "session_on_or_after", lambda value: str(value))
    conn = _Connection(
        [("SEC-A", "AAA", Decimal("25"), Decimal("100"),
          Decimal("0.25"))],
        [(date(2026, 8, 20), "dividend", "AAA", Decimal("0.0625"),
          "action-equity")],
    )
    commands = [{
        "client_key": "sell-aaa", "security_id": "SEC-A",
        "side": "SELL", "filled_quantity": "12",
    }]

    entitlement = trial._expected_effective_equity_dividends(  # noqa: SLF001
        conn, date(2026, 8, 20), {"SEC-A": "0"}, commands)

    assert entitlement == [{
        "security_id": "SEC-A", "ticker": "AAA",
        "accrued_session": "2026-08-20", "shares": "12",
        "per_share": "0.25", "amount": "3.00",
        "reported_per_share": "0.0625",
        "source_row_ids": ["action-equity"],
        "source": "PUBLISHED_NORMALISED_BAR_AND_SHARADAR_ACTIONS",
        "settlement_lag_sessions": None,
    }]
    assert "sentinel_bars" in conn.statements[0][0]
    assert "sentinel_active_actions" in conn.statements[1][0]


def test_ex_date_equity_buy_does_not_manufacture_distribution():
    conn = _Connection()
    commands = [{
        "client_key": "buy-aaa", "security_id": "SEC-A",
        "side": "BUY", "filled_quantity": "12",
    }]

    assert trial._expected_effective_equity_dividends(  # noqa: SLF001
        conn, date(2026, 8, 20), {"SEC-A": "12"}, commands) == []
    assert conn.statements == []


def test_positive_equity_dividend_without_action_identity_refuses(monkeypatch):
    from sentinel.feed import calendar

    monkeypatch.setattr(
        calendar, "action_date_window", lambda *_: ("2026-08-20", "2026-08-20"))
    monkeypatch.setattr(calendar, "session_on_or_after", lambda value: str(value))
    conn = _Connection(
        [("SEC-A", "AAA", Decimal("25"), Decimal("100"),
          Decimal("0.25"))],
        [],
    )

    with pytest.raises(trial.TrialEvidenceRefused, match="lacks bound action"):
        trial._expected_effective_equity_dividends(  # noqa: SLF001
            conn, date(2026, 8, 20), {"SEC-A": "12"}, [])


def test_zero_equity_dividend_with_unusable_action_refuses(monkeypatch):
    from sentinel.feed import calendar

    monkeypatch.setattr(
        calendar, "action_date_window", lambda *_: ("2026-08-20", "2026-08-20"))
    monkeypatch.setattr(calendar, "session_on_or_after", lambda value: str(value))
    conn = _Connection(
        [("SEC-A", "AAA", Decimal("25"), Decimal("100"), Decimal("0"))],
        [(date(2026, 8, 20), "dividend", "AAA", None, "action-equity")],
    )

    with pytest.raises(trial.TrialEvidenceRefused, match="not a decimal"):
        trial._expected_effective_equity_dividends(  # noqa: SLF001
            conn, date(2026, 8, 20), {"SEC-A": "12"}, [])


def test_mixed_valid_and_unusable_equity_dividends_refuse(monkeypatch):
    from sentinel.feed import calendar

    monkeypatch.setattr(
        calendar, "action_date_window", lambda *_: ("2026-08-20", "2026-08-20"))
    monkeypatch.setattr(calendar, "session_on_or_after", lambda value: str(value))
    conn = _Connection(
        [("SEC-A", "AAA", Decimal("25"), Decimal("100"),
          Decimal("0.25"))],
        [(date(2026, 8, 20), "dividend", "AAA", Decimal("0.0625"), "a-1"),
         (date(2026, 8, 20), "specialdividend", "AAA", Decimal("0"), "a-2")],
    )

    with pytest.raises(trial.TrialEvidenceRefused, match="usable decimal"):
        trial._expected_effective_equity_dividends(  # noqa: SLF001
            conn, date(2026, 8, 20), {"SEC-A": "12"}, [])


def test_equity_dividend_action_aggregate_must_bind_to_published_bar(monkeypatch):
    from sentinel.feed import calendar

    monkeypatch.setattr(
        calendar, "action_date_window", lambda *_: ("2026-08-20", "2026-08-20"))
    monkeypatch.setattr(calendar, "session_on_or_after", lambda value: str(value))
    conn = _Connection(
        [("SEC-A", "AAA", Decimal("25"), Decimal("100"),
          Decimal("0.25"))],
        [(date(2026, 8, 20), "dividend", "AAA", Decimal("0.10"), "a-1")],
    )

    with pytest.raises(trial.TrialEvidenceRefused, match="aggregate does not match"):
        trial._expected_effective_equity_dividends(  # noqa: SLF001
            conn, date(2026, 8, 20), {"SEC-A": "12"}, [])


def test_zero_equity_bar_without_action_is_proven_non_event(monkeypatch):
    from sentinel.feed import calendar

    monkeypatch.setattr(
        calendar, "action_date_window", lambda *_: ("2026-08-20", "2026-08-20"))
    monkeypatch.setattr(calendar, "session_on_or_after", lambda value: str(value))
    conn = _Connection(
        [("SEC-A", "AAA", Decimal("25"), Decimal("100"), Decimal("0"))],
        [],
    )

    assert trial._expected_effective_equity_dividends(  # noqa: SLF001
        conn, date(2026, 8, 20), {"SEC-A": "12"}, []) == []
    assert len(conn.statements) == 2
