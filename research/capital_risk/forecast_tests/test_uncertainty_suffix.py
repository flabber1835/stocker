"""Synthetic semantic-basis and retained-descriptor regressions only."""
import hashlib
import json
import sys
from types import ModuleType

import pytest

from system_campaign_uncertainty_basis import basis


def corpus(tmp_path, predecessor):
    root=tmp_path;folder=root/'book/repairs';folder.mkdir(parents=True)
    docs=[dict(schema='terminal-repair/1',source_evidence=[],suppress=[],add=[]),
          dict(schema='research.leadership-uncertainty-input/1',predecessor_checkpoint_sha256=predecessor,
               source_evidence=[dict(reference='synthetic:model',sha256='a'*64)])]
    descriptors=[]
    for doc in docs:
        raw=json.dumps(doc).encode();digest=hashlib.sha256(raw).hexdigest()
        (folder/(digest+'.json')).write_bytes(raw)
        descriptors.append(dict(filename=digest+'.json',sha256=digest))
    return root,dict(base={},repairs=descriptors)


def stub_basis(monkeypatch):
    import system_campaign_uncertainty_basis as module
    monkeypatch.setattr(module,'validate_input_commitment',lambda root,cp:'model')
    def ordinary(root,cp):
        assert len(cp['repairs'])==1
        return 'f'*64,dict(frozen_source='synthetic',declared_fact_compilers={})
    monkeypatch.setattr(module,'ordinary_basis',ordinary)


def test_common_basis_normalizes_only_own_predecessor(monkeypatch,tmp_path):
    stub_basis(monkeypatch)
    a,cp_a=corpus(tmp_path/'a','a'*64);b,cp_b=corpus(tmp_path/'b','b'*64)
    assert basis(a,cp_a)==basis(b,cp_b)
    assert 'predecessor_checkpoint_sha256' not in basis(a,cp_a)[1]['model_semantics']


def test_undeclared_repair_schema_cannot_be_silently_filtered(monkeypatch,tmp_path):
    stub_basis(monkeypatch);root,cp=corpus(tmp_path,'a'*64)
    raw=json.dumps(dict(schema='undeclared:other-model')).encode();digest=hashlib.sha256(raw).hexdigest()
    (root/'book/repairs'/(digest+'.json')).write_bytes(raw)
    cp['repairs'].append(dict(filename=digest+'.json',sha256=digest))
    with pytest.raises(ValueError,match='UNDECLARED_SCHEMA'):basis(root,cp)


def test_retained_alder_uses_original_admission_cursor_after_event(monkeypatch,tmp_path):
    import system_campaign_uncertainty_support as module
    packages={n:ModuleType(n) for n in ('research','research.pooled_vacancy_funding','research.pooled_vacancy_funding.repair')}
    for name,p in packages.items():p.__path__=[];monkeypatch.setitem(sys.modules,name,p)
    calls=[]
    def parser(path,**kwargs):
        assert kwargs['resume_session']=='2019-09-30'
        assert kwargs['predecessor_checkpoint_sha256']=='a'*64
        calls.append(kwargs);return 'parsed-retained-term'
    packages['research.pooled_vacancy_funding.repair'].load_repair=parser
    old=tmp_path/'old';out=tmp_path/'out';(old/'book/repairs').mkdir(parents=True);out.mkdir()
    value=dict(predecessor_checkpoint_sha256='a'*64,source_evidence=[{'reference':'research:system-optimization-002/alder-terminal-catalog/1'}])
    raw=json.dumps(value).encode();digest=hashlib.sha256(raw).hexdigest();(old/'book/repairs'/(digest+'.json')).write_bytes(raw)
    class Context:
        def __init__(self,path):pass
        def hydrate(self,path):path.write_bytes(b'synthetic')
    monkeypatch.setattr(module,'FactualInputs',Context);monkeypatch.setattr(module,'DistributionFacts',Context);monkeypatch.setattr(module,'AlderDateV2',Context)
    monkeypatch.setattr(module,'retained_components',lambda *args:None)
    for name in ('hydrated-factual-catalog.json','hydrated-distribution-catalog.json','hydrated-alder-unresolved-date.json'):
        (out/name).write_bytes(b'synthetic')
    cp=dict(source_cursor='2019-10-31',repairs=[dict(filename=digest+'.json',sha256=digest,resume_session='2019-09-30')])
    *_,loaded=module.retained(cp,old,out)
    assert loaded=='parsed-retained-term' and len(calls)==1
