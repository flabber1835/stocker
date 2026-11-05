"""Hosted packet and own-position cash qualification; no financial sessions."""
from copy import deepcopy
import math

from full_system_core import hosted
from full_system_benchmark import need, save
from system_campaign_facts import digest


def qualify(out, cp, facts, loaded, old_objects, request):
    hosted()
    from research.pooled_vacancy_funding import runtime
    from stock_strategy_shared.wealth_core.state import PortfolioState
    from stock_strategy_shared.wealth_core.ledger import Ledger
    from stock_strategy_shared.wealth_core.terminal import terminal_terms_from_dict, apply_terminal
    facts.qualify(loaded, old_objects, out / 'q4-cash-packet-qualification.json',
                  packet_source_sha256=request['qualified_packet_source_sha256'])
    restored = runtime.restore(cp['run'], policy=cp['base']['policy'], input_sha256=cp['run']['input_sha256'])
    need(runtime.checkpoint(restored) == cp['run'], 'Q4_ACTUAL_OWN_PARENT_CANONICAL_ROUNDTRIP')
    original = deepcopy(restored.state.wealth_core)
    cfg = runtime.config(cp['base']['policy'])
    checks = []
    # Each event uses a separate copy of the actual parent. This is not a
    # forecast of holdings on that future day or a substitute for replay.
    for item in facts.catalog['terms']:
        core = PortfolioState.from_dict(deepcopy(original));ledger = Ledger()
        sid, day = item['security_id'], item['added']['session']
        quantity = sum(v.current_shares for v in core.episodes.values() if v.security_id == sid)
        before = (core.to_dict(), ledger.to_dict());cash = core.cash
        terms = terminal_terms_from_dict(item['added'])
        result = apply_terminal(core, terms, ledger=ledger, session=day, cfg=cfg)
        if quantity:
            need(result['applied'] is True
                 and math.isclose(core.cash - cash, float(quantity) * terms.cash_per_share,
                                  rel_tol=1e-12, abs_tol=1e-8)
                 and not any(v.security_id == sid for v in core.episodes.values())
                 and sid not in core.unresolved_terminals and sid not in core.terminal_pending_sessions,
                 'Q4_CANONICAL_ACTUAL_PARENT_ENTITLEMENT_PAID_AND_REMOVED')
        else:
            need(result['applied'] is False and result['reason'] == 'NOT_HELD'
                 and (core.to_dict(), ledger.to_dict()) == before,
                 'Q4_CANONICAL_UNHELD_EVENT_DOES_NOT_CREATE_ENTITLEMENT')
        once = (core.to_dict(), ledger.to_dict())
        repeat = apply_terminal(core, terms, ledger=ledger, session=day, cfg=cfg)
        need(repeat['applied'] is False and repeat['reason'] == 'NOT_HELD'
             and (core.to_dict(), ledger.to_dict()) == once, 'Q4_CANONICAL_CASH_EXACTLY_ONCE')
        checks.append(dict(ticker=item['ticker'], security_id=sid, session=day,
            actual_parent_shares=float(quantity), qualification_cash=float(quantity)*terms.cash_per_share,
            not_a_future_holdings_claim=True))
    need(restored.state.wealth_core == original and runtime.checkpoint(restored) == cp['run'],
         'Q4_QUALIFICATION_DID_NOT_MUTATE_OR_ADVANCE_PARENT')
    save(out / 'q4-cash-canonical-qualification.json', dict(status='ALL_31_CASH_EVENTS_CANONICALLY_QUALIFIED',
        parent_checkpoint_sha256=cp['sha256'], original_portfolio_sha256=digest(original), checks=checks,
        actual_parent_roundtrip=True, actual_packets_and_prior_inputs_qualified=True,
        source_state_unchanged=True, qualification_copy_only=True,
        actual_resumed_session_proof_still_required=True, financial_sessions_advanced=0,
        production_contacted=False))
