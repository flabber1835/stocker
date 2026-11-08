"""Hosted synthetic canonical action components. No financial state authority."""
import ast
from copy import deepcopy
from dataclasses import asdict
from fractions import Fraction
import gzip
import hashlib
import json
import math
import os
from pathlib import Path

MAP_IDENTITY = 'c3a47c8c7d7facc3d7bd798b74fd3f3fbb9dd0115b86369b7dc5b4f3e1aab915'
SCHEMA = 'research.p01-grouped-synthetic-canonical-components/1'
STOCK_CASES = {
    'WLH': dict(current=[5, 10], initial=[5, 10]),
    'VSLR': dict(current=[10, 10], initial=[20, 20]),
    'BMCH': dict(current=[8, 8], initial=[16, 16]),
    'WPX': dict(current=[1000, 1000], initial=[2000, 2000]),
}


def need(value, code):
    if not value:
        raise ValueError('REFUSED_P01_FACTUAL_COMPONENT_' + code)


def encoded(value):
    return (json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n').encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(encoded(value)[:-1])


def exact_representation(quantities, initials, ratio):
    """Representation oracle only: no state transition or trade implementation."""
    q = [Fraction(str(v)) for v in quantities]
    initial = [Fraction(str(v)) for v in initials]
    r = Fraction(ratio)
    need(q and len(q) == len(initial) and all(v > 0 for v in q), 'POSITIVE_SYNTHETIC_LOTS')
    total = sum(q, Fraction(0))
    whole = total * r
    need(whole.denominator == 1 and Fraction.from_float(float(whole)) == whole, 'AGGREGATE_REQUIRES_CIL_OR_INEXACT_TOTAL')
    done = 0.0
    result = []
    for index, (quantity, original) in enumerate(zip(q, initial)):
        actual = float(whole) - done if index == len(q) - 1 else float(whole * quantity / total)
        need(math.isfinite(actual) and actual > 0 and Fraction.from_float(actual) == quantity * r,
             'INEXACT_CANONICAL_EPISODE_ALLOCATION')
        reference = original * r
        need(reference > 0 and reference.denominator == 1
             and max(1, int(round(float(original) * float(r)))) == reference, 'INITIAL_REFERENCE_ROUNDING')
        result.append(dict(source_quantity=str(quantity), delivered_exact=str(quantity * r),
                           delivered=actual, delivered_binary64_hex=actual.hex(), initial_reference=int(reference)))
        done += actual
    need(Fraction.from_float(done) == whole, 'EXACT_AGGREGATE_ALLOCATION_CONSERVATION')
    return dict(holder_source_shares=str(total), holder_delivered_shares=int(whole), episodes=result)


def configuration(binding, factory):
    policy = binding.parent['base']['policy']
    value = factory(policy)
    need(value.economic_profile == policy and type(value.n_slots) is int and value.n_slots > 0,
         'EXACT_PARENT_FUNDING_POLICY_CONFIGURATION')
    return value


def action_prefix(source, namespace):
    """Compile the exact existing prefix, bounded before any fills or decisions."""
    tree = ast.parse(source)
    fn, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'step_session']
    cuts = [i for i, n in enumerate(fn.body) if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call)
            and isinstance(n.value.func, ast.Name) and n.value.func.id == '_resolved_open_equity']
    need(len(cuts) == 1, 'ONE_CANONICAL_PRE_FILL_OPEN_EQUITY_BOUNDARY')
    fn = deepcopy(fn)
    fn.name = '_qualified_component_action_prefix'
    fn.body = fn.body[:cuts[0] + 1]
    calls = {n.func.id for n in ast.walk(fn) if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    need({'apply_ticker_changes', '_rebind_session_issuers', 'apply_splits', 'apply_dividends',
          'apply_terminal', '_transform_pending_for_terminal', '_cancel_pending_issuer_conflicts',
          '_resolved_open_equity'} <= calls and not {'apply_entry', 'apply_exit', 'decide'} & calls,
         'ALL_CANONICAL_ACTION_SITES_AND_NO_FILLS_OR_DECISIONS')
    fn.body += ast.parse("return dict(resolved_open_equity=resolved_open_equity, open_unresolved=list(open_unresolved), "
                         "terminal_results=terminal_results, transformed=order_transformations, cancelled=res_cancelled)").body
    ns = dict(namespace)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<source-bound-canonical-action-prefix>', 'exec'), ns)
    return ns[fn.name]


def target_identity_mutation(source, namespace):
    fn, = [deepcopy(n) for n in ast.parse(source).body if isinstance(n, ast.FunctionDef)
           and n.name == '_transform_pending_for_terminal']
    sites = [n for n in ast.walk(fn) if isinstance(n, ast.Compare) and ast.unparse(n.left) == 'po.security_id'
             and len(n.ops) == 1 and isinstance(n.ops[0], ast.NotEq)
             and len(n.comparators) == 1 and ast.unparse(n.comparators[0]) == 'terms.security_id']
    need(len(sites) == 1, 'EXACT_SOURCE_INTENT_IDENTITY_MUTATION_SITE')
    sites[0].comparators[0] = ast.parse('terms.delivered_security_id', mode='eval').body
    ns = dict(namespace)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<disposable-target-identity-falsifier>', 'exec'), ns)
    return ns[fn.name]


def removed_scope_guard(source, namespace):
    fn, = [deepcopy(n) for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'require_scope']
    sites = [(parent, n) for parent in ast.walk(fn) if isinstance(getattr(parent, 'body', None), list)
             for n in parent.body
             if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
             and any(isinstance(v, ast.Constant) and v.value == 'UNSUPPORTED_INEXACT_CANONICAL_EPISODE_ALLOCATION'
                     for v in ast.walk(n.value))]
    need(len(sites) == 1, 'EXACT_ALLOCATION_GUARD_REMOVAL_SITE')
    parent, node = sites[0]
    parent.body.remove(node)
    ns = dict(namespace)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<actual-allocation-guard-removal>', 'exec'), ns)
    return ns[fn.name]


def same_state(actual, expected, label):
    need(actual == expected, 'ENTIRE_SESSIONSTATE_AND_LEDGER_' + label)


def write_progress(output, value):
    """One atomic cumulative proof, retaining completed cases on a later refusal."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    destination = output / 'target-independence-component.json.gz'
    temporary = output / 'target-independence-component.inflight'
    with temporary.open('xb') as stream:
        stream.write(gzip.compress(encoded(value), mtime=0))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, destination)
    return destination


def qualify_components(binding, template_state, output: Path):
    from full_system_core import hosted
    hosted()
    need(Path(output).resolve() == Path('/out/proof'), 'EXACT_DISPOSABLE_HOSTED_PROOF_OUTPUT')
    # Every canonical import and call is strictly after the actual hosted fence.
    from sentinel.core.session import SessionState
    from stock_strategy_shared.wealth_core import adapter, engine, ledger, state, terminal
    from stock_strategy_shared.wealth_core.funding import config
    from stock_strategy_shared.wealth_core.marks import Mark, MarkStatus
    from stock_strategy_shared.wealth_core.prices import DailyBar
    from p01_factual_batch_contract import facts, term
    import p01_factual_batch_guard as guard
    from core_window_review import reconcile

    need(digest(binding.source_map) == MAP_IDENTITY and len(binding.source_map['successor_all_sources']) == 516
         and len(binding.source_map['successor_financial_sources']) == 224, 'EXACT_RETAINED516_224_SOURCE_EPOCH')
    source_files = {}
    for name in ('shared/stock_strategy_shared/wealth_core/adapter.py', 'shared/stock_strategy_shared/wealth_core/terminal.py',
                 'shared/stock_strategy_shared/wealth_core/state.py', 'shared/stock_strategy_shared/wealth_core/ledger.py',
                 'shared/stock_strategy_shared/wealth_core/engine.py', 'shared/stock_strategy_shared/wealth_core/prices.py',
                 'shared/stock_strategy_shared/wealth_core/funding.py', 'shared/stock_strategy_shared/wealth_core/v5.py',
                 'shared/stock_strategy_shared/wealth_core/marks.py',
                 'sentinel/core/session.py'):
        raw = (Path('/variant') / name).read_bytes()
        need(sha(raw) == binding.source_map['successor_all_sources'][name]
             == binding.source_map['successor_financial_sources'][name], 'ACTUAL_CANONICAL_SOURCE_BYTES:' + name)
        source_files[name] = sha(raw)
    adapter_raw = Path(adapter.__file__).read_bytes()
    original_hooks = (adapter.step_session, adapter._transform_pending_for_terminal, terminal.apply_terminal)
    prefix = action_prefix(adapter_raw, adapter.__dict__)
    bad_namespace = dict(adapter.__dict__)
    bad_namespace['_transform_pending_for_terminal'] = target_identity_mutation(adapter_raw, adapter.__dict__)
    bad_prefix = action_prefix(adapter_raw, bad_namespace)
    cfg = configuration(binding, config)
    template = template_state.to_dict()
    need(len(template['wealth_core']['slots']) == cfg.n_slots, 'EXACT_PARENT_CONFIG_SLOT_COUNT')
    same_state(SessionState.from_dict(template).to_dict(), template, 'VALID_TEMPLATE_ROUNDTRIP')
    actions = {a['source_ticker']: a for a in facts()['records'] if a['exchange_ratio'] is not None}
    need(set(actions) == set(STOCK_CASES), 'EXACT_FOUR_ORDINARY_STOCK_COMPONENTS')
    record = dict(schema=SCHEMA, status='SYNTHETIC_COMPONENTS_STARTED', source_files=source_files,
                  source_map_identity_sha256=MAP_IDENTITY, target_cases={}, stock_cases={}, negative_cases=[],
                  configuration=dict(policy=binding.parent['base']['policy'], fields=asdict(cfg), config_hash=cfg.config_hash()),
                  all_component_positions_orders_and_used_prices_synthetic=True,
                  spectator_controller_history_from_template=True, actual_future_own_roles_claimed=False,
                  actual_provider_response_transferred=False, financial_authority=False,
                  independent_accounting_source_sha256=sha((Path(__file__).parent / 'core_window_review.py').read_bytes()),
                  qualification_state_adopted=False, target_independence_qualified=False,
                  ordinary_representation_qualified=False, held_target_holding_qualified=False,
                  held_source_with_target_pending_qualified=False)
    path = write_progress(output, record)

    def fixture(action, quantities=(), initials=(), target_role=None, target_holding=False):
        book = state.PortfolioState.fresh(50000., n_slots=cfg.n_slots)
        book.entry_sizing_profile = template['wealth_core']['entry_sizing_profile']
        need(book.entry_sizing_profile == cfg.economic_profile, 'TEMPLATE_AND_CANONICAL_PARENT_CONFIG_PROFILE')
        book.median5 = deepcopy(template['wealth_core']['median5'])
        journal = ledger.Ledger()
        pending = []
        sid, ticker, issuer = action['source_security_id'], action['source_ticker'], 'SYNTHETIC_SOURCE_ISSUER'
        if target_role in ('TARGET_HELD', 'TARGET_CLOSE_PENDING'):
            sid, ticker, issuer = action['delivered_security_id'], action['delivered_ticker'], action['delivered_issuer_id']
            quantities, initials = [10], [10]
        for slot, (current, initial) in enumerate(zip(quantities, initials)):
            entry_day = ('2020-01-02', '2020-01-06')[slot]
            sale_day = ('2020-01-03', '2020-01-07')[slot]
            cost = engine.entry_cost(initial, 1., cfg)
            before = book.cash
            journal.post(session=entry_day, event_type=ledger.EventType.BUY, cash_before=before, cash_delta=-cost,
                         security_id=sid, ticker=ticker, shares_delta=initial, price=1., fees=cost - initial,
                         reason='SYNTHETIC_COMPONENT_SETUP')
            engine.apply_entry(book, op=engine.Op(engine.Operation.OPEN_SLOT_POSITION, 'SYNTHETIC_COMPONENT_SETUP',
                slot_id=slot, security_id=sid, ticker=ticker, shares=initial), session=entry_day,
                signal_session='2019-12-31', raw_open=1., split_adjusted_price=2., issuer_id=issuer, cfg=cfg)
            ep = book.episodes[slot]
            ep.episode_peak_split_adjusted_close = 3.
            ep.market_sessions_held = 17
            ep.review_completed = True
            if initial != current:
                sold = initial - current
                need(sold > 0, 'SYNTHETIC_PARTIAL_SALE_IS_POSITIVE')
                proceeds = engine.exit_proceeds(sold, 1., cfg)
                journal.post(session=sale_day, event_type=ledger.EventType.SELL, cash_before=book.cash,
                             cash_delta=proceeds, security_id=sid, ticker=ticker, shares_delta=-sold,
                             price=1., fees=sold - proceeds, reason='SYNTHETIC_PARTIAL_LOT_SETUP')
                book.cash += proceeds
                ep.current_shares = current
        if target_holding:
            slot = len(quantities)
            target_sid, target_ticker = action['delivered_security_id'], action['delivered_ticker']
            cost = engine.entry_cost(7, 1., cfg)
            journal.post(session='2020-01-08', event_type=ledger.EventType.BUY, cash_before=book.cash, cash_delta=-cost,
                security_id=target_sid, ticker=target_ticker, shares_delta=7, price=1., fees=cost - 7,
                reason='SYNTHETIC_PREEXISTING_TARGET_SETUP')
            engine.apply_entry(book, op=engine.Op(engine.Operation.OPEN_SLOT_POSITION, 'SYNTHETIC_PREEXISTING_TARGET_SETUP',
                slot_id=slot, security_id=target_sid, ticker=target_ticker, shares=7), session='2020-01-08',
                signal_session='2020-01-07', raw_open=1., split_adjusted_price=2.,
                issuer_id=action['delivered_issuer_id'], cfg=cfg)
            book.episodes[slot].episode_peak_split_adjusted_close = 3.
        if target_role == 'TARGET_CLOSE_PENDING':
            book.episodes[0].exit_pending = True
            book.episodes[0].exit_reason = 'SYNTHETIC_TARGET_CLOSE'
            pending.append(adapter.PendingOrder(engine.Operation.CLOSE_POSITION, sid, ticker, 0, 10,
                                                '2020-02-04', 'SYNTHETIC_TARGET_CLOSE'))
        if target_role == 'TARGET_DOLLAR_BUY_PENDING':
            sid, ticker, issuer = action['delivered_security_id'], action['delivered_ticker'], action['delivered_issuer_id']
            book.slots[0].reserve(sid, ticker, issuer)
            pending.append(adapter.PendingOrder(engine.Operation.OPEN_SLOT_POSITION, sid, ticker, 0, 0,
                                                '2020-02-04', 'SYNTHETIC_TARGET_DOLLAR_BUY', intended_dollars=500.))
        raw = deepcopy(template)
        raw.update(wealth_core=book.to_dict(), ledger=journal.to_dict(), pending=[p.to_dict() for p in pending],
                   last_known={action['source_security_id']: 10., action['delivered_security_id']: 20.})
        full = SessionState.from_dict(raw)
        # Canonical normalization may drop now-unprotected historical quote anchors.
        # Establish this synthetic fixture once, then compare complete canonical wires.
        normalized = full.to_dict()
        same_state(SessionState.from_dict(normalized).to_dict(), normalized, 'SYNTHETIC_FIXTURE_CANONICAL_FULL_ROUNDTRIP')
        return full

    def phase(full, action, with_term=True, mutated=False):
        raw = full.to_dict()
        candidate = SessionState.from_dict(deepcopy(raw))
        book = state.PortfolioState.from_dict(candidate.wealth_core)
        journal = ledger.Ledger.from_dict(candidate.ledger)
        pending = [adapter.PendingOrder.from_dict(p) for p in candidate.pending]
        target = DailyBar(action['delivered_security_id'], action['delivered_ticker'], action['delivered_issuer_id'],
                          action['economic_session'], 60., 20., 20.)
        source = DailyBar(action['source_security_id'], action['source_ticker'], 'SYNTHETIC_SOURCE_ISSUER',
                          action['economic_session'], 20., 10., 10.)
        typed = terminal.terminal_terms_from_dict(term(action))
        need(asdict(terminal.terminal_terms_from_dict(asdict(typed))) == asdict(typed), 'ORDINARY_TYPED_TERM_ROUNDTRIP')
        result = (bad_prefix if mutated else prefix)(session=action['economic_session'], state=book,
            bars=[source, target], pending=pending, ledger=journal, last_known=dict(candidate.last_known), cfg=cfg,
            strategy_id='SYNTHETIC_COMPONENT_ONLY', strategy_version=1, security_bars=[],
            terminal_terms=[typed] if with_term else [])
        candidate.wealth_core, candidate.ledger, candidate.pending = book.to_dict(), journal.to_dict(), [p.to_dict() for p in pending]
        following = candidate.to_dict()
        same_state(SessionState.from_dict(following).to_dict(), following, 'ACTION_PHASE_FULL_CANONICAL_ROUNDTRIP')
        same_state(ledger.Ledger.from_dict(following['ledger']).to_dict(), following['ledger'], 'ACTION_PHASE_LEDGER_ROUNDTRIP')
        return following, result

    def refused(label, full, action, expected):
        before = full.to_dict()
        try:
            guard.require_scope(full, action)
        except ValueError as error:
            need(expected in str(error), 'EXPECTED_SPECIFIC_GUARD_REFUSAL:' + label)
            message = str(error)
        else:
            raise ValueError('SYNTHETIC_COMPONENT_NEGATIVE_ACCEPTED:' + label)
        same_state(full.to_dict(), before, 'NEGATIVE_CALLER_UNCHANGED:' + label)
        record['negative_cases'].append(dict(case=label, error=message, caller_full_state_and_ledger_unchanged=True))
        write_progress(output, record)

    def accounting(full, action, result):
        snapshot = dict(wealth_core=full['wealth_core'], ledger=full['ledger'],
                        prices={action['delivered_security_id']: dict(status='RAW_OPEN', raw_price=20.)},
                        resolved_equity=result['resolved_open_equity'])
        reconcile(snapshot)
        return dict(full_ledger_cash_quantity_fee_and_opening_equity_reconciled=True,
                    resolved_equity=result['resolved_open_equity'], synthetic_raw_open=20.)

    try:
        wlh = actions['WLH']
        for role in ('TARGET_HELD', 'TARGET_CLOSE_PENDING', 'TARGET_DOLLAR_BUY_PENDING'):
            full = fixture(wlh, target_role=role)
            before = full.to_dict()
            guard.require_scope(full, wlh)
            baseline, base_result = phase(full, wlh, with_term=False)
            actual, result = phase(full, wlh)
            same_state(actual, baseline, 'TARGET_ACTION_WITH_VERSUS_WITHOUT_TERM:' + role)
            same_state(actual, before, 'UNHELD_SOURCE_PRESERVES_COMPLETE_TARGET_STATE:' + role)
            bad, _ = phase(full, wlh, mutated=True)
            mutation_detected = bad != baseline if role != 'TARGET_HELD' else None
            if role != 'TARGET_HELD':
                need(mutation_detected, 'ACTUAL_TARGET_IDENTITY_MUTATION_MUST_FAIL:' + role)
            independent = accounting(actual, wlh, result)
            record['target_cases'][role] = dict(before=before, canonical_without_term_state=baseline,
                canonical_with_term_state=actual, actual_action_result=result, source_security_id=wlh['source_security_id'],
                canonical_control_result=base_result, actual_mutated_state=bad,
                independent_accounting=independent,
                source_vs_target_mutation_detected=mutation_detected, full_state_roundtrip=True,
                source_unheld=True, all_source_pending_absent=True)
            write_progress(output, record)

        for ticker, quantities in STOCK_CASES.items():
            action = actions[ticker]
            expected = exact_representation(quantities['current'], quantities['initial'], action['exchange_ratio'])
            full = fixture(action, quantities['current'], quantities['initial'], target_holding=True)
            before = full.to_dict()
            guard.require_scope(full, action)
            actual, result = phase(full, action)
            independent = accounting(actual, action, result)
            new_events = actual['ledger']['events'][len(before['ledger']['events']):]
            need(len(new_events) == len(quantities['current']) and all(e['event_type'] == 'CONVERSION' for e in new_events),
                 'ONE_ORDINARY_CONVERSION_EVENT_PER_SOURCE_LOT')
            same_state(actual['ledger']['events'][:len(before['ledger']['events'])], before['ledger']['events'], 'OLD_SYNTHETIC_LEDGER_PREFIX')
            cash = Fraction(action['cash_per_share'] or '0') * Fraction(expected['holder_source_shares'])
            need(actual['wealth_core']['cash'] == before['wealth_core']['cash'] + float(cash)
                 and sum(Fraction.from_float(float(e['detail']['shares_delivered'])) for e in new_events)
                     == expected['holder_delivered_shares']
                 and all(e['fees'] == 0 and e['detail']['cash_in_lieu'] == 0 for e in new_events), 'EXACT_HOLDER_STOCK_AND_LEGAL_CASH_NO_CIL_OR_FEE')
            total = Fraction(expected['holder_source_shares'])
            ratio = float(action['exchange_ratio'])
            rebase = cash != 0
            multiplier = float(total * 20 / (cash + expected['holder_delivered_shares'] * 20)) if rebase else 1. / ratio
            signal = 1.5 * multiplier if rebase else 1.5 / ratio
            for index, e in enumerate(expected['episodes']):
                old = before['wealth_core']['episodes'][str(index)]
                new = actual['wealth_core']['episodes'][str(index)]
                need(new['security_id'] == action['delivered_security_id'] and new['current_shares'] == e['delivered']
                     and new['initial_shares'] == e['initial_reference']
                     and new['entry_raw_open'] == (old['entry_raw_open'] * multiplier if rebase else old['entry_raw_open'] / ratio)
                     and new['entry_split_adjusted_price'] == old['entry_split_adjusted_price'] * signal
                     and new['episode_peak_split_adjusted_close'] == old['episode_peak_split_adjusted_close'] * signal
                     and all(new[k] == old[k] for k in ('market_sessions_held', 'review_completed', 'exit_pending', 'entry_date', 'signal_date'))
                     and new['source_lots'][:-1] == old['source_lots'], 'CANONICAL_QUANTITY_INITIAL_REFERENCE_AND_PROVENANCE:' + ticker)
            target_slot = str(len(quantities['current']))
            same_state(actual['wealth_core']['episodes'][target_slot], before['wealth_core']['episodes'][target_slot],
                       'PREEXISTING_TARGET_EPISODE_UNCHANGED:' + ticker)
            need(actual['pending'] == before['pending'] == [], 'HELD_SOURCE_TARGET_HOLDING_SCOPE_HAS_NO_PENDING_INTERACTION')
            book = state.PortfolioState.from_dict(actual['wealth_core'])
            marks = {action['delivered_security_id']: Mark(action['delivered_security_id'], MarkStatus.CURRENT, raw_mark_close=20.)}
            journal = ledger.Ledger.from_dict(actual['ledger'])
            report = terminal.final_report(session=action['economic_session'], state=book, marks=marks, ledger=journal, cfg=cfg).to_dict()
            need(report['aggregate_by_security'][action['delivered_security_id']]['shares'] == expected['holder_delivered_shares'] + 7
                 and result['resolved_open_equity'] == book.cash + (expected['holder_delivered_shares'] + 7) * 20.,
                 'CANONICAL_FULL_REPORT_AND_OPENING_VALUE')
            record['stock_cases'][ticker] = dict(terms=term(action), synthetic_quantities=quantities, before=before,
                after=actual, actual_action_result=result, independent_representation=expected, canonical_report=report,
                independent_accounting=independent,
                exact_legal_cash=str(cash), no_CIL_rate_supplied=True, canonical_reference_multiplier=multiplier,
                preexisting_target_quantity=7, preexisting_target_episode_unchanged=True,
                canonical_signal_multiplier=signal, reference_binary64_policy='EXACT_EXISTING_OPERATION_ORDER_NOT_IDEAL_REAL_ARITHMETIC')
            write_progress(output, record)

        vslr = actions['VSLR']
        refused('HOLDER_FRACTION_WITHOUT_CIL', fixture(vslr, [1, 1], [20, 20]), vslr, 'UNSUPPORTED_NONINTEGRAL_HOLDER_ENTITLEMENT')
        initial_bad = fixture(vslr, [10, 10], [10, 10])
        refused('INITIAL_REFERENCE_ROUNDING', initial_bad, vslr, 'UNSUPPORTED_CANONICAL_INITIAL_REFERENCE_ROUNDING')
        inexact = fixture(wlh, [1, 4], [5, 5])
        refused('INEXACT_EPISODE_BINARY64', inexact, wlh, 'UNSUPPORTED_INEXACT_CANONICAL_EPISODE_ALLOCATION')
        broken = removed_scope_guard(Path(guard.__file__).read_bytes(), guard.__dict__)
        broken(inexact, wlh)
        record['actual_allocation_guard_removal_accepts_bad_fixture'] = True
        exiting = fixture(wlh, [5], [5])
        exiting.wealth_core['episodes']['0']['exit_pending'] = True
        refused('SOURCE_EPISODE_EXIT_FLAG_WITHOUT_PENDING', exiting, wlh, 'UNSUPPORTED_SOURCE_EPISODE_EXIT_FLAG')
        ordered = fixture(wlh)
        ordered.wealth_core['slots']['0'].update(reserved_for=wlh['source_security_id'], reserved_ticker=wlh['source_ticker'], reserved_issuer='SYNTHETIC_SOURCE_ISSUER')
        ordered.pending = [adapter.PendingOrder(engine.Operation.OPEN_SLOT_POSITION, wlh['source_security_id'], wlh['source_ticker'],
            0, 0, '2020-02-04', 'SYNTHETIC_SOURCE_DOLLAR_BUY', intended_dollars=500.).to_dict()]
        ordered = SessionState.from_dict(ordered.to_dict())
        refused('SOURCE_PENDING_DOLLAR_BUY', ordered, wlh, 'UNSUPPORTED_SOURCE_PENDING_INTENT')
        need((adapter.step_session, adapter._transform_pending_for_terminal, terminal.apply_terminal) == original_hooks,
             'CANONICAL_MODULE_GLOBAL_HOOKS_UNCHANGED')
        record.update(status='SYNTHETIC_CANONICAL_COMPONENTS_PASSED_NOT_FINANCIAL_ADMISSION',
                      target_independence_qualified=True, ordinary_representation_qualified=True,
                      held_target_holding_qualified=True,
                      canonical_module_global_hooks_unchanged=True)
        path = write_progress(output, record)
    except BaseException as error:
        record.update(status='SYNTHETIC_COMPONENT_REFUSAL_PARTIAL_PROOFS_PRESERVED',
                      error_class=type(error).__name__, error=str(error)[:1200])
        write_progress(output, record)
        raise
    finally:
        same_state(template_state.to_dict(), template, 'ORIGINAL_TEMPLATE_CALLER_UNCHANGED')
        need((adapter.step_session, adapter._transform_pending_for_terminal, terminal.apply_terminal) == original_hooks,
             'CANONICAL_MODULE_GLOBAL_HOOKS_UNCHANGED_ON_EXIT')
    return dict(target_independence_qualified=True, ordinary_representation_qualified=True,
                held_target_holding_qualified=True,
                proof_file=path.name, proof_sha256=sha(path.read_bytes()), synthetic_only=True,
                financial_authority=False, target_cases=3, stock_cases=4, negative_cases=len(record['negative_cases']))
