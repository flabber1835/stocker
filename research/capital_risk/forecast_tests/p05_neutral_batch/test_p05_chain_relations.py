"""In-memory NONCANONICAL metadata DTOs; no financial state or book files."""
import gzip,json,sys
from copy import deepcopy
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).parent))
from test_p05_neutral_batch import Fence
sys.meta_path.insert(0,Fence())
import system_campaign_p05_batch_runtime as r

def fixture(monkeypatch):
    import system_campaign_financial_partial as partial
    empty=dict(bytes=0,prefix_sha256=r.sha(b''))
    before=dict(schema='NONCANONICAL-CHAIN-METADATA-DTO/1',base={'NONCANONICAL':True},source_cursor='2099-01-01',completed=1,
        economics={'NONCANONICAL':True},stats={'NONCANONICAL':True},spy_base=None,retries={'NONCANONICAL':True},
        repairs=[{'NONCANONICAL_INPUT_DESCRIPTOR_DTO':i} for i in range(16)],
        journals={key:deepcopy(empty) for key in ('formation','daily','monthly','watch')},chain='1'*64)
    before['run']=dict(state={'NONCANONICAL_METADATA_ONLY':True,'last_processed_session':'2099-01-01'})
    def commit(cp):
        cp['run']['state_sha256']=r.digest(cp['run']['state'])
        cp['run']['input_sha256']=r.digest(dict(base=cp['base'],repairs=cp['repairs']))
        cp['run']['checkpoint_sha256']=r.digest({k:v for k,v in cp['run'].items() if k!='checkpoint_sha256'})
        cp['sha256']=r.digest({k:v for k,v in cp.items() if k!='sha256'})
    commit(before);members={r.PARENT:gzip.compress(r.encoded(before))};watch=b'';stages=[]
    parent_pin=dict(bytes=len(members[r.PARENT]),sha256=r.sha(members[r.PARENT]))
    monkeypatch.setattr(partial,'root_spec',lambda *a:{'selected_file':parent_pin})
    def data_parent(cp):assert cp['schema']=='NONCANONICAL-CHAIN-METADATA-DTO/1' and cp['run']['state']['NONCANONICAL_METADATA_ONLY'] is True
    monkeypatch.setattr(r.data,'parent_contract',data_parent)
    for index in range(3):
        directory=r.api_module.directory(index);overlay=r.api_module.overlay(index);cat=r.api_module.catalog_name(index)
        doc=dict(schema='terminal-repair/1',predecessor_checkpoint_sha256=before['run']['checkpoint_sha256'],
            suppress=[{'session':'2099-01-02','NONCANONICAL':True}],add=[{'session':'2099-01-03','NONCANONICAL':True}],source_evidence=[{'NONCANONICAL':True}])
        members[overlay]=r.encoded(doc)
        after=deepcopy(before)
        d=dict(filename=r.sha(members[overlay])+'.json',sha256=r.sha(members[overlay]),resume_session=before['source_cursor'],predecessor_checkpoint_sha256=before['run']['checkpoint_sha256'])
        after['repairs'].append(d);commit(after)
        event=dict(schema='research.pooled-action-successor/1',predecessor_checkpoint_sha256=before['run']['checkpoint_sha256'],
            unchanged_through=before['source_cursor'],earliest_affected_session='2099-01-02',state_sha256=before['run']['state_sha256'],overlay=d,
            predecessor_input_sha256=before['run']['input_sha256'],successor_input_sha256=after['run']['input_sha256'])
        watch+=json.dumps(event,sort_keys=True,separators=(',',':')).encode()+b'\n'
        after['journals']['watch']=dict(bytes=len(watch),prefix_sha256=r.sha(watch));after['chain']=r.digest(dict(previous=before['chain'],event=event));commit(after)
        raw=gzip.compress(r.encoded(after));members[directory+'/checkpoint.json.gz']=raw
        members[directory+'/proof.json']=r.encoded(dict(event=event,actual_checkpoint_gzip_sha256=r.sha(raw),original_outer_sha256=before['sha256'],
            financial_state_unchanged=True,financial_sessions_advanced=0))
        members[directory+'-correlation-inputs.jsonl.gz']=gzip.compress(b'NONCANONICAL_CORRELATION_METADATA\n')
        members[cat]=members[r.api_module.qualification(index)]=members[r.future.hydration_name(before)]=b'{"NONCANONICAL_INPUT_METADATA":true}\n'
        stages.append(dict(index=index,parent_outer_sha256=before['sha256'],successor_outer_sha256=after['sha256']));before=after
    value=dict(schema='research.p05-actual-neutral-cash-batch-chain/1',passed=True,origin_root_admission_sha256=r.data.ROOT,
        financial_sessions_advanced=0,origin_parent_is_retained_financial_seed=False,canonical_financial_source_changed=False,
        original_correlation_rows_sha256=r.sha(b'NONCANONICAL_CORRELATION_METADATA\n'),stages=stages,
        resources={n:dict(bytes=len(raw),sha256=r.sha(raw)) for n,raw in members.items()})
    members['book/watch.jsonl']=watch
    return value,before,members

def test_complete_three_stage_relation_uses_original_neutral_contract(monkeypatch):
    value,current,members=fixture(monkeypatch)
    initial,last,stages=r.chain_relations(value,current,lambda n:members[n])
    assert initial['schema']=='NONCANONICAL-CHAIN-METADATA-DTO/1' and last==current
    assert [s['source_evidence'] for s in stages]==[1,1,1]
    assert len(initial['repairs'])==16 and len(last['repairs'])==19

@pytest.mark.parametrize('change',['financial_authority','seed_authority','unsafe_name','raw_boundary','watch_prefix','correlation','current_input_hash','current_state'])
def test_chain_refuses_state_source_watch_or_authority_mutation(monkeypatch,change):
    value,current,members=fixture(monkeypatch)
    if change=='financial_authority':value['financial_sessions_advanced']=True
    elif change=='seed_authority':value['origin_parent_is_retained_financial_seed']=True
    elif change=='unsafe_name':value['resources']['../FOREIGN']={'bytes':0,'sha256':r.sha(b'')}
    elif change=='raw_boundary':members[r.api_module.directory(0)+'/checkpoint.json.gz']+=b'FOREIGN'
    elif change=='watch_prefix':members['book/watch.jsonl']=members['book/watch.jsonl'].replace(b'2099',b'FORE',1)
    elif change=='correlation':
        name=r.api_module.directory(0)+'-correlation-inputs.jsonl.gz';members[name]=gzip.compress(b'NEW_NONCANONICAL_OBSERVATION\n')
        value['resources'][name]=dict(bytes=len(members[name]),sha256=r.sha(members[name]))
    elif change=='current_input_hash':current['run']['input_sha256']='0'*64
    else:current['run']['state']['NONCANONICAL_METADATA_ONLY']=False
    with pytest.raises((ValueError,KeyError)):r.chain_relations(value,current,lambda n:members[n])
