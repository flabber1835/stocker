"""Source-bound diagnostic entitlement deferral; never a financial settlement."""
from __future__ import annotations

import ast
from copy import deepcopy
import csv
from dataclasses import asdict, is_dataclass
from datetime import date
import gzip
import hashlib
import io
import json
import math
import os
from pathlib import Path
from typing import Any, Literal
import zipfile

from pydantic import BaseModel, ConfigDict, Field

from full_system_core import hosted
from system_campaign_discovery_context import TAINT, digest, encoded, material, need

SOURCE_SHA = '3ee01881e21a984c80cbdae1e2323fb42dc87f69dfe19f613b7141554e7ffeb2'
PARSER_SHA = '5381b3b41b14cfc2f9d9d6e97c35929c9acc3d237d6df359a9ad7e6d0e4df7ec'
LEDGER_SHA = 'c37a8656cc43a4807bf16e2fc6dcb97758cbe7271fc8d9a736ee526c9a9281f3'
ACTIONS_SHA = 'ec6f1d96c0beed8bf4baba45a55cc56a881f001d27456b9630471d69e2d46139'
ACTIONS_BYTES = 5322055
MISSING_POLICY = 'REQUIRE_REVIEWED_CHILD_OWNERSHIP'
REFUSAL = 'SPINOFF_CHILD_OWNERSHIP_REQUIRED: '


def original_number(raw):
    need(hashlib.sha256(raw).hexdigest() == PARSER_SHA, 'SPINOFF_DIAGNOSTIC_EXACT_ORIGINAL_NUMBER_PARSER')
    fn, = [n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef) and n.name == 'number']
    scope = dict(math=math)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<frozen-original-source-number-parser>', 'exec'), scope)
    return scope['number']


def native_actions(raw):
    need(len(raw) == ACTIONS_BYTES and hashlib.sha256(raw).hexdigest() == ACTIONS_SHA,
         'SPINOFF_DIAGNOSTIC_EXACT_NATIVE_ACTION_GZIP_MEMBER')
    rows, multiplicity, dividends = {}, {}, set()
    with io.TextIOWrapper(gzip.GzipFile(fileobj=io.BytesIO(raw)), encoding='utf-8') as stream:
        for row in csv.DictReader(stream):
            if row['action'].lower() == 'dividend':
                dividends.add((row['effective_session'], row['security_id']))
            if row['action'].lower() in ('spinoff', 'spinoffdividend'):
                source = hashlib.sha256(json.dumps(row, sort_keys=True).encode()).hexdigest()
                multiplicity[source] = multiplicity.get(source, 0) + 1
                rows[source] = row
    return dict(rows=rows, multiplicity=multiplicity, ordinary_dividends=dividends)


class UnresolvedClaim(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, frozen=True)
    schema_id: Literal['research.diagnostic-unvalued-spinoff-claim/1'] = 'research.diagnostic-unvalued-spinoff-claim/1'
    authority: Literal['DISCOVERY_ONLY_NOT_FINANCIAL_AUTHORITY'] = TAINT
    session: str
    parent_ticker: str
    parent_security_id: str
    child_ticker: str | None
    child_security_id: str | None
    source_row_id: str = Field(pattern=r'^[0-9a-f]{64}$')
    entitlement_status: Literal['UNRESOLVED_UNVALUED_NOT_SETTLED'] = 'UNRESOLVED_UNVALUED_NOT_SETTLED'
    parent_episode_facts: list[dict[str, Any]]
    roles: list[str]
    financial_authority: Literal[False] = False


def missing_contract(event):
    """Only the original source codec's absent contract is deferrable."""
    need(event.policy == MISSING_POLICY
         and event.child_shares_per_parent is None
         and event.child_price is None and event.cash_in_lieu_price is None,
         'SPINOFF_DIAGNOSTIC_ONLY_ABSENT_SOURCE_CONTRACT')
    need(isinstance(event.parent_security_id, str) and bool(event.parent_security_id)
         and event.child_security_id != event.parent_security_id,
         'SPINOFF_DIAGNOSTIC_VALID_PARENT_AND_DISTINCT_CHILD')
    need(isinstance(event.session, str) and date.fromisoformat(event.session).isoformat() == event.session
         and isinstance(event.parent_ticker, str) and bool(event.parent_ticker)
         and isinstance(event.source_row_id, str) and len(event.source_row_id) == 64
         and all(c in '0123456789abcdef' for c in event.source_row_id),
         'SPINOFF_DIAGNOSTIC_EXPLICIT_SOURCE_ROW_AND_SESSION')
    for value in (event.child_ticker, event.child_security_id):
        need(value is None or isinstance(value, str) and bool(value),
             'SPINOFF_DIAGNOSTIC_CHILD_SOURCE_IDENTITY_SHAPE')
    return event


def unresolved_identity_relation(event, prior):
    """Absent identities cannot establish economic duplication or uniqueness."""
    matching = [e for e in prior if (e.session, e.parent_security_id, e.child_security_id)
                == (event.session, event.parent_security_id, event.child_security_id)]
    if event.child_security_id is not None or not matching:
        return None
    if any(e.source_row_id == event.source_row_id for e in matching):
        return None
    missing_contract(event)
    for previous in matching:
        missing_contract(previous)
    return dict(status='RAW_SOURCE_LEGS_RELATIONSHIP_UNRESOLVED_NOT_ECONOMIC_CHILD_IDENTITIES',
        session=event.session, parent_security_id=event.parent_security_id,
        source_row_ids=[e.source_row_id for e in matching] + [event.source_row_id],
        no_deduplication_combination_or_entitlement_count=True)


def preflight_tree(raw):
    """Retain canonical validation, stop before mutation, collect absent terms."""
    need(hashlib.sha256(raw).hexdigest() == SOURCE_SHA,
         'SPINOFF_DIAGNOSTIC_EXACT_FROZEN_PREFLIGHT_SOURCE')
    fn, = [n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef)
           and n.name == 'apply_supported_entitlements']
    boundary, = [i for i, n in enumerate(fn.body) if isinstance(n, ast.Assign)
                 and ast.unparse(n.targets[0]) == 'audit']
    fn.body = fn.body[:boundary]
    duplicate, = [n for n in ast.walk(fn) if isinstance(n, ast.If)
                 and ast.unparse(n.test) == 'key in seen']
    original_duplicate_refusal = deepcopy(duplicate.body)
    duplicate.body = ast.parse('relation = unresolved_identity_relation(event, unresolved)\nif relation is None:\n    pass\nindeterminate_identities.append(relation)').body
    duplicate.body[1].body = original_duplicate_refusal
    sites = []
    for node in ast.walk(fn):
        if isinstance(node, ast.If) and any(isinstance(n, ast.Constant)
            and n.value == REFUSAL for n in ast.walk(node)):
            sites.append(node)
    branch, = sites
    expected = ast.parse('event.policy != LIQUIDATE_CHILD_AT_OPEN or not event.child_security_id or not event.child_ticker or event.child_security_id == event.parent_security_id', mode='eval').body
    need(ast.dump(branch.test) == ast.dump(expected),
         'SPINOFF_DIAGNOSTIC_ONLY_CANONICAL_MISSING_CONTRACT_BRANCH')
    branch.body = ast.parse('unresolved.append(missing_contract(event))\ncontinue').body
    fn.body.insert(1, ast.parse('unresolved = []').body[0])
    fn.body.insert(2, ast.parse('indeterminate_identities = []').body[0])
    fn.body.extend(ast.parse('return dict(plans=plans, unresolved=unresolved, indeterminate_identities=indeterminate_identities)').body)
    return ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))


def compile_preflight(raw, namespace):
    scope = dict(namespace, missing_contract=missing_contract,
                 unresolved_identity_relation=unresolved_identity_relation)
    exec(compile(preflight_tree(raw), '<frozen-diagnostic-spinoff-preflight>', 'exec'), scope)
    return scope['apply_supported_entitlements']


def payload(value):
    if hasattr(value, 'to_dict'):
        return value.to_dict()
    if is_dataclass(value):
        return asdict(value)
    raise ValueError('SPINOFF_DIAGNOSTIC_EXPLICIT_SERIALIZABLE_BOOK_REQUIRED')


def snapshot(state, ledger):
    return digest(dict(state=payload(state), ledger=payload(ledger)))


def write_once(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = encoded(value) + b'\n'
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return dict(filename=path.name, bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())


class SpinoffDeferral:
    def __init__(self, context, *, bindings=None, source_raw=None, expected_first=None,
                 native_source=None, number=None, ledger_class=None):
        self.context = context
        self.bindings = bindings
        self.source_raw = source_raw
        self.expected_first = expected_first
        self.first_seen = False
        self.pending = []
        self.uses = 0
        self.original = None
        self.native_source, self.number, self.ledger_class = native_source, number, ledger_class
        self.original_accrue = None
        self.proxy_blocks = {}

    def __enter__(self):
        hosted()
        if self.bindings is None:
            from sentinel.core import spinoffs
            self.bindings = spinoffs
        raw = self.source_raw if self.source_raw is not None else Path(self.bindings.__file__).read_bytes()
        self.preflight = compile_preflight(raw, vars(self.bindings))
        if self.native_source is None:
            with zipfile.ZipFile('/frozen/archive/corpus.zip') as archive:
                self.native_source = native_actions(archive.read('actions.csv.gz'))
        if self.number is None:
            self.number = original_number(Path('/variant/research/bounded_20y/run.py').read_bytes())
        if self.ledger_class is None:
            from stock_strategy_shared.wealth_core import ledger
            need(hashlib.sha256(Path(ledger.__file__).read_bytes()).hexdigest() == LEDGER_SHA,
                 'SPINOFF_DIAGNOSTIC_EXACT_ORIGINAL_ACCRUAL_SOURCE')
            self.ledger_class = ledger.Ledger
        self.original = self.bindings.apply_supported_entitlements
        self.original_accrue = self.ledger_class.accrue_dividend
        self.bindings.apply_supported_entitlements = self.apply
        def accrue(owner, **kwargs):
            return self.accrue(owner, **kwargs)
        self.ledger_class.accrue_dividend = accrue
        return self

    def __exit__(self, *args):
        if self.original_accrue is not None:
            self.ledger_class.accrue_dividend = self.original_accrue
            self.original_accrue = None
        if self.original is not None:
            self.bindings.apply_supported_entitlements = self.original
            self.original = None

    def native_evidence(self, state, events, bars):
        evidence = []
        for event in events:
            row = self.native_source['rows'].get(event.source_row_id)
            need(row is not None and row['effective_session'] == event.session
                 and row['ticker'] == event.parent_ticker and row['security_id'] == event.parent_security_id
                 and row['vendor_value'] == event.value_evidence
                 and event.child_security_id is None and event.child_ticker is None
                 and self.native_source['multiplicity'].get(event.source_row_id) == 1,
                 'SPINOFF_DIAGNOSTIC_EACH_UNKNOWN_EXACT_NATIVE_SOURCE_ROW')
            evidence.append(dict(source_row_id=event.source_row_id, native_row=deepcopy(row)))
        proxies = []
        keys = {(event.session, event.parent_security_id) for event in events}
        for day, sid in sorted(keys):
            source = [r for r in evidence if r['native_row']['effective_session'] == day
                      and r['native_row']['security_id'] == sid
                      and r['native_row']['action'].lower() == 'spinoffdividend']
            current = [b for b in bars if b.security_id == sid]
            need(len(current) <= 1, 'SPINOFF_DIAGNOSTIC_UNAMBIGUOUS_PROXY_PARENT_BAR')
            dividend = getattr(current[0], 'dividend_per_share', 0.0) if current else 0.0
            if not source:
                need(not dividend or (day, sid) in self.native_source['ordinary_dividends'],
                     'SPINOFF_DIAGNOSTIC_NO_UNEXPLAINED_PARENT_DIVIDEND')
                continue
            need(len(source) == 1 and len(current) == 1
                 and (day, sid) not in self.native_source['ordinary_dividends'],
                 'SPINOFF_DIAGNOSTIC_NO_SEPARATE_COMBINED_OR_AMBIGUOUS_PROXY_DIVIDEND')
            raw_value = source[0]['native_row']['vendor_value']
            normalized = self.number(raw_value)
            need(normalized is not None and normalized > 0 and dividend == normalized,
                 'SPINOFF_DIAGNOSTIC_EXACT_ORIGINAL_BINARY64_SOURCE_PROXY_EQUALITY')
            expected = [dict(shares=ep.current_shares, ticker=ep.ticker)
                        for _, ep in sorted(state.episodes.items()) if ep.security_id == sid and ep.current_shares > 0]
            block = dict(session=day, security_id=sid, source_row_id=source[0]['source_row_id'],
                source_raw_value=raw_value, original_parser_binary64_value=normalized,
                status='UNVALUED_RAW_CASH_PROXY_NOT_RECEIVABLE_OR_SETTLED_CASH',
                expected_accruals=expected, actual_deferred_accruals=[])
            self.proxy_blocks[day, sid] = block
            proxies.append(block)
        return evidence, proxies

    def accrue(self, ledger, **kwargs):
        block = self.proxy_blocks.get((kwargs['session'], kwargs['security_id']))
        if block is None:
            return self.original_accrue(ledger, **kwargs)
        before = digest(payload(ledger))
        expected = dict(shares=kwargs['shares'], ticker=kwargs['ticker'])
        need(kwargs['per_share'] == block['original_parser_binary64_value']
             and expected in block['expected_accruals'],
             'SPINOFF_DIAGNOSTIC_ONLY_EXACT_SOURCE_PROXY_EPISODE_ACCRUAL')
        block['expected_accruals'].remove(expected)
        block['actual_deferred_accruals'].append(expected)
        self.context.emit('SPINOFF_CASH_PROXY_ACCRUAL_DEFERRED', kwargs['security_id'], bypass=True,
            source_row_id=block['source_row_id'], source_raw_value=block['source_raw_value'],
            parent_episode_shares=kwargs['shares'],
            convention='UNVALUED_SOURCE_PROXY_NO_DIVIDEND_RECEIVABLE_OR_CASH_SETTLEMENT')
        need(digest(payload(ledger)) == before, 'SPINOFF_DIAGNOSTIC_PROXY_ACCRUAL_NO_LEDGER_MUTATION')
        return None

    def refusal_probe(self, state, distributions, kwargs):
        copied_state, copied_events, copied_kwargs = deepcopy((state, distributions, kwargs))
        before = snapshot(copied_state, copied_kwargs['ledger'])
        try:
            self.original(copied_state, copied_events, **copied_kwargs)
        except self.bindings.SpinoffTermsRequired as exc:
            need(str(exc).startswith(REFUSAL), 'SPINOFF_DIAGNOSTIC_ONLY_ORIGINAL_MISSING_CHILD_REFUSAL')
            refusal = str(exc)
        else:
            raise ValueError('SPINOFF_DIAGNOSTIC_ORIGINAL_MISSING_CHILD_REFUSAL_REQUIRED')
        need(snapshot(copied_state, copied_kwargs['ledger']) == before,
             'SPINOFF_DIAGNOSTIC_ORIGINAL_REFUSAL_ATOMIC')
        return refusal

    def apply(self, state, distributions, **kwargs):
        need(self.context.current is not None, 'SPINOFF_DIAGNOSTIC_CURRENT_TRANSITION_REQUIRED')
        events = tuple(distributions)
        before = snapshot(state, kwargs['ledger'])
        checked = self.preflight(state, events, **kwargs)
        input_before = digest(dict(events=events, bars=kwargs['bars'], config=kwargs['config']))
        need(snapshot(state, kwargs['ledger']) == before,
             'SPINOFF_DIAGNOSTIC_PREFLIGHT_NO_MUTATION')
        if not checked['unresolved']:
            return self.original(state, events, **kwargs)
        run, published = self.context.current
        need(tuple(published.spinoff_distributions) == events
             and all(e.session == published.session for e in events),
             'SPINOFF_DIAGNOSTIC_EXACT_CURRENT_PUBLICATION_EVENT_SET')
        original_refusal = self.refusal_probe(state, events, kwargs)
        for event in checked['unresolved']:
            refusal = self.refusal_probe(state, (event,), kwargs)
            need(event.source_row_id in refusal,
                 'SPINOFF_DIAGNOSTIC_EACH_UNKNOWN_HAS_ORIGINAL_SOURCE_REFUSAL')
        if not self.first_seen and self.expected_first is not None:
            need(any(all(getattr(e, key) == value for key, value in self.expected_first.items())
                     for e in checked['unresolved']),
                 'SPINOFF_DIAGNOSTIC_FIRST_EXPECTED_OWN_ORIGINAL_REFUSAL')
        self.first_seen = True
        native, proxies = self.native_evidence(state, checked['unresolved'], kwargs['bars'])
        unknown = {e.source_row_id for e in checked['unresolved']}
        known = {p['event'].source_row_id for p in checked['plans']}
        legs = []
        for event in events:
            if event.source_row_id not in unknown | known:
                continue
            parents = [material(payload(ep)) for _, ep in sorted(state.episodes.items())
                       if ep.security_id == event.parent_security_id and ep.current_shares > 0]
            need(parents, 'SPINOFF_DIAGNOSTIC_HELD_LEG_EPISODE_FACTS_REQUIRED')
            prior = run.state
            roles = ['HELD']
            if any(p['security_id'] == event.parent_security_id for p in prior.pending):
                roles.append('PENDING')
            if event.parent_security_id in (prior.median5 or {}).get('selected', ()):
                roles.append('LEADERSHIP')
            claim = None
            if event.source_row_id in unknown:
                claim = UnresolvedClaim(session=event.session, parent_ticker=event.parent_ticker,
                    parent_security_id=event.parent_security_id, child_ticker=event.child_ticker,
                    child_security_id=event.child_security_id, source_row_id=event.source_row_id,
                    parent_episode_facts=parents, roles=roles).model_dump()
            legs.append(dict(source_term=material(event), parent_episode_facts=parents,
                roles=roles, unresolved_claim=claim,
                disposition='UNRESOLVED_UNVALUED_NOT_SETTLED' if claim else 'SUPPORTED_LEG_DEFERRED_WITH_COMPLETE_SET'))
        need(len(legs) == len(unknown) + len(known), 'SPINOFF_DIAGNOSTIC_EVERY_HELD_LEG_RECORDED')
        need(snapshot(state, kwargs['ledger']) == before
             and digest(dict(events=events, bars=kwargs['bars'], config=kwargs['config'])) == input_before,
             'SPINOFF_DIAGNOSTIC_NO_SHARES_CASH_LEDGER_SLOTS_BASIS_OR_INPUT_CHANGE')
        proof = dict(schema='research.diagnostic-spinoff-deferral-use/1', authority=TAINT,
            session=published.session, prior_state_sha256=run.state.state_hash,
            input_sha256=run.input_sha256, publication_sha256=digest(published),
            frozen_preflight_source_sha256=SOURCE_SHA, original_refusal=original_refusal,
            book_and_ledger_before_sha256=before, book_and_ledger_after_sha256=snapshot(state, kwargs['ledger']),
            supplied_source_events=material(events), affected_held_legs=legs,
            indeterminate_child_identity_relations=checked['indeterminate_identities'],
            native_source_legs=native, cash_proxy_obligations=proxies,
            native_actions_gzip_sha256=ACTIONS_SHA, original_number_parser_sha256=PARSER_SHA,
            all_supplied_held_legs_deferred=True, partial_application=False,
            shares_cash_ledger_slots_and_basis_unchanged=True, financial_authority=False,
            account_performance_computed=False, production_contacted=False)
        self.context.emit('SPINOFF_UNRESOLVED_ENTITLEMENT_DEFERRED', bypass=True,
            entitlement_proof=proof, convention='COMPLETE_HELD_SET_UNVALUED_NO_SETTLEMENT_NO_PARTIAL_APPLICATION')
        proof['deferral_event_commitment'] = self.context.commitment()
        self.pending.append(proof)
        return ()

    def after(self, prior, next_run):
        if not self.pending:
            return
        before = prior.state.to_dict()
        after = next_run.state.to_dict()
        old_events = before['ledger']['events']
        events = after['ledger']['events']
        need(events[:len(old_events)] == old_events,
             'SPINOFF_DIAGNOSTIC_CANONICAL_LEDGER_PREFIX_UNCHANGED')
        for proof in self.pending:
            need(prior.state.state_hash == proof['prior_state_sha256']
                 and next_run.state.last_processed_session == proof['session'],
                 'SPINOFF_DIAGNOSTIC_ACTUAL_TRANSITION_ADJACENCY')
            source_ids = {e['source_row_id'] for e in proof['supplied_source_events']}
            for proxy in proof['cash_proxy_obligations']:
                need(not proxy['expected_accruals'] and proxy['actual_deferred_accruals'],
                     'SPINOFF_DIAGNOSTIC_EVERY_SOURCE_PROXY_ACCRUAL_ACTUALLY_DEFERRED')
                need(not any(e.get('security_id') == proxy['security_id']
                             and (e.get('event_type') == 'DIVIDEND_ACCRUED'
                                  or e.get('event_type') == 'DIVIDEND_PAID'
                                  and (e.get('detail') or {}).get('accrued_session') == proxy['session'])
                             for e in events[len(old_events):])
                     and not any(r.get('security_id') == proxy['security_id']
                                 and r.get('accrued_session') == proxy['session']
                                 for r in after['ledger'].get('receivables', ())),
                     'SPINOFF_DIAGNOSTIC_NO_CURRENT_PROXY_ACCRUAL_CASH_OR_RECEIVABLE')
            need(not any(e.get('event_type') in ('SPINOFF_RECEIPT', 'SPINOFF_LIQUIDATION')
                         or (e.get('detail') or {}).get('source_row_id') in source_ids
                         for e in events[len(old_events):]),
                 'SPINOFF_DIAGNOSTIC_NO_RECEIPT_LIQUIDATION_OR_SOURCE_SETTLEMENT')
            for episode in after['wealth_core']['episodes'].values():
                need(not any(lot.get('kind') == 'SPINOFF_CHILD_LIQUIDATION'
                             and lot.get('source_row_id') in source_ids
                             for lot in episode.get('source_lots', ())),
                     'SPINOFF_DIAGNOSTIC_NO_CHILD_SOURCE_LOT_OR_BASIS_SETTLEMENT')
            proof.update(status='ACTUAL_CANONICAL_DIAGNOSTIC_SPINOFF_DEFERRAL_QUALIFIED',
                next_state_sha256=next_run.state.state_hash,
                no_spinoff_settlement_in_actual_canonical_transition=True)
            name = f'{self.uses:08d}-{proof["session"]}-{digest(proof)}.json'
            write_once(self.context.output/'spinoff-deferral-qualifications'/name, proof)
            self.uses += 1
        self.pending.clear()
        self.proxy_blocks.clear()


def context_class(base, *, expected_first=None):
    """Factory accepted by the shared exact suffix engine."""
    class SpinoffContext(base):
        def __enter__(self):
            super().__enter__()
            try:
                self.spinoff_deferral = SpinoffDeferral(self, expected_first=expected_first)
                self.spinoff_deferral.__enter__()
                return self
            except BaseException:
                super().__exit__(None, None, None)
                raise

        def advance(self, run, published):
            result = super().advance(run, published)
            self.spinoff_deferral.after(run, result)
            return result

        def __exit__(self, *args):
            try:
                self.spinoff_deferral.__exit__(*args)
            finally:
                super().__exit__(*args)

    return SpinoffContext
