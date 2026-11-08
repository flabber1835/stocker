"""Exact retained source staging and single-catalog normalization; synthetic IO."""
import ast
from copy import deepcopy
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import urllib.request

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import system_campaign_financial_future as f
import system_campaign_sprint_facts as sprint


def test_sprint_phase_keeps_exact_literal_terms_metadata_and_witnesses():
    codec, filename, terms=f.selected('P07',cursor='2020-02-28');term,=terms
    original=json.loads((f.HERE/filename).read_bytes())
    assert term['added']==original['added'] and term['added']['exchange_ratio']=='0.10256'
    assert term['added']['cash_per_share'] is None
    assert term['identity_witness']==original['source_identity_witness']
    assert term['identity_witness']['security_type_eligible']=='0'
    assert term['identity_witness']['issuer_id']=='SEC_UNKNOWN:957008674074369745'
    assert term['delivered_identity_witness']==original['delivered_identity_witness']
    assert codec.catalog==original
    assert f.suppressions(dict(source_cursor='2020-02-28'),terms)==[dict(
        session='2020-03-31',security_id=sprint.SID,term_sha256=original['native_term_sha256'])]


def test_following_phase_composes_all_eight_original_future_cash_literals_without_reapplying_sprint():
    codec, name, terms=f.selected('P07',cursor='2020-03-31')
    assert [t['ticker'] for t in terms]==['CY','MLNX','WBC','MNTA','AIMT','IMMU','MYOK','VRTU']
    assert len(codec.composition['sources'])==2
    for source in codec.composition['sources']:
        original=json.loads((f.HERE/source['catalog_file']).read_bytes())
        selected=[t for t in terms if t['ticker'] in source['selected_tickers']]
        assert selected==original['terms']
    suppress=f.suppressions(dict(source_cursor='2020-03-31'),terms)
    assert len(suppress)==8 and all(t['session']>'2020-03-31' for t in suppress)
    assert sprint.SID not in {t['security_id'] for t in suppress}


def fixture(tmp_path,monkeypatch,*,retained=False,bad=None):
    monkeypatch.setenv('GITHUB_ACTIONS','true');monkeypatch.setenv('RUNNER_ENVIRONMENT','github-hosted')
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT','1')
    raw=b'original';expected=f.sha(raw);data=b'corrupt!' if bad=='hash' else raw
    if bad=='long':data=raw+b'x'
    monkeypatch.setattr(sprint,'ALIAS_BYTES',len(raw));monkeypatch.setattr(sprint,'ALIAS_SHA',expected)
    calls=[];parses=[]
    monkeypatch.setattr(f,'selected',lambda *a,**kw:(None,None,[dict(security_id=sprint.SID)]))
    monkeypatch.setattr(sprint,'alias_rows',lambda path,hashes:parses.append(path.read_bytes()) or [dict(alias='S2')])
    class Response(io.BytesIO):
        status=500 if bad=='status' else 200
        headers={'Content-Encoding':'gzip'} if bad=='encoding' else {}
        def read(self,size=-1):
            assert size==len(raw)+1
            return super().read(size)
    def open_(url,*,timeout):
        calls.append((url,timeout));return Response(data)
    monkeypatch.setattr(urllib.request,'urlopen',open_)
    old,out=tmp_path/'old',tmp_path/'out';old.mkdir();out.mkdir()
    if retained:
        (old/'provider-source').mkdir();(old/'provider-source/SHARADAR_ACTIONS.zip').write_bytes(data)
    spec=dict(arm='P07',selected_session='2020-02-28')
    return spec,old,out,calls,parses,raw


@pytest.mark.parametrize('retained',[False,True])
def test_exact_source_is_copied_or_fetched_once_then_hash_verified_before_parse(tmp_path,monkeypatch,retained):
    spec,old,out,calls,parses,raw=fixture(tmp_path,monkeypatch,retained=retained)
    f.stage_selected_sources(spec,old,out)
    assert calls==([] if retained else [(sprint.ALIAS_URL,60)])
    assert parses==[raw] and (out/'provider-source/SHARADAR_ACTIONS.zip').read_bytes()==raw
    proof=json.loads((out/'provider-alias-proof.json').read_bytes())
    assert proof['strategy_metadata_upgraded'] is False and proof['source_sha256']==f.sha(raw)


@pytest.mark.parametrize('bad',['hash','long','status','encoding'])
def test_wrong_provider_bytes_or_response_refuse_before_alias_parse(tmp_path,monkeypatch,bad):
    spec,old,out,calls,parses,raw=fixture(tmp_path,monkeypatch,bad=bad)
    with pytest.raises(ValueError):f.stage_selected_sources(spec,old,out)
    assert len(calls)==1 and parses==[] and not (out/'provider-source/SHARADAR_ACTIONS.zip').exists()


def test_bad_retained_object_is_not_replaced_by_a_new_network_fetch(tmp_path,monkeypatch):
    spec,old,out,calls,parses,_=fixture(tmp_path,monkeypatch,retained=True,bad='hash')
    with pytest.raises(ValueError):f.stage_selected_sources(spec,old,out)
    assert calls==parses==[]


def test_nonhost_refuses_before_network_or_writes(tmp_path,monkeypatch):
    spec,old,out,calls,parses,_=fixture(tmp_path,monkeypatch)
    monkeypatch.setenv('GITHUB_ACTIONS','false')
    with pytest.raises(ValueError):f.stage_selected_sources(spec,old,out)
    assert calls==parses==[] and list(out.iterdir())==[]


def test_unselected_source_phase_performs_no_io(tmp_path,monkeypatch):
    spec,old,out,calls,parses,_=fixture(tmp_path,monkeypatch)
    spec['arm']='P00'
    f.stage_selected_sources(spec,old,out)
    assert calls==parses==[] and list(out.iterdir())==[]


def test_consumed_source_is_retained_for_following_phase_without_network(tmp_path,monkeypatch):
    spec,old,out,calls,parses,raw=fixture(tmp_path,monkeypatch,retained=True)
    spec['selected_session']='2020-03-31'
    f.stage_selected_sources(spec,old,out)
    assert calls==[] and parses==[raw]
    assert json.loads((out/'provider-alias-proof.json').read_bytes())['selected_security_ids']==[sprint.SID]


def test_missing_consumed_alias_is_refused_instead_of_refetched_and_guard_removal_falsifier(tmp_path,monkeypatch):
    spec,old,out,calls,parses,raw=fixture(tmp_path,monkeypatch)
    spec['selected_session']='2020-03-31'
    with pytest.raises(ValueError):f.stage_selected_sources(spec,old,out)
    assert calls==parses==[]
    other=tmp_path/'other';other.mkdir()
    fn=next(n for n in ast.parse(Path(f.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='stage_selected_sources')
    guard,=[n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
            and any(isinstance(a,ast.Constant) and a.value=='FUTURE_CONSUMED_ALIAS_SOURCE_MUST_BE_RETAINED_NOT_REFETCHED' for a in n.value.args)]
    fn.body.remove(guard);ns=dict(vars(f))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-consumed-alias-retention-guard>','exec'),ns)
    ns['stage_selected_sources'](spec,old,other)
    assert calls==[(sprint.ALIAS_URL,60)] and parses==[raw]


def test_removed_preparse_hash_guard_exposes_corrupt_bytes_to_parser(tmp_path,monkeypatch):
    spec,old,out,calls,parses,_=fixture(tmp_path,monkeypatch,bad='hash')
    with pytest.raises(ValueError):f.stage_selected_sources(spec,old,out)
    other=tmp_path/'other';other.mkdir()
    fn=next(n for n in ast.parse(Path(f.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='stage_selected_sources')
    guard,=[n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call)
            and any(isinstance(a,ast.Constant) and a.value=='FUTURE_ORIGINAL_PROVIDER_BYTES_BEFORE_PARSE' for a in n.value.args)]
    fn.body.remove(guard);ns=dict(vars(f))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),'<removed-provider-preparse-byte-guard>','exec'),ns)
    ns['stage_selected_sources'](spec,old,other)
    assert parses==[b'corrupt!']
