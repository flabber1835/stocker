"""Two unstarted V forks; immutable prior drivers and exact existing fences."""
import argparse,ast,json
from pathlib import Path
from full_system_benchmark import need
from seal import sha256_file
from system_campaign_facts import sha
from system_campaign_parallel_discovery import compile_body
from system_campaign_volatility_discovery_run import ARMS
import system_campaign_risk_discovery_job as previous
import system_campaign_parallel_discovery_job as original

HERE=Path(__file__).parent
PRIOR=previous.REQUEST
PRIOR_SHA='368b2a778dcb6823df94d93a1327b4d3962ce1e04e8028717cb24c3f5f9e54fd'
REQUEST='system-campaign-volatility-discovery-request-001.json'
RECOVERY='system-campaign-volatility-retention-recovery-001.json'
SOURCES=tuple(dict.fromkeys((*previous.SOURCES,PRIOR,RECOVERY,
    'system_campaign_volatility_discovery_gate.py','system_campaign_volatility_discovery_run.py',
    'system_campaign_volatility_discovery_job.py','system_campaign_volatility_discovery_probe.py')))

def expected_request():
    raw=(HERE/PRIOR).read_bytes();need(sha(raw)==PRIOR_SHA,'V_RETENTION_EXACT_391_REQUEST')
    old=json.loads(raw)
    need(len(old['sources'])==391 and all(sha256_file(HERE/n)==h for n,h in old['sources'].items()),
         'V_RETENTION_ALL391_OLD_SOURCE_BYTES_UNCHANGED')
    request=previous.expected_request();need(request==old,'V_RETENTION_EXACT_PRIOR_ORCHESTRATION')
    recovery=json.loads((HERE/RECOVERY).read_bytes())
    need(recovery['run_id']==41358212146 and tuple(recovery['arms'])==ARMS
         and all(v['no_diagnostic_origin_or_worker'] and v['qualifier_exit_code']==1
                 and not v['oom_killed'] for v in recovery['arms'].values()),
         'V_RETENTION_TWO_ACTUAL_FAILED_QUALIFIERS_NO_RESTART')
    request.update(schema='research.volatility-discovery-retention-recovery-request/1',arms=list(ARMS),
        concurrent_candidate_limit=2,prior391_request_sha256=PRIOR_SHA,
        recovery_evidence_file=RECOVERY,recovery_evidence_sha256=sha256_file(HERE/RECOVERY),
        signal_material_closes=127,actual_fast_reference_full_runtime_equality_required=True,
        actual_discovery_replay_changed='RETAIN_ORIGINAL_SIGNAL_HISTORY_ONLY',
        financial_source_or_risk_rule_changed=False,all_three_failed_before_diagnostic_origin=False,
        other_candidates_unchanged=True,sources={n:sha256_file(HERE/n) for n in SOURCES})
    return request

def entrypoint(arm,mode):
    need(arm in ARMS and mode in ('qualify','discovery'),'V_RETENTION_EXACT_TWO_ENTRYPOINTS')
    return ['-B','-u','/driver/system_campaign_volatility_discovery_run.py',
            '--mode',mode,'--arm',arm,'--spec','/out/spec.json']

def worker_command(*args):
    return compile_body(previous.adopted('worker_command'),dict(vars(original),entrypoint=entrypoint))(*args)

def inspect(name,identity=None):
    need(name.split('-')[4].upper() in ARMS,'V_RETENTION_INSPECT_ONLY_TWO_V_ARMS')
    return compile_body(previous.adopted('inspect'),dict(vars(original),entrypoint=entrypoint))(name,identity)

def check_qualification(proof,arm):
    previous.check_qualification(proof,arm)
    need(proof['signal_material_closes']==127
         and proof['actual_fast_reference_full_runtime_paths_equal'] is True
         and proof['actual_fast_reference_published_sessions_equal'] is True
         and proof['financial_source_or_risk_rule_changed'] is False,
         'V_RETENTION_ACTUAL_HOSTED_FULL_RUNTIME_EQUIVALENCE_REQUIRED')

def main(args):
    need(args.arm in ARMS,'V_RETENTION_ONLY_TWO_UNSTARTED_ARMS')
    fn=previous.adopted('main');sites=[]
    for node in ast.walk(fn):
        for field,value in ast.iter_fields(node):
            if isinstance(value,list):
                for i,n in enumerate(value):
                    if isinstance(n,ast.Assign) and len(n.targets)==1 and ast.unparse(n.targets[0])=='proof':sites.append((value,i))
    need(len(sites)==1,'V_RETENTION_ONE_QUALIFICATION_ADMISSION_SITE')
    values,i=sites[0];values[i+1:i+1]=ast.parse('check_qualification(proof,args.arm)').body
    return compile_body(fn,dict(vars(original),expected_request=expected_request,
        worker_command=worker_command,inspect=inspect,check_qualification=check_qualification))(args)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--arm',choices=ARMS,required=True)
    for name in ('request','staging','output'):p.add_argument('--'+name,type=Path,required=True)
    main(p.parse_args())
