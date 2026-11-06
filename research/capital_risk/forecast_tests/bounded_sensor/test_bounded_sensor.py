"""Synthetic input/binding falsifiers only; canonical financial imports refused."""
import ast
from copy import deepcopy
from dataclasses import dataclass, replace
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest


class Fence:
    def find_spec(self, fullname, path=None, target=None):
        if fullname.startswith(('research.pooled_', 'stock_strategy_shared', 'sentinel', 'numpy', 'pandas')):
            raise ImportError('DATA_ONLY_NO_LOCAL_CANONICAL_RUNTIME:' + fullname)


sys.meta_path.insert(0, Fence())
sys.path.insert(0, str(Path(__file__).parent))
import system_campaign_bounded_sensor_input as data
import system_campaign_bounded_sensor_binding as binding


@dataclass(frozen=True)
class Native:
    session: str = '2019-11-12'
    security_id: str = '471435039050105714'
    cash_per_share: float | None = None
    kind: str = 'CASH_MERGER'
    reference: str = 'synthetic incomplete frozen term'

    def completeness(self, quantity):
        return self.cash_per_share is not None, 'SYNTHETIC'


@dataclass(frozen=True)
class Packet:
    day: str
    terminal: tuple


@dataclass(frozen=True)
class Published:
    session: str
    terminal_events: tuple
    bars: tuple


def event():
    from dataclasses import asdict
    return dict(ticker='DOVA', security_id=Native().security_id, native_session='2019-11-12',
                effective_session='2019-11-12', prior_session='2019-11-11',
                native_term_sha256=data.digest(asdict(Native())), currency='USD',
                upfront_cash_per_share='27.50', right_lower_per_share='0.00', right_upper_per_share='1.50',
                right_kind='NONTRANSFERABLE_CONTINGENT_VALUE_RIGHT', ownership_scope='UNOWNED_UNORDERED_SENSOR_ONLY',
                treatment='EVERY_REACHABLE_CANONICAL_DECISION_MUST_MATCH',
                price_or_probability_selected=False, cash_settlement_authorized=False, historical_causality='UNVERIFIED')


def evidence():
    return [dict(reference='synthetic:' + str(i), description='synthetic source commitment', sha256=str(i) * 64)
            for i in range(4)]


def document():
    return dict(schema=data.SCHEMA, predecessor_checkpoint_sha256='a' * 64, event=event(), source_evidence=evidence())


def parse(tmp_path, doc=None, **overrides):
    p = tmp_path / 'model.json'
    p.write_bytes(json.dumps(document() if doc is None else doc).encode())
    return data.parse(p, **dict(dict(resume_session='2019-10-31', predecessor_checkpoint_sha256='a' * 64,
                      expected_event=event(), expected_evidence=evidence()), **overrides))


def prior(selected=True):
    sid = Native().security_id
    return SimpleNamespace(wealth_core=dict(episodes={}), pending=[], last_processed_session='2019-11-11',
        median5=dict(selected=[sid] if selected else []), feed=dict(series={sid:dict(signal_basis_anchor=['2019-11-11', 10., 20.])}))


def source():
    return dict(session='2019-11-12', security_id=Native().security_id, source_quote_present=False, split_ratio='1')


def test_typed_distinct_input_and_same_day_packet_untouched(tmp_path):
    obj = parse(tmp_path)
    assert obj.earliest_affected_session == '2019-11-12'
    codec = data.InputCodec(event(), evidence(), Native())
    obj = codec.load(tmp_path / 'model.json', resume_session='2019-10-31', predecessor_checkpoint_sha256='a' * 64)
    packet = Packet('2019-11-12', (Native(),))
    assert codec.apply(packet, obj) is packet
    assert packet.terminal[0].cash_per_share is None
    assert obj.event.upfront_cash_per_share == '27.50' and obj.event.right_upper_per_share == '1.50'


@pytest.mark.parametrize('change', ['donor_schema', 'other_sid', 'cash29', 'right_point', 'right_negative', 'native_day',
    'prior_day', 'evidence', 'probability', 'cash_authority', 'bool_authority', 'causality', 'cash_field', 'predecessor'])
def test_altered_model_refuses(tmp_path, change):
    doc = document()
    if change == 'donor_schema': doc['schema'] = 'research.zogenix-leadership-uncertainty-input/1'
    elif change == 'other_sid': doc['event']['security_id'] = '941065113449292610'
    elif change == 'cash29': doc['event']['upfront_cash_per_share'] = '29.00'
    elif change == 'right_point': doc['event']['right_upper_per_share'] = '0.00'
    elif change == 'right_negative': doc['event']['right_lower_per_share'] = '-1.50'
    elif change == 'native_day': doc['event']['native_session'] = '2019-11-13'
    elif change == 'prior_day': doc['event']['prior_session'] = '2019-11-12'
    elif change == 'evidence': doc['source_evidence'][0]['sha256'] = 'f' * 64
    elif change == 'probability': doc['event']['price_or_probability_selected'] = True
    elif change == 'cash_authority': doc['event']['cash_settlement_authorized'] = True
    elif change == 'bool_authority': doc['event']['cash_settlement_authorized'] = 0
    elif change == 'causality': doc['event']['historical_causality'] = 'VERIFIED'
    elif change == 'cash_field': doc['cash_per_share'] = 29.00
    else: doc['predecessor_checkpoint_sha256'] = 'b' * 64
    with pytest.raises(ValueError): parse(tmp_path, doc)


@pytest.mark.parametrize('cursor', ['2019-11-12', '2019-11-13', '2019-10-32', '2019-1-01'])
def test_consumed_or_noncanonical_cursor_refuses(tmp_path, cursor):
    with pytest.raises(ValueError): parse(tmp_path, resume_session=cursor)


def test_foreign_object_and_wrong_native_packet_refuse(tmp_path):
    obj = parse(tmp_path)
    codec = data.InputCodec(event(), evidence(), Native())
    packet = Packet('2019-11-12', (Native(),))
    with pytest.raises(ValueError, match='ONLY_EXACT'): codec.apply(packet, obj)
    codec.objects.append(obj)
    with pytest.raises(ValueError, match='EXACT_NATIVE'): codec.apply(replace(packet, terminal=()), obj)
    with pytest.raises(ValueError, match='EXACT_INCOMPLETE_NATIVE'):
        data.InputCodec(event(), evidence(), Native(cash_per_share=27.50))


def test_independent_signal_basis_uses_full_range_and_no_cash_input():
    p = Published('2019-11-12', (Native(),), ())
    actual, interval = binding.basis(prior(), p, event(), source(), Native())
    assert interval == actual['signal_consideration_interval'] == [55., 58.]
    assert actual['selected'] is True and p.terminal_events[0].cash_per_share is None
    actual, interval = binding.basis(prior(False), p, event(), source(), Native())
    assert interval is None and actual['selected'] is False
    assert 'signal_consideration_interval' not in actual


@pytest.mark.parametrize('change', ['held', 'ordered', 'clock', 'term', 'quote', 'split', 'anchor'])
def test_event_binding_requires_actual_context(change):
    before, p, s = prior(), Published('2019-11-12', (Native(),), ()), source()
    if change == 'held': before.wealth_core['episodes']['0'] = dict(security_id=Native().security_id)
    elif change == 'ordered': before.pending.append(dict(security_id=Native().security_id))
    elif change == 'clock': before.last_processed_session = '2019-11-08'
    elif change == 'term': p = replace(p, terminal_events=(replace(Native(), cash_per_share=29.),))
    elif change == 'quote': s['source_quote_present'] = True
    elif change == 'split': s['split_ratio'] = '2'
    else: before.feed['series'][Native().security_id]['signal_basis_anchor'][0] = '2019-11-08'
    with pytest.raises(ValueError): binding.basis(before, p, event(), s, Native())


@pytest.mark.parametrize('label', ['EXACT_OWN_PREDECESSOR', 'EXACT_QUALIFIED_EVENT'])
def test_removing_parser_guard_really_admits_bad_input(tmp_path, label):
    doc = document()
    if label == 'EXACT_OWN_PREDECESSOR': doc['predecessor_checkpoint_sha256'] = 'b' * 64
    else: doc['event']['upfront_cash_per_share'] = '29.00'
    with pytest.raises(ValueError, match=label): parse(tmp_path, doc)
    fn, = [n for n in ast.parse(Path(data.__file__).read_bytes()).body if isinstance(n, ast.FunctionDef) and n.name == 'parse']
    guard, = [n for n in fn.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
              and any(isinstance(v, ast.Constant) and v.value == label for v in n.value.args)]
    fn.body.remove(guard)
    scope = dict(vars(data))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])), '<removed-parser-guard>', 'exec'), scope)
    obj = scope['parse'](tmp_path / 'model.json', resume_session='2019-10-31', predecessor_checkpoint_sha256='a' * 64,
                        expected_event=event(), expected_evidence=evidence())
    assert obj is not None


@pytest.mark.parametrize('prefix', ['research.pooled_', 'stock_strategy_shared', 'sentinel', 'numpy', 'pandas'])
def test_import_fence(prefix):
    with pytest.raises(ImportError): Fence().find_spec(prefix)
