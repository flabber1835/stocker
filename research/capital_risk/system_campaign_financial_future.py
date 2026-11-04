"""Selected future ordinary facts, with read-only actual cash/risk postconditions."""
from copy import deepcopy
from dataclasses import asdict
import inspect
import json
import math
from pathlib import Path
from types import SimpleNamespace
import zipfile

from full_system_benchmark import need, save
from full_system_core import hosted
from system_campaign_facts import digest, sha

HERE = Path(__file__).parent
OVERLAY = 'future-financial-overlay.json'
HYDRATED = 'hydrated-future-financial-terminal-catalog.json'
REFERENCE = 'research:system-optimization-002/selected-future-ordinary-input/1'
PLANS = {
    'P04': ('system_campaign_following_completions_facts', 'FollowingFacts',
            'system-campaign-following-completions-terminal-facts.json', ('APHA', 'CATM', 'REGI', 'PLAN')),
    'P10': ('system_campaign_autumn2020_cash_facts', 'CashCompletionFacts',
            'system-campaign-autumn2020-cash-terminal-facts.json', ('MNTA', 'AIMT', 'IMMU', 'MYOK', 'VRTU')),
}


def selected(arm):
    import importlib
    module, cls, catalog, tickers = PLANS[arm]
    codec = getattr(importlib.import_module(module), cls)(HERE / catalog)
    terms = [deepcopy(t) for t in codec.catalog['terms'] if t['ticker'] in tickers]
    need(tuple(t['ticker'] for t in terms) == tickers, 'FUTURE_EXACT_DECLARED_CATALOG_SUBSET')
    return codec, catalog, terms


def pending_completion(cp, term):
    """Only MNTA's exact admitted pending native can be completed after consumption."""
    sid = term['security_id']
    w = cp['run']['state']['wealth_core']
    held = [(k, e) for k, e in w['episodes'].items() if e['security_id'] == sid]
    pending = w.get('terminal_pending_terms', {}).get(sid, {})
    need(sid == '510659411298086546' and term['ticker'] == 'MNTA'
         and cp['source_cursor'] == term['native_session'] == '2020-09-30'
         and term['added']['session'] == '2020-10-01' and term['added']['cash_per_share'] == 52.5
         and w['terminal_pending_sessions'].get(sid) == 0 and pending.get('stale_at_event') == 0
         and digest(pending.get('terms')) == term['native_term_sha256']
         and len(held) == 1 and held[0][0] == '5' and held[0][1]['slot_id'] == 5
         and held[0][1]['current_shares'] == 101 and held[0][1]['exit_pending'] is False
         and w['slots']['5']['occupied_by'] == sid and sid not in w.get('unresolved_terminals', {})
         and w['terminal_carry_audit'][sid] == dict(carry_price=52.49, carry_session='2020-09-30',
             grace_prints=[dict(price=52.48, session='2020-09-30')], grace_split_multiplier=1.,
             grace_splits=[], last_trustworthy_print_session='2020-09-29', shares_at_carry=101),
         'FUTURE_EXACT_ADMITTED_HELD_MNTA_PENDING_NATIVE')


def suppressions(cp, terms):
    result = []
    for t in terms:
        need(t['added']['session'] > cp['source_cursor'], 'FUTURE_COMPLETE_TERMS_UNCONSUMED')
        if t['native_session'] <= cp['source_cursor']:
            pending_completion(cp, t)
        else:
            result.append(dict(session=t['native_session'], security_id=t['security_id'],
                               term_sha256=t['native_term_sha256']))
    return result


def hydrate(cp, arm):
    hosted()
    from research.pooled_input_support import inputs
    from system_campaign_2021_completions_facts import require_witness, CIL
    codec, catalog, terms = selected(arm)
    suppressions(cp, terms)
    actions = inputs.load_actions(Path('/frozen/bundle'))
    wanted = {}
    for t in terms:
        native, = [v for v in actions.terminal.get(t['native_session'], ()) if v.security_id == t['security_id']]
        need(digest(asdict(native)) == t['native_term_sha256'] and not native.completeness(0)[0],
             'FUTURE_EXACT_INCOMPLETE_FROZEN_NATIVE')
        need(not any(v.security_id == t['security_id'] for v in actions.terminal.get(t['added']['session'], ())),
             'FUTURE_NO_CONFLICTING_EFFECTIVE_TERM')
        for w in (t['identity_witness'], *([t['delivered_identity_witness']] if 'delivered_identity_witness' in t else [])):
            key = w['session'], w['security_id']
            need(key not in wanted, 'FUTURE_UNIQUE_DECLARED_WITNESS')
            wanted[key] = w
    seen = {}
    with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
        for year in sorted({day[:4] for day, _ in wanted}):
            for row in inputs._archive_rows(archive, 'observations-' + year + '.csv.gz'):
                key = row['session'], row['security_id']
                if key not in wanted:
                    continue
                need(key not in seen, 'FUTURE_UNIQUE_ACTUAL_WITNESS')
                require_witness(row, wanted[key])
                seen[key] = row
    need(set(seen) == set(wanted), 'FUTURE_ALL_SELECTED_NATIVE_AND_DELIVERY_WITNESSES')
    delivered = {}
    for t in terms:
        if 'delivered_identity_witness' not in t:
            continue
        w = t['delivered_identity_witness']
        row = seen[w['session'], w['security_id']]
        price = float(row['raw_open'])
        need(math.isfinite(price) and price > 0, 'FUTURE_POSITIVE_DECLARED_RAW_OPEN_CIL_PROXY')
        t['added']['cash_in_lieu_price_per_delivered_share'] = price
        delivered[t['security_id']] = row
    material = dict(schema=REFERENCE, arm=arm, catalog=catalog, catalog_sha256=codec.catalog_sha,
        original_validator_sha256=codec.compiler_sha, selector_sha256=sha(Path(__file__).read_bytes()),
        parent_outer_sha256=cp['sha256'], terms=terms,
        cil_convention=CIL if delivered else None, native_and_delivery_witnesses_verified=len(seen),
        consumed_native_preserved=[t['security_id'] for t in terms if t['native_session'] <= cp['source_cursor']],
        financial_source_changed=False, provider_metadata_upgraded=False)
    return material, delivered, actions


def document(cp, material, hydrated_sha):
    evidence = [dict(reference=REFERENCE + '/' + name, description=description, sha256=value)
        for name, description, value in (
            ('catalog', 'Unchanged literal ordinary completion catalog.', material['catalog_sha256']),
            ('validator', 'Original literal catalog validator; original compiler guard remains intact.', material['original_validator_sha256']),
            ('selector', 'Own-parent future-only selected ordinary input.', material['selector_sha256']),
            ('hydrated', 'Actual frozen native and complete identity/delivery witnesses.', hydrated_sha))]
    for t in material['terms']:
        evidence.extend((dict(reference=t['primary_source'], description=t['description'], sha256=None),
            dict(reference=t['timing_source'], description='Actual mandatory completion; preserve native trading history.', sha256=None)))
    return dict(schema='terminal-repair/1', predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'],
        source_evidence=evidence, suppress=suppressions(cp, material['terms']),
        add=[deepcopy(t['added']) for t in material['terms']])


def qualify(cp, material, delivered, actions, loaded, path, out):
    from research.pooled_input_support.adapter import Packet
    from research.pooled_vacancy_funding import backtest
    from research.pooled_vacancy_funding.repair import load_repair
    from research.bounded_20y.run import vendor
    from sentinel.controller import terminal_returns
    from system_campaign_sprint_facts import published_packet, qualify_packet_schema
    from system_campaign_2021_completions_facts import notional, require_witness
    qualify_packet_schema(Packet, cp['base']['sources']['research/pooled_input_support/adapter.py'])
    checks = 0
    for t in material['terms']:
        sid = t['security_id']
        bar = vendor(delivered[sid]) if sid in delivered else None
        prior = SimpleNamespace(median5={'selected': [sid]}, feed={'series': {sid: {
            'signal_basis_anchor': (t['last_trading_session'], 1., 1.)}}}, last_processed_session=t['last_trading_session'])
        for day in (t['native_session'], t['added']['session']):
            original = Packet(day, (bar,) if bar and day == t['added']['session'] else (), {}, {}, 1., {},
                              tuple(actions.terminal.get(day, ())), ())
            before = asdict(original)
            fixed = backtest.apply_repair(original, loaded)
            expected = deepcopy(before)
            expected['terminal'] = asdict(fixed)['terminal']
            need(asdict(original) == before and asdict(fixed) == expected,
                 'FUTURE_ONLY_TERMINAL_PACKET_FIELD_CHANGED')
            matches = [v for v in fixed.terminal if v.security_id == sid]
            if day == t['added']['session']:
                need(len(matches) == 1 and asdict(matches[0]) == t['added'] and matches[0].completeness(1)[0],
                     'FUTURE_EXACT_COMPLETE_ORDINARY_TERM')
                values = terminal_returns.values(prior=prior, published=published_packet(fixed))
                need(values[sid] == float(notional(t['added'], bar)), 'FUTURE_EXACT_CANONICAL_CONTROLLER_NOTIONAL')
                if bar:
                    try:
                        terminal_returns.values(prior=prior, published=SimpleNamespace(session=day, bars=(), terminal_events=fixed.terminal))
                    except ValueError as error:
                        need('lacks delivered close' in str(error), 'FUTURE_MISSING_DELIVERY_REFUSAL_REASON')
                    else:
                        raise ValueError('REFUSED_FUTURE_MISSING_DELIVERY_QUOTE_ACCEPTED')
                    try:
                        require_witness({**delivered[sid], 'issuer_id': 'WRONG'}, t['delivered_identity_witness'])
                    except ValueError:
                        pass
                    else:
                        raise ValueError('REFUSED_FUTURE_WRONG_DELIVERY_IDENTITY_ACCEPTED')
            elif day <= cp['source_cursor']:
                need(fixed == original and len(matches) == 1, 'FUTURE_CONSUMED_NATIVE_PACKET_UNCHANGED')
            else:
                need(not matches, 'FUTURE_LAST_NATIVE_TRADING_SESSION_PRESERVED')
                bad = json.loads(path.read_bytes())
                row, = [r for r in bad['suppress'] if r['security_id'] == sid]
                row['term_sha256'] = '0' * 64
                target = out / ('wrong-native-' + t['ticker'] + '.json')
                save(target, bad)
                wrong = load_repair(target, resume_session=cp['source_cursor'], predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
                try:
                    backtest.apply_repair(original, wrong)
                except ValueError as error:
                    need(str(error).startswith('suppressed original terminal differs:'), 'FUTURE_NATIVE_PREIMAGE_REFUSAL_REASON')
                else:
                    raise ValueError('REFUSED_FUTURE_WRONG_NATIVE_ACCEPTED')
            checks += 1
        # The original canonical incomplete-term guard must still refuse.
        native = Packet(t['native_session'], (), {}, {}, 1., {}, tuple(actions.terminal.get(t['native_session'], ())), ())
        day = t['identity_witness']['session']
        native_prior = SimpleNamespace(median5={'selected': [sid]}, feed={'series': {sid: {
            'signal_basis_anchor': (day, 1., 1.)}}}, last_processed_session=day)
        try:
            terminal_returns.values(prior=native_prior, published=published_packet(native))
        except ValueError as error:
            need('incomplete leadership cash terminal' in str(error), 'FUTURE_ORIGINAL_INCOMPLETE_GUARD_REASON')
        else:
            raise ValueError('REFUSED_FUTURE_ORIGINAL_INCOMPLETE_GUARD_MISSING')
    for cursor, predecessor in ((cp['source_cursor'], '0' * 64),
                                (loaded.earliest_affected_session, cp['run']['checkpoint_sha256'])):
        try:
            load_repair(path, resume_session=cursor, predecessor_checkpoint_sha256=predecessor)
        except ValueError:
            pass
        else:
            raise ValueError('REFUSED_FUTURE_ORDINARY_PARSER_FALSIFIER_ACCEPTED')
    save(out / 'future-input-qualification.json', dict(passed=True, packet_checks=checks,
        only_terminal_field_changed=True, complete_terms_and_canonical_notional_verified=True,
        original_incomplete_guard_retained=True, wrong_predecessor_and_consumed_date_refused=True,
        wrong_native_and_delivery_witness_refused=True, financial_sessions_advanced=0))


def prepare(cp, out, arm):
    material, delivered, actions = hydrate(cp, arm)
    save(out / HYDRATED, material)
    path = out / OVERLAY
    save(path, document(cp, material, sha((out / HYDRATED).read_bytes())))
    from research.pooled_vacancy_funding.repair import load_repair
    loaded = load_repair(path, resume_session=cp['source_cursor'], predecessor_checkpoint_sha256=cp['run']['checkpoint_sha256'])
    qualify(cp, material, delivered, actions, loaded, path, out)
    return path, loaded


def review_input(cp, evidence, arm):
    material, _, _ = hydrate(cp, arm)
    need(json.loads((evidence / HYDRATED).read_bytes()) == material
         and json.loads((evidence / OVERLAY).read_bytes()) == document(cp, material, sha((evidence / HYDRATED).read_bytes())),
         'FUTURE_INDEPENDENT_RECONSTRUCTION_OF_COMPLETE_SELECTED_INPUT')
    return min(r['session'] for field in ('suppress', 'add') for r in json.loads((evidence / OVERLAY).read_bytes())[field])


def cash_postcondition(before, after, ledger_before, ledger_after, terms, result):
    sid, price = terms['security_id'], terms['cash_per_share']
    held = [(k, v) for k, v in sorted(before['episodes'].items(), key=lambda x: int(x[0])) if v['security_id'] == sid]
    if not held:
        need(result['reason'] == 'NOT_HELD' and before == after and ledger_before == ledger_after,
             'FUTURE_UNHELD_CASH_EXACT_NOOP')
        return dict(actual_held=False, quantity=0, nominal_cash=0.)
    running = before['cash']
    events = ledger_after['events'][len(ledger_before['events']):]
    need(result['applied'] is True and ledger_after['events'][:len(ledger_before['events'])] == ledger_before['events']
         and len(events) == len(held), 'FUTURE_EXACT_NUMBER_AND_PREFIX_OF_CASH_POSTS')
    for (slot, episode), event in zip(held, events):
        q = episode['current_shares']
        proceeds = q * price
        need(event['event_type'] == 'CASH_MERGER' and event['security_id'] == sid
             and event['price'] == price and event['shares_delta'] == -q and event['cash_delta'] == proceeds
             and event['detail']['shares'] == q and event['detail']['reference'] == terms['reference']
             and event['fees'] == 0. and event['cash_before'] == running and event['cash_after'] == running + proceeds
             and after['slots'][str(slot)]['occupied_by'] is None, 'FUTURE_EXACT_CONTRACTUAL_CASH_OPERATION_ORDER')
        running += proceeds
    need(after['cash'] == running
         and {k: v for k, v in before['episodes'].items() if v['security_id'] != sid} == after['episodes']
         and ledger_before.get('receivables', []) == ledger_after.get('receivables', [])
         and sid not in after.get('terminal_pending_sessions', {}) and sid not in after.get('terminal_pending_terms', {}),
         'FUTURE_CASH_SETTLED_SOURCE_REMOVED_OTHER_EPISODES_RECEIVABLES_UNCHANGED')
    return dict(actual_held=True, quantity=sum(e['current_shares'] for _, e in held),
                nominal_cash=sum(e['current_shares'] * price for _, e in held))


def actual_terminal_call(frame, step_code, state, ledger, session):
    return (frame.f_code is step_code and frame.f_locals.get('state') is state
            and frame.f_locals.get('ledger') is ledger and frame.f_locals.get('session') == session)


class ActualEvents:
    """Delegate unchanged canonical calls; check postconditions before journal commit."""
    def __init__(self, out, arm):
        self.out, self.arm = out, arm
        self.terms = {(t['session'], t['security_id']): t for t in json.loads((out / OVERLAY).read_bytes())['add']}
        self.saved, self.current = [], None

    def patch(self, owner, name, replacement):
        old = getattr(owner, name)
        self.saved.append((owner, name, old))
        setattr(owner, name, replacement)
        return old

    def __enter__(self):
        hosted()
        from research.pooled_vacancy_funding import runtime
        from stock_strategy_shared.wealth_core import terminal, adapter
        # actual_parent already verified the entire own canonical source map.
        self.step_code = adapter.step_session.__code__
        self.advance_original = self.patch(runtime, 'advance', self.advance)
        self.terminal_original = self.patch(terminal, 'apply_terminal', self.terminal)
        if self.arm == 'P10':
            from stock_strategy_shared.wealth_core import capital_risk
            self.decide_original = self.patch(adapter, 'decide', self.decide)
            self.risk_original = self.patch(capital_risk, 'volatility_stop', self.risk)
        return self

    def __exit__(self, *args):
        for owner, name, old in reversed(self.saved):
            setattr(owner, name, old)

    def terminal(self, state, terms, **kwargs):
        key = terms.session, terms.security_id
        if self.current is None or key not in self.terms or terms.kind != 'CASH_MERGER':
            return self.terminal_original(state, terms, **kwargs)
        before, ledger = deepcopy(state.to_dict()), deepcopy(kwargs['ledger'].to_dict())
        caller = inspect.currentframe().f_back
        actual = actual_terminal_call(caller, self.step_code, state, kwargs['ledger'], terms.session)
        need(asdict(terms) == self.terms[key], 'FUTURE_ACTUAL_TERMS_EXACT_SELECTED_CONTRACT')
        result = self.terminal_original(state, terms, **kwargs)
        proof = cash_postcondition(before, state.to_dict(), ledger, kwargs['ledger'].to_dict(), asdict(terms), result)
        need(kwargs.get('phase', 'OPEN') == 'OPEN', 'FUTURE_ACTUAL_CASH_OPEN_PHASE')
        self.current['cash'].append(dict(session=terms.session, security_id=terms.security_id,
            actual_context_call=actual, postcondition=proof))
        if actual:
            self.current['order'].append('CASH:' + terms.security_id)
        return result

    def decide(self, **kwargs):
        if self.current is None:
            return self.decide_original(**kwargs)
        eligible = [(int(k), v['security_id']) for k, v in sorted(kwargs['state'].to_dict()['episodes'].items(), key=lambda x: int(x[0])) if not v['exit_pending']]
        offset = len(self.current['risk'])
        self.current['order'].append('ENGINE')
        result = self.decide_original(**kwargs)
        need(self.current['risk'][offset:] == eligible, 'FUTURE_ALL_SURVIVING_EPISODES_TRAVERSE_ORIGINAL_V_GUARD')
        self.current['engine_calls'] += 1
        return result

    def risk(self, ep, *, bars, session, cfg):
        result = self.risk_original(ep, bars=bars, session=session, cfg=cfg)
        if self.current is not None:
            from sentinel.feed.calendar import previous_sessions
            bar = next((b for b in bars if b.security_id == ep.security_id), None)
            need(cfg.economic_profile == 'wealth-core-capital-risk-v-v1' and bar is not None
                 and list(bar.signal_sessions or ()) == previous_sessions(session, 21) and len(bar.closes) >= 21,
                 'FUTURE_ORIGINAL_V21_CAUSAL_AXIS')
            self.current['risk'].append((ep.slot_id, ep.security_id))
        return result

    def advance(self, run, publication):
        need(self.current is None, 'FUTURE_SINGLE_ACTUAL_ADVANCE')
        record = self.current = dict(session=publication.session, cash=[], risk=[], order=[], engine_calls=0)
        try:
            result = self.advance_original(run, publication)
            if self.arm == 'P10' and publication.session == '2020-10-01':
                sid = '510659411298086546'
                actual = [r for r in record['cash'] if r['actual_context_call'] and r['security_id'] == sid]
                need(len(actual) == 1 and actual[0]['postcondition'] == dict(actual_held=True, quantity=101, nominal_cash=5302.5)
                     and record['engine_calls'] > 0 and record['order'].index('CASH:' + sid) < record['order'].index('ENGINE')
                     and not any(s == sid for _, s in record['risk'])
                     and not any(p['security_id'] == sid for p in result.state.pending),
                     'FUTURE_MNTA_EXACT_CASH_REMOVAL_BEFORE_UNCHANGED_V_LOOP')
            if record['cash'] or publication.session in {d for d, _ in self.terms}:
                save(self.out / ('actual-future-event-' + publication.session + '.json'), dict(record, passed=True, financial_source_changed=False))
            return result
        except BaseException as error:
            save(self.out / 'actual-future-event-refusal.json', dict(record, passed=False, error=str(error), financial_source_changed=False))
            raise
        finally:
            self.current = None
