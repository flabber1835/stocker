"""Hosted actual packet and own-position conversion qualification; no replay."""
from copy import deepcopy
from fractions import Fraction

from full_system_core import hosted
from full_system_benchmark import need, save
from system_campaign_facts import digest
from system_campaign_wwe_facts import SID, DELIVERED, DAY


def qualify(out, cp, facts, loaded, old_objects, request):
    hosted()
    from research.pooled_vacancy_funding import runtime
    from stock_strategy_shared.wealth_core.state import PortfolioState
    from stock_strategy_shared.wealth_core.ledger import Ledger
    from stock_strategy_shared.wealth_core.terminal import terminal_terms_from_dict, apply_terminal
    facts.qualify(loaded, old_objects, out / 'wwe-packet-qualification.json',
                  packet_source_sha256=request['qualified_packet_source_sha256'])
    restored = runtime.restore(cp['run'], policy=cp['base']['policy'], input_sha256=cp['run']['input_sha256'])
    need(runtime.checkpoint(restored) == cp['run'], 'WWE_OWN_ACTUAL_CANONICAL_PARENT_ROUNDTRIP')
    original = deepcopy(restored.state.wealth_core)
    core = PortfolioState.from_dict(deepcopy(original))
    ledger = Ledger()
    quantity = sum(v.current_shares for v in core.episodes.values() if v.security_id == SID)
    need(quantity == 16 and not any(v.security_id == DELIVERED for v in core.episodes.values()),
         'WWE_EXACT_OWN_SIXTEEN_SHARE_QUALIFICATION_ENTITLEMENT')
    raw = facts.rows['2023-09-11', SID]
    delivered = facts.rows[DAY, DELIVERED]
    source_scale = float(Fraction(raw['signal_close']) / Fraction(raw['raw_close']))
    target_scale = float(Fraction(delivered['signal_close']) / Fraction(delivered['raw_close']))
    terms = terminal_terms_from_dict(facts.added[0])
    cfg = runtime.config(cp['base']['policy'])
    cash = core.cash
    result = apply_terminal(core, terms, ledger=ledger, session=DAY, cfg=cfg,
        source_signal_to_raw_scale=source_scale, delivered_signal_to_raw_scale=target_scale,
        delivered_raw_open=float(delivered['raw_open']))
    target = [v for v in core.episodes.values() if v.security_id == DELIVERED]
    need(result['applied'] is True and len(target) == 1 and target[0].current_shares == 16
         and not any(v.security_id == SID for v in core.episodes.values()) and core.cash == cash
         and SID not in core.unresolved_terminals and SID not in core.terminal_pending_sessions,
         'WWE_CANONICAL_SIXTEEN_FOR_SIXTEEN_WITHOUT_CASH_OR_PENDING_CLAIM')
    before_second = (core.to_dict(), ledger.to_dict())
    repeat = apply_terminal(core, terms, ledger=ledger, session=DAY, cfg=cfg,
        source_signal_to_raw_scale=source_scale, delivered_signal_to_raw_scale=target_scale,
        delivered_raw_open=float(delivered['raw_open']))
    need(repeat['applied'] is False and repeat['reason'] == 'NOT_HELD'
         and (core.to_dict(), ledger.to_dict()) == before_second, 'WWE_CANONICAL_CONVERSION_EXACTLY_ONCE')
    refused = PortfolioState.from_dict(deepcopy(original))
    bad = apply_terminal(refused, terms, ledger=Ledger(), session=DAY, cfg=cfg,
        delivered_signal_to_raw_scale=target_scale, delivered_raw_open=float(delivered['raw_open']))
    need(bad.get('blocked') is True and bad['reason'] == 'MISSING_CONVERSION_SIGNAL_BASIS'
         and refused.cash == cash and sum(v.current_shares for v in refused.episodes.values()
                                        if v.security_id == SID) == 16,
         'WWE_MISSING_SOURCE_SIGNAL_BASIS_REFUSED_WITHOUT_CONVERSION')
    need(restored.state.wealth_core == original and runtime.checkpoint(restored) == cp['run'],
         'WWE_QUALIFICATION_DID_NOT_MUTATE_OR_ADVANCE_PARENT')
    save(out / 'wwe-canonical-qualification.json', dict(
        status='ACTUAL_OWN_WWE_TO_TKO_CANONICAL_CONVERSION_QUALIFIED',
        parent_checkpoint_sha256=cp['sha256'], original_portfolio_sha256=digest(original),
        original_shares=16, delivered_shares=16, cash_delta=0, fractional_cash_paid=0,
        actual_parent_roundtrip=True, actual_packets_and_prior_inputs_qualified=True,
        actual_once_only_and_missing_signal_basis_refusals=True, source_state_unchanged=True,
        original_terminal_shares_removed=True, correct_frozen_delivered_security=True,
        qualification_copy_only=True, actual_resumed_session_proof_still_required=True,
        financial_sessions_advanced=0, production_contacted=False))
