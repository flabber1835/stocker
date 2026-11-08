import ast,gzip,hashlib,json,os,sys
from pathlib import Path
D=Path('C:/GitHub/stocker/.codex-tmp/p03-fin337-thor-qualified-reuse-20261106');C=Path(__file__).parents[2];sys.path[:0]=[str(C)]
class Fence:
    def find_spec(self,name,path=None,target=None):
        if name.startswith(('research.pooled_','stock_strategy_shared','sentinel','numpy','pandas')):raise ImportError('FIN337_P03_DATA_ONLY:'+name)
sys.meta_path.insert(0,Fence())
import system_campaign_p03_thor_runtime as thor
from system_campaign_financial_partial import root_spec
R=Path('C:/Users/mbron/.codex/visualizations/2026/11/05/01a1ac36-4c96-7aa1-82ca-4efb70a86ea8')
F=R/'financial337-source-snapshot';CAP=F/'capture-P03-13520549642-001'
def long(path):
    path=Path(path)
    return Path('\\\\?\\'+str(path.resolve())) if os.name=='nt' and not str(path).startswith('\\\\?\\') else path
sha=lambda r:hashlib.sha256(r).hexdigest()
enc=lambda v:(json.dumps(v,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def read():
    root=long(CAP/'verified-output');manifest=json.loads((CAP/'authenticated-manifest.json').read_bytes())
    members=manifest['members'];assert len(members)==182 and sum(v['bytes'] for v in members.values())==120869438
    def member(name):
        raw=(root/name).read_bytes();assert dict(bytes=len(raw),sha256=sha(raw))==members[name],name;return raw
    for name in members:member(name)
    request=json.loads(member('request.json'))
    for name in ('system_campaign_p03_thor_runtime.py','system_campaign_p03_thor_data.py','system_campaign_p03_thor_api.py',
        'system_campaign_bounded_sensor_runtime_v2.py','system_campaign_financial_uncertainty.py','system_campaign_bounded_sensor_seed_binding.py','system_campaign_financial_branches.py'):
        assert sha((C/name).read_bytes())==request['sources'][name],name
    spec=root_spec('P03',thor.data.ROOT);parent=thor.strict_json(member(thor.SELECTED));thor.data.parent_contract(parent,spec)
    neutral=thor.strict_json(member('book/checkpoint.json.gz'))
    corr=gzip.decompress(member(thor.api_module.DIRECTORY+'-correlation-inputs.jsonl.gz')).splitlines(keepends=True)
    boundary=thor.boundary_relation(parent,neutral,spec,member,corr)
    assert neutral['sha256']=='5fb4362552632deb492c59b4348c73aa3be0b18733c2a7a4303c482efef191fc'
    assert len(neutral['repairs'])==17 and neutral['completed']==parent['completed']==503
    raw=member(thor.RAW_PROOF);lines=raw.splitlines(keepends=True);assert len(lines)==63
    seed=[json.loads(v) for v in lines[:49]];assert seed[-1]['session']==neutral['source_cursor']
    assert all(json.loads(v)['session']>parent['source_cursor'] for v in lines[49:])
    qualified=member('branch-controller-qualification.json');q=json.loads(qualified)
    assert q['passed'] is q['actual_divergent_decisions_refused'] is q['all_possible_counters_retained_and_later_merged'] is q['ambiguous_comparisons_exhaustively_partitioned'] is True
    assert q['historical_financial_sessions_advanced']==0 and len(q['exact_controller_sources'])==6
    assert all(neutral['base']['sources'][n]==h for n,h in q['exact_controller_sources'].items())
    log=member('worker.log').decode();assert 'FileExistsError' in log and "'/out/branch-controller-qualification.json'" in log
    assert 'uncertainty-certificate.jsonl' not in members
    return root,members,member,spec,parent,neutral,seed,qualified,boundary
def main():
    root,members,member,spec,parent,neutral,seed,qualified,boundary=read()
    review=json.loads((CAP/'capture-review.json').read_bytes())
    assert review['new_committed_sessions']==0 and review['actual_stops']['economic']['exit_code']==review['actual_stops']['review']['exit_code']==1
    result=dict(schema='research.P03-FIN337-qualification-collision-DATA/1',passed=True,financial_authority=False,
        local_canonical_runtime_executed=False,financial_sessions_advanced=0,artifact_id=13520549642,head='d2088351f2f0bf15d5ea6b6a3ca2992341b6acc5',
        members=182,logical_bytes=120869438,all_full_member_hashes_verified=True,all_frozen_source_closure_pins_verified=True,
        actual_selected_parent_outer_sha256=parent['sha256'],actual_neutral17_outer_sha256=neutral['sha256'],boundary=boundary,
        qualification_bytes=len(qualified),qualification_sha256=sha(qualified),admitted_seed_rows=49,whole_retained_raw_rows=63,unadmitted_tail_rows=14,
        downstream_uncertainty_certificate_absent_before_original_Certificate_construction=True,downstream_review_passed=False,
        source_hashes={n:sha((C/n).read_bytes()) for n in ('system_campaign_p03_thor_runtime.py','system_campaign_bounded_sensor_runtime_v2.py','system_campaign_financial_uncertainty.py')})
    raw=enc(result)
    with (D/'P03-FIN337-qualification-collision-DATA.json').open('xb') as s:s.write(raw)
    print(json.dumps(dict(passed=True,sha256=sha(raw),qualification_sha256=sha(qualified),qualification_bytes=len(qualified),source_hashes=result['source_hashes'])))
if __name__=='__main__':main()
