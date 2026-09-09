import math
from types import SimpleNamespace

import pytest

from tools.median5_equivalence import Comparison, prepare_output
from tools import median5_equivalence as gate_module


def test_split_roundoff_tolerance_cannot_hide_integer_or_material_quantity_changes(tmp_path):
    gate = Comparison.__new__(Comparison)
    gate.session, gate.output, gate.count = "2006-12-29", tmp_path, 250
    gate.fractional_share_roundoffs = 0
    gate.shares("split", 216058.7007, 216058.70070000002)
    assert gate.fractional_share_roundoffs == 1
    for actual, expected in ((216058.7007, 216059.7007),
                             (216058., math.nextafter(216058., math.inf)),
                             (216058., 216059.)):
        with pytest.raises(AssertionError):
            gate.shares("must_fail", actual, expected)


def test_previous_pass_cannot_survive_into_a_new_gate_run(tmp_path):
    old = tmp_path/"RESULT.json"
    old.write_text('{"status":"PASS_FULL_PIT_EQUIVALENCE"}')
    with pytest.raises(ValueError, match="output must be empty"):
        prepare_output(tmp_path)
    assert old.read_text() == '{"status":"PASS_FULL_PIT_EQUIVALENCE"}'


def test_opening_audit_preserves_strict_production_result_and_prefill_boundary(monkeypatch):
    prior = SimpleNamespace(last_known={"predecessor": 99.},
        feed={"series": {"delivered": {"raw_closes": [5., None, 7.]}}})
    book = SimpleNamespace(cash=10., episodes={0: SimpleNamespace(
        security_id="delivered", current_shares=3.)})
    ledger = SimpleNamespace(receivable_total=lambda: 2.)
    expected = gate_module.adapter._resolved_open_equity(book, [], ledger)
    assert expected == (None, ("delivered",))
    def transition(before, published, **kwargs):
        assert gate_module.adapter._resolved_open_equity(book, [], ledger) == expected
        book.cash += 100.  # Simulate a later fill; the audit already captured the open.
        return book
    monkeypatch.setattr(gate_module, "advance_session", transition)
    after, audit = gate_module.advance_with_open_audit(prior, None,
        controller_config=None, strategy_identity=None)
    assert after is book
    assert audit == (33., ("delivered",))
    assert gate_module.adapter._resolved_open_equity(book, [], ledger) == expected


def test_opening_audit_refuses_missing_prior_price():
    prior = SimpleNamespace(last_known={"predecessor": 99.}, feed={"series": {}})
    book = SimpleNamespace(cash=10., episodes={0: SimpleNamespace(
        security_id="delivered", current_shares=3.)})
    ledger = SimpleNamespace(receivable_total=lambda: 2.)
    with pytest.raises(ValueError, match="lacks current and prior raw price: delivered"):
        gate_module.opening_estimate(book, [], ledger, prior)


def test_opening_audit_refuses_duplicate_boundary(monkeypatch):
    prior = SimpleNamespace(last_known={}, feed={"series": {}})
    book = SimpleNamespace(cash=10., episodes={})
    ledger = SimpleNamespace(receivable_total=lambda: 0.)
    def transition(before, published, **kwargs):
        for _ in range(2):
            gate_module.adapter._resolved_open_equity(book, [], ledger)
        return book
    monkeypatch.setattr(gate_module, "advance_session", transition)
    with pytest.raises(AssertionError, match="exactly one canonical boundary"):
        gate_module.advance_with_open_audit(prior, None,
            controller_config=None, strategy_identity=None)
