"""Measurement and durable continuation contracts for the bounded January run."""
from decimal import Decimal
import json

import pytest

from research.bounded_20y.january import (
    START, load_supplements, progress, read_checkpoint, write_checkpoint)
from sentinel.controller.machine import Controller
from sentinel.core.session import SessionState
from sentinel.strategy import production_strategy


def test_january_formation_does_not_reset_book_or_enter_july_return():
    stats, status = progress({}, "2006-07-28", "90000", {})
    assert stats == {} and status["cagr"] is None
    stats, status = progress(stats, START, "80000", {START: Decimal(1)})
    assert stats["base"] == "80000"
    assert status["multiple"] == "1" and status["cagr"] is None
    stats, status = progress(stats, "2007-07-31", "100000",
        {START: Decimal(1), "2007-07-31": Decimal("1.1")})
    assert Decimal(status["multiple"]) == Decimal("1.25")
    assert status["cagr"] == pytest.approx(1.25**(365.2425/365)-1)
    assert status["reference_cagr"] == pytest.approx(1.1**(365.2425/365)-1)


def test_checkpoint_roundtrip_preserves_production_state_and_detects_corruption(tmp_path):
    config, identity = production_strategy()
    state = SessionState.fresh(starting_cash=100000, controller=Controller(config),
                               strategy_identity=identity)
    packet = {"binding": {"scenario": "january"}, "state": state.to_dict(),
              "state_sha256": state.state_hash, "pending_cash_example": "2800"}
    pointer = write_checkpoint(tmp_path, packet)
    restored, actual = read_checkpoint(tmp_path/"latest-checkpoint.json", packet["binding"])
    assert actual.to_dict() == state.to_dict()
    assert restored["pending_cash_example"] == "2800"
    with pytest.raises(ValueError, match="binding differs"):
        read_checkpoint(tmp_path/"latest-checkpoint.json", {"scenario": "other"})
    altered = {**packet, "state_sha256": "0"*64}
    pointer = write_checkpoint(tmp_path, altered)
    with pytest.raises(ValueError, match="state commitment differs"):
        read_checkpoint(tmp_path/"latest-checkpoint.json", packet["binding"])
    from pathlib import Path
    Path(pointer["path"]).write_bytes(b"corruption")
    with pytest.raises(ValueError, match="bytes changed"):
        read_checkpoint(tmp_path/"latest-checkpoint.json", packet["binding"])


def test_applied_action_evidence_is_immutable_and_future_evidence_cannot_be_used_early(tmp_path):
    path = tmp_path/"terms.json"
    row = {"id": "RSAS-confirmed", "sources": ["https://www.sec.gov/example"],
           "known_by": "2006-09-18", "effective_session": "2006-09-18",
           "original_event_session": "2006-09-15", "cash_per_share": "28"}
    path.write_text(json.dumps([row]))
    assert load_supplements(path, {}, "2006-09-15") == {row["id"]: row}
    assert load_supplements(path, {row["id"]: row}, "2006-09-18") == {row["id"]: row}
    with pytest.raises(ValueError, match="rewrite processed history"):
        load_supplements(path, {}, "2006-09-18")
    path.write_text(json.dumps([{**row, "cash_per_share": "29"}]))
    with pytest.raises(ValueError, match="applied supplemental evidence changed"):
        load_supplements(path, {row["id"]: row}, "2006-09-18")
    path.write_text(json.dumps([{**row, "known_by": "2006-09-19"}]))
    with pytest.raises(ValueError, match="causal evidence"):
        load_supplements(path, {}, "2006-09-15")
