"""Hosted disposable cases and explicit passive non-election scope qualification."""
import ast
from copy import deepcopy
import json
from pathlib import Path

from full_system_core import hosted
from full_system_benchmark import need, save
from system_campaign_facts import digest, sha

PASSIVE_FIELDS = {
    'PortfolioState': ['slots', 'episodes', 'security_cooldowns', 'cash', 'initialized',
        'session_index', 'median5', 'entry_sizing_profile', 'unresolved_terminals',
        'sessions_since_valid_mark', 'terminal_pending_sessions', 'terminal_pending_terms',
        'terminal_carry_audit', 'last_valid_mark_session'],
    'HoldingEpisode': ['security_id', 'ticker', 'issuer_id', 'slot_id', 'signal_date',
        'entry_date', 'entry_raw_open', 'entry_split_adjusted_price', 'initial_shares',
        'current_shares', 'episode_peak_split_adjusted_close', 'market_sessions_held',
        'source_lots', 'review_completed', 'exit_pending', 'exit_reason'],
    'TerminalTerms': ['session', 'security_id', 'kind', 'cash_per_share',
        'delivered_security_id', 'delivered_ticker', 'delivered_issuer_id', 'exchange_ratio',
        'cash_in_lieu_price_per_delivered_share', 'reference', 'entitlement_aggregation'],
}
PASSIVE_API = {'advance': ['run', 'published'],
               'restore': ['value', 'policy', 'input_sha256']}


def require_passive_shape(shape):
    need(shape == dict(fields=PASSIVE_FIELDS, api=PASSIVE_API),
         'WINTER2025_INFN_EXACT_PASSIVE_CANONICAL_SCHEMA_WITHOUT_ELECTION_OPERATION')


def qualify_default_scope(out, cp, facts, request):
    hosted()
    from dataclasses import fields
    from research.pooled_vacancy_funding import runtime
    from stock_strategy_shared.wealth_core.state import PortfolioState, HoldingEpisode
    from stock_strategy_shared.wealth_core.terminal import TerminalTerms
    from system_campaign_winter2025_cash_parent import SPEC, SPEC_SHA, scope
    spec = scope(json.loads((Path(__file__).parent / SPEC).read_bytes()))
    need(cp['sha256'] == spec['outer_sha256']
         and cp['run']['checkpoint_sha256'] == spec['inner_sha256']
         and cp['run']['state_sha256'] == spec['state_sha256']
         and cp['run']['input_sha256'] == spec['input_sha256']
         and request['predecessor_sha256'] == SPEC_SHA,
         'WINTER2025_INFN_ACTUAL_OWN40_PASSIVE_PARENT_BINDING')
    source = Path(runtime.__file__).read_bytes()
    api = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.FunctionDef) and node.name in PASSIVE_API:
            need(node.args.vararg is None and node.args.kwarg is None,
                 'WINTER2025_NO_UNDECLARED_CANONICAL_ELECTION_ARGUMENTS')
            api[node.name] = [v.arg for v in (*node.args.posonlyargs, *node.args.args,
                                             *node.args.kwonlyargs)]
    shape = dict(fields={cls.__name__: [f.name for f in fields(cls)]
                         for cls in (PortfolioState, HoldingEpisode, TerminalTerms)}, api=api)
    require_passive_shape(shape)
    restored = runtime.restore(cp['run'], policy=cp['base']['policy'],
                               input_sha256=cp['run']['input_sha256'])
    need(runtime.checkpoint(restored) == cp['run'],
         'WINTER2025_INFN_ACTUAL_CANONICAL_STATE_ROUNDTRIP_WITHOUT_FOREIGN_STATE')
    term, = [v for v in facts.catalog['terms'] if v['ticker'] == 'INFN']
    need(term['cash_scope'] == 'NO_AFFIRMATIVE_ELECTION'
         and term['primary_extraction']['passive_book_default_only'] is True
         and term['primary_extraction']['all_holders_mandatory_cash'] is False,
         'WINTER2025_INFN_CONTRACTUAL_DEFAULT_ONLY')
    changed = deepcopy(shape)
    changed['fields']['HoldingEpisode'].append('affirmative_merger_election')
    try:
        require_passive_shape(changed)
    except ValueError as error:
        need(str(error) == 'REFUSED_FULL_SYSTEM_WINTER2025_INFN_EXACT_PASSIVE_CANONICAL_SCHEMA_WITHOUT_ELECTION_OPERATION',
             'WINTER2025_INFN_SCOPE_FALSIFIER_EXACT_REASON')
    else:
        raise ValueError('REFUSED_WINTER2025_INFN_SCOPE_MUTATION_WAS_NOT_REJECTED')
    save(out / 'winter2025-passive-default-canonical-qualification.json', dict(
        status='INFN_CONTRACTUAL_DEFAULT_QUALIFIED_FOR_EXACT_PASSIVE_SIMULATION_ONLY',
        parent_checkpoint_sha256=cp['sha256'], input_sha256=cp['run']['input_sha256'],
        parent_policy=cp['base']['policy'], canonical_runtime_source_sha256=sha(source),
        actual_schema=shape, actual_parent_roundtrip=True,
        simulation_has_no_affirmative_election_operation=True,
        external_account_election_observed=False, all_holders_mandatory_cash=False,
        stock_or_mixed_election_proration_applied=False,
        actual_added_election_capability_falsifier_passed=True,
        qualification_copy_only=True, financial_sessions_advanced=0, production_contacted=False))


def require_positive(core, ledger, sid, cash):
    paid = [v for v in ledger.events
            if v.security_id == sid and v.event_type.value == 'CASH_MERGER']
    need(core.cash == 9000. + 10. * cash and not core.episodes and len(paid) == 1
         and paid[0].price == cash and paid[0].cash_delta == 10. * cash
         and paid[0].shares_delta == -10.,
         'WINTER2025_CANONICAL_POSITIVE_CASH_REMOVAL')


def qualify_held(out, cp, facts):
    hosted()
    from research.pooled_vacancy_funding import runtime
    from stock_strategy_shared.wealth_core import v5
    from stock_strategy_shared.wealth_core.state import PortfolioState, HoldingEpisode
    from stock_strategy_shared.wealth_core.ledger import Ledger
    from stock_strategy_shared.wealth_core.terminal import terminal_terms_from_dict, apply_terminal
    payload = json.loads((out / facts.catalog['commitment_group']['private_file']).read_bytes())
    witnesses = {w['security_id']: w for w in payload['source_witnesses']}
    need(len(witnesses) == 11
         and payload['recognition_quote_qualification']['actual_recognition_quotes'] == [],
         'WINTER2025_ELEVEN_ACTUAL_LAST_TRADES_AND_RECOGNITION_QUOTE_ABSENCE')
    restored = runtime.restore(cp['run'], policy=cp['base']['policy'],
                               input_sha256=cp['run']['input_sha256'])
    need(runtime.checkpoint(restored) == cp['run'], 'WINTER2025_ACTUAL_PARENT_ROUNDTRIP')
    cfg = runtime.config(cp['base']['policy'])
    checks = []
    for term in facts.catalog['terms']:
        sid = term['security_id']; day = term['added']['session']; cash = term['added']['cash_per_share']
        witness = witnesses[sid]
        need(witness['session'] == term['last_trading_session'], 'WINTER2025_EXACT_DISPOSABLE_LAST_TRADE_WITNESS')
        core = PortfolioState.fresh(9000, n_slots=cfg.n_slots,
                                   entry_sizing_profile=v5.entry_sizing_profile(cfg.economic_profile))
        core.episodes[0] = HoldingEpisode(sid, term['ticker'], witness['issuer_id'], 0,
            witness['session'], witness['session'], float(witness['raw_close']),
            float(witness['signal_close']), 10, 10,
            episode_peak_split_adjusted_close=float(witness['signal_close']),
            market_sessions_held=17, review_completed=True,
            source_lots=[dict(kind='EXPLICIT_DISPOSABLE_WINTER2025_COMPONENT_FIXTURE')])
        core.slots[0].occupied_by = sid; ledger = Ledger()
        result = apply_terminal(core, terminal_terms_from_dict(term['added']), ledger=ledger, session=day, cfg=cfg)
        need(result['applied'] is True, 'WINTER2025_POSITIVE_CASE_ACTUALLY_APPLIED')
        require_positive(core, ledger, sid, cash)
        once = deepcopy((core.to_dict(), ledger.to_dict()))
        repeat = apply_terminal(core, terminal_terms_from_dict(term['added']), ledger=ledger, session=day, cfg=cfg)
        need(repeat == dict(applied=False, reason='NOT_HELD', security_id=sid)
             and (core.to_dict(), ledger.to_dict()) == once,
             'WINTER2025_REPEAT_PAYMENT_AND_REMOVAL_UNCHANGED')
        core.cash -= 1
        try:
            require_positive(core, ledger, sid, cash)
        except ValueError as error:
            need(str(error) == 'REFUSED_FULL_SYSTEM_WINTER2025_CANONICAL_POSITIVE_CASH_REMOVAL',
                 'WINTER2025_WRONG_CASH_FALSIFIER_EXACT_REASON')
        else:
            raise ValueError('REFUSED_WINTER2025_POSITIVE_CASE_MUTATION_WAS_NOT_REJECTED')
        core.cash += 1; require_positive(core, ledger, sid, cash)
        checks.append(dict(ticker=term['ticker'], security_id=sid, recognition_session=day,
            last_trading_source_sha256=digest(witness), fixture_shares=10, fixture_cash=10. * cash,
            cash_scope=term['cash_scope'], recognition_rule=term['recognition_rule'],
            actual_cash_removal_once_only_and_changed_cash_falsifier_passed=True))
    need(runtime.checkpoint(restored) == cp['run'], 'WINTER2025_ALL_FIXTURES_LEAVE_ACTUAL_PARENT_UNCHANGED')
    save(out / 'winter2025-positive-cash-canonical-qualification.json', dict(
        status='ELEVEN_POSITIVE_CANONICAL_CASH_REMOVAL_AND_ONCE_ONLY_CASES_QUALIFIED',
        parent_checkpoint_sha256=cp['sha256'], checks=checks, actual_parent_unchanged=True,
        actual_parent_roundtrip=True, qualification_copy_only=True,
        financial_sessions_advanced=0, production_contacted=False))
