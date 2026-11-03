"""Only synthetic schema, predecessor and packet identity tests."""
import inspect
import json
from types import SimpleNamespace
import textwrap

import pytest

from system_campaign_uncertainty_input import InputCodec, parse, require_no_financial_position


def document():
    evidence = [dict(reference='synthetic:' + str(n), description='Synthetic commitment', sha256=str(n) * 64)
                for n in range(4)]
    return dict(schema='research.leadership-uncertainty-input/1', predecessor_checkpoint_sha256='a' * 64,
                session='2019-10-22', security_id='941065113449292610', sensor_only=True,
                require_unowned_and_unordered=True,
                consideration_range='18<=cash_plus_nontransferable_right<=20',
                treatment='ALL_EXECUTED_COMPARISONS_MUST_BE_INTERVAL_INVARIANT', source_evidence=evidence)


def load(tmp_path, doc=None, **kwargs):
    doc = doc or document()
    path = tmp_path / 'input.json'
    path.write_text(json.dumps(doc))
    return parse(path, **dict(resume_session='2019-09-30', predecessor_checkpoint_sha256='a' * 64,
                             expected_evidence=document()['source_evidence'], **kwargs))


def test_exact_own_successor_is_distinct_from_empty_cash_repair(tmp_path):
    obj = load(tmp_path)
    assert obj.earliest_affected_session == '2019-10-22' and len(obj.sha256) == 64
    assert obj._resume_session == '2019-09-30'
    assert not hasattr(obj, 'add') and not hasattr(obj, 'suppress')


@pytest.mark.parametrize('change', [dict(predecessor_checkpoint_sha256='b' * 64),
                                   dict(sensor_only=False), dict(sensor_only=1),
                                   dict(require_unowned_and_unordered=False),
                                   dict(security_id='different'), dict(session='2019-10-23'),
                                   dict(add=[]), dict(suppress=[]), dict(cash_per_share=18.)])
def test_wrong_predecessor_scope_or_fabricated_cash_refuses(tmp_path, change):
    with pytest.raises(ValueError):
        load(tmp_path, {**document(), **change})


def test_consumed_session_and_wrong_source_refuse(tmp_path):
    path = tmp_path / 'input.json'
    doc = document();path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match='UNCONSUMED'):
        parse(path, resume_session='2019-10-22', predecessor_checkpoint_sha256='a' * 64,
              expected_evidence=doc['source_evidence'])
    with pytest.raises(ValueError, match='IMPLEMENTATION_AND_GATE'):
        parse(path, resume_session='2019-09-30', predecessor_checkpoint_sha256='a' * 64,
              expected_evidence=[])


def test_codec_returns_exact_same_packet_only_for_admitted_typed_object(tmp_path):
    doc = document();path = tmp_path / 'input.json';path.write_text(json.dumps(doc))
    codec = InputCodec(doc['source_evidence'])
    obj = codec.load(path, resume_session='2019-09-30', predecessor_checkpoint_sha256='a' * 64)
    packet = object()
    assert codec.apply(packet, obj) is packet
    other = load(tmp_path)
    with pytest.raises(ValueError, match='ONLY_ADMITTED'):
        codec.apply(packet, other)


def test_ordinary_empty_cash_repair_still_reaches_original_parser(tmp_path):
    codec = InputCodec(document()['source_evidence'])
    calls = []
    def original(*args, **kwargs):
        calls.append((args, kwargs))
        raise ValueError('empty terminal repair')
    codec.original_load = original
    path = tmp_path / 'empty.json'
    path.write_text(json.dumps(dict(schema='terminal-repair/1', suppress=[], add=[])))
    with pytest.raises(ValueError, match='empty terminal repair'):
        codec.load(path, resume_session='2019-09-30', predecessor_checkpoint_sha256='a' * 64)
    assert len(calls) == 1


def test_holding_or_pending_order_cannot_use_notional_treatment():
    empty = SimpleNamespace(wealth_core={'episodes': {}}, pending=[])
    require_no_financial_position(empty)
    for prior in (SimpleNamespace(wealth_core={'episodes': {'0': {'security_id': '941065113449292610'}}}, pending=[]),
                  SimpleNamespace(wealth_core={'episodes': {}}, pending=[{'security_id': '941065113449292610'}])):
        with pytest.raises(ValueError, match='CVR_MUST_NOT_BE_'):
            require_no_financial_position(prior)


def test_actual_unowned_guard_removal_falsifier():
    raw = inspect.getsource(require_no_financial_position)
    broken = raw.replace("and v['security_id'] != sid for v in prior.wealth_core['episodes'].values()",
                         "for v in prior.wealth_core['episodes'].values()")
    assert raw != broken
    namespace = {}
    exec(textwrap.dedent(broken), require_no_financial_position.__globals__, namespace)
    owned = SimpleNamespace(wealth_core={'episodes': {'0': {'security_id': '941065113449292610'}}}, pending=[])
    with pytest.raises(ValueError, match='MUST_NOT_BE_OWNED'):
        require_no_financial_position(owned)
    namespace['require_no_financial_position'](owned)
