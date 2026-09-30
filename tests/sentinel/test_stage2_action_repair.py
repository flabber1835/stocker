"""Falsifiers for the retained research action chronology correction."""
from copy import deepcopy

import pytest

from research.stage2_actions.repair import RAW_DISPOSITION, load_chronology, repair
from research.bounded_20y.run import terminals
from stock_strategy_shared.wealth_core.engine import WealthCoreConfig
from stock_strategy_shared.wealth_core.ledger import Ledger
from stock_strategy_shared.wealth_core.state import HoldingEpisode, PortfolioState, SlotState
from stock_strategy_shared.wealth_core.terminal import apply_terminal


def inputs():
    rules = load_chronology()
    raw = []
    supplements = []
    for r in rules:
        raw.append(dict(effective_session=r["original_event_session"],
                        security_id=r["security_id"], ticker=r["ticker"],
                        kind="CASH_MERGER", disposition=RAW_DISPOSITION,
                        cash_per_share=""))
        supplements.append(dict(id=r["source_supplement_id"],
                                effective_session=r["original_event_session"],
                                original_event_session=r["original_event_session"],
                                security_id=r["security_id"], ticker=r["ticker"],
                                kind="CASH_MERGER", cash_per_share=r["cash_per_share"],
                                sources=[r["source"]], reference="sourced cash merger",
                                delivered_security_id="", delivered_ticker="",
                                delivered_issuer_id="", exchange_ratio="",
                                cash_in_lieu_price_per_delivered_share=""))
    return raw, supplements, rules


def test_all_twelve_early_rows_removed_and_once_only_later_cash():
    raw, supplements, rules = inputs()
    schedule, corrected, audit = repair(raw, supplements, rules)
    assert audit["corrected_count"] == audit["suppressed_raw_count"] == 12
    assert len(corrected) == len(supplements)
    events = terminals(schedule)
    for rule in rules:
        sid = rule["security_id"]
        old, completion = rule["original_event_session"], rule["completion_session"]
        assert all(e.security_id != sid for e in events.get(old, ()))
        matching = [e for e in events[completion] if e.security_id == sid]
        assert len(matching) == 1
        book = PortfolioState.fresh(1000, n_slots=20)
        book.slots[0].occupied_by = sid
        book.episodes[0] = HoldingEpisode(
            security_id=sid, ticker=rule["ticker"], issuer_id="SID:" + sid,
            slot_id=0, signal_date="2008-01-01", entry_date="2008-01-02",
            entry_raw_open=20, entry_split_adjusted_price=20,
            initial_shares=3, current_shares=3,
            episode_peak_split_adjusted_close=20, market_sessions_held=30)
        ledger = Ledger()
        assert book.cash == 1000 and sid in book.held_security_ids()
        result = apply_terminal(book, matching[0], ledger=ledger,
                                session=completion, cfg=WealthCoreConfig())
        assert result["applied"] and sid not in book.held_security_ids()
        assert abs(book.cash - (1000 + 3 * float(rule["cash_per_share"]))) < 1e-8
        duplicate = apply_terminal(book, matching[0], ledger=ledger,
                                   session=completion, cfg=WealthCoreConfig())
        assert not duplicate["applied"] and len(ledger.events) == 1


def test_obsolete_raw_witness_or_source_drift_refuses():
    raw, supplements, rules = inputs()
    raw[0]["disposition"] = "SOURCE_CHANGED"
    with pytest.raises(ValueError, match="raw terminal differs"):
        repair(raw, supplements, rules)
    raw, supplements, rules = inputs()
    supplements[0]["cash_per_share"] = "0"
    with pytest.raises(ValueError, match="source supplement differs"):
        repair(raw, supplements, rules)
    raw, supplements, rules = inputs()
    raw.append(deepcopy(raw[0]))
    with pytest.raises(ValueError, match="expected one raw terminal"):
        repair(raw, supplements, rules)


def test_new_completion_collisions_refuse():
    raw, supplements, rules = inputs()
    first = rules[0]
    raw.append({**raw[0], "effective_session": first["completion_session"],
                "cash_per_share": first["cash_per_share"]})
    with pytest.raises(ValueError, match="expected one raw terminal"):
        repair(raw, supplements, rules)


def test_age_twenty_replacement_cannot_reuse_corrected_slot():
    slot = SlotState(slot_id=0)
    slot.start_cooldown()
    for _ in range(20):
        slot.age_cooldown()
    assert not slot.ready
    slot.age_cooldown()
    assert slot.ready
