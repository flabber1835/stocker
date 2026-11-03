"""Codec lifecycle over inert stand-ins; never financial/canonical execution."""
import ast
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from forecast_tests.test_close_admission import without_guard
import system_campaign_close_review_materialization as module


class FakeCodec:
    events = []
    wrong_hash = False
    raises = False
    def __init__(self, *args): self.objects = []
    def __enter__(self): self.events.append('entered');return self
    def __exit__(self, *args): self.events.append('restored')
    def load(self, path, **binding):
        self.events.append((path, binding))
        if self.raises: raise ValueError('INJECTED_LOAD_REFUSAL')
        value = SimpleNamespace(sha256=('0' if self.wrong_hash else '1')*64)
        self.objects[:] = [value]
        return value


def fixture(tmp_path):
    FakeCodec.events = [];FakeCodec.wrong_hash = False;FakeCodec.raises = False
    descriptor = dict(filename='1'*64+'.json',sha256='1'*64,resume_session='2023-10-31',
        predecessor_checkpoint_sha256='2'*64)
    checkpoint = dict(repairs=[descriptor]);report = {}
    return checkpoint,report,module.codec_factory(FakeCodec,tmp_path,checkpoint,report)


def test_materializes_exact_original_descriptor_inside_context_then_restores(tmp_path):
    checkpoint,report,codec = fixture(tmp_path);before = deepcopy(checkpoint)
    with codec({},[]):
        assert report == dict(input_sha256='1'*64,resume_session='2023-10-31',
            predecessor_checkpoint_sha256='2'*64,actual_nested_canonical_repair_loaded=True)
        assert FakeCodec.events == ['entered',(tmp_path/'book/repairs'/('1'*64+'.json'),
            dict(resume_session='2023-10-31',predecessor_checkpoint_sha256='2'*64))]
    assert FakeCodec.events[-1] == 'restored' and checkpoint == before


@pytest.mark.parametrize('fault', ['wrong_hash','raises'])
def test_load_failure_restores_dispatch_and_never_claims_materialization(tmp_path, fault):
    _,report,codec = fixture(tmp_path);setattr(FakeCodec,fault,True)
    with pytest.raises(ValueError):
        with codec({},[]): raise AssertionError('FAILED_LOAD_MUST_NOT_ENTER_BODY')
    assert FakeCodec.events[-1] == 'restored' and report == {}


def test_actual_descriptor_guard_removal_admits_wrong_binding(tmp_path):
    checkpoint,report,_ = fixture(tmp_path);FakeCodec.wrong_hash = True
    broken = without_guard(module,'codec_factory','CLOSE_REVIEW_MATERIALIZED_EXACT_CANONICAL_DESCRIPTOR')
    codec = broken(FakeCodec,tmp_path,checkpoint,report)
    with codec({},[]): assert report['input_sha256'] == '0'*64


def test_review_adapter_has_no_financial_transition_or_writer_entrypoint():
    tree = ast.parse(Path(module.__file__).read_bytes())
    calls = {ast.unparse(v.func) for v in ast.walk(tree) if isinstance(v,ast.Call)}
    assert not {'economic','backtest.main','runtime.advance','write_checkpoint'} & calls
    assert 'journal.read_checkpoint' in calls and 'checked' in calls
    assert 'self.load' in calls
