"""Three-arm synthetic qualification repair; original discovery stays intact."""
import argparse,ast,hashlib,json
from copy import deepcopy
from pathlib import Path

from full_system_benchmark import need
from seal import sha256_file
import system_campaign_parallel_discovery_job as original
from system_campaign_parallel_discovery import compile_body
from system_campaign_risk_discovery_run import ARMS,CODES

HERE=Path(__file__).parent
PRIOR_SHA='863f6c7983fc2cdc1a86bd58a9c4987744d180e8bb56568608eda77d29f85fcd'
REQUEST='system-campaign-risk-discovery-request-002.json'
RECOVERY='system-campaign-risk-discovery-recovery.json'
SOURCES=tuple(dict.fromkeys((*original.SOURCES,original.REQUEST,RECOVERY,
    'system_campaign_risk_discovery_gate.py','system_campaign_risk_discovery_run.py',
    'system_campaign_risk_discovery_job.py','system_campaign_risk_discovery_probe.py',
    'system-campaign-risk-discovery-request-001.json','system-campaign-risk-prepare-order-provenance.json')))


def adopted(name):
    prior=(HERE/original.REQUEST).read_bytes()
    need(hashlib.sha256(prior).hexdigest()==PRIOR_SHA,'RISK_RECOVERY_EXACT_PRIOR383_REQUEST')
    raw=Path(original.__file__).read_bytes()
    need(hashlib.sha256(raw).hexdigest()==json.loads(prior)['sources'][Path(original.__file__).name],
         'RISK_RECOVERY_ORIGINAL_PARALLEL_ORCHESTRATOR_BYTES')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name==name]
    return deepcopy(fn)


def expected_request():
    request=original.expected_request()
    need(json.loads((HERE/original.REQUEST).read_bytes())==request,'RISK_RECOVERY_ALL383_OLD_BYTES_UNCHANGED')
    recovery=json.loads((HERE/RECOVERY).read_bytes())
    need(tuple(recovery['arms'])==ARMS and recovery['financial_authority'] is False
         and all(v['expected_refusal']==CODES[a] and v['no_discovery_launch_or_checkpoint'] is True
                 for a,v in recovery['arms'].items()),'RISK_RECOVERY_EXACT_THREE_FAILED_QUALIFIERS_NO_DISCOVERY')
    request.update(schema='research.risk-discovery-qualification-recovery-request/1',arms=list(ARMS),
        concurrent_candidate_limit=3,prior383_request_sha256=PRIOR_SHA,recovery_evidence_file=RECOVERY,
        recovery_evidence_sha256=sha256_file(HERE/RECOVERY),
        qualification_kind='ORIGINAL_RISK_GUARDS_PRESERVED_HELD_MISSING_INPUT_REFUSED',
        actual_discovery_replay_changed=False,risk_guards_bypassed=False,
        all_three_failed_before_diagnostic_origin=True,other_five_jobs_unchanged=True,
        retained_failed_prepare_request_sha256='a2039e366633fc7a7bbd7f6e059e9eeecb01094cd916bce42df9f2d6d290570f',
        prepare_order_provenance_sha256=sha256_file(HERE/'system-campaign-risk-prepare-order-provenance.json'),
        sources={n:sha256_file(HERE/n) for n in SOURCES})
    validate_prepare_order()
    return request


def validate_prepare_order():
    oldraw=(HERE/'system-campaign-risk-discovery-request-001.json').read_bytes()
    need(hashlib.sha256(oldraw).hexdigest()=='a2039e366633fc7a7bbd7f6e059e9eeecb01094cd916bce42df9f2d6d290570f',
         'RISK_PREPARE_EXACT_RETAINED_FAILED_REQUEST')
    old=json.loads(oldraw);proof=json.loads((HERE/'system-campaign-risk-prepare-order-provenance.json').read_bytes())
    changed=['system_campaign_risk_discovery_gate.py','system_campaign_risk_discovery_job.py']
    need(proof['changed_driver_files']==changed and proof['financial_source_or_rule_changed'] is False
         and all(sha256_file(HERE/n)==h for n,h in old['sources'].items() if n not in changed),
         'RISK_PREPARE_ONLY_TWO_EXPLICIT_DRIVER_SUCCESSORS')
    raw=proof['original_gate_source_text'].encode()
    need(hashlib.sha256(raw).hexdigest()==proof['original_gate_sha256']==old['sources'][changed[0]],
         'RISK_PREPARE_EXACT_ORIGINAL_GATE_PREIMAGE')
    before=ast.parse(raw);after=ast.parse((HERE/changed[0]).read_bytes())
    fn,=[n for n in before.body if isinstance(n,ast.FunctionDef) and n.name=='expected_refusal']
    pub,=[n for n in fn.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='published']
    prior,=[n for n in fn.body if isinstance(n,ast.Assign) and ast.unparse(n.targets[0])=='publication']
    fn.body.remove(pub);fn.body.remove(prior)
    block,=[n for n in fn.body if isinstance(n,ast.With)]
    block.body[:0]=[pub,prior]
    need(ast.dump(before,include_attributes=False)==ast.dump(after,include_attributes=False),
         'RISK_PREPARE_ONLY_PUBLICATION_MOVED_INSIDE_EXISTING_EXECUTION_CONTEXT')


def entrypoint(arm,mode):
    need(arm in ARMS and mode in ('qualify','discovery'),'RISK_RECOVERY_THREE_EXACT_ENTRYPOINTS')
    return ['-B','-u','/driver/system_campaign_risk_discovery_run.py','--mode',mode,'--arm',arm,'--spec','/out/spec.json']


def worker_command(*args):
    return compile_body(adopted('worker_command'),dict(vars(original),entrypoint=entrypoint))(*args)


def inspect(name,identity=None):
    need(name.split('-')[4].upper() in ARMS,'RISK_RECOVERY_INSPECT_ONLY_THREE_ARMS')
    return compile_body(adopted('inspect'),dict(vars(original),entrypoint=entrypoint))(name,identity)


def check_qualification(proof,arm):
    need(arm in ARMS and proof['qualification_kind']=='ORIGINAL_RISK_GUARDS_PRESERVED_HELD_MISSING_INPUT_REFUSED'
         and proof['held_missing_quote_continuation'] is False and proof['all_actual_held_quotes_unchanged'] is True
         and proof['normal_source_packets_unchanged'] is True
         and proof['incomplete_toy_position_cash_shares_and_slot_unchanged'] is True,
         'RISK_RECOVERY_CORRECT_FAMILY_SPECIFIC_CANONICAL_GATE')
    r=proof['expected_held_input_refusal']
    need(r['status']=='EXPECTED_ORIGINAL_RISK_INPUT_REFUSAL_QUALIFIED' and r['expected_refusal']==CODES[arm]
         and r['committed_transitions']==0 and r['prior_and_publication_unchanged'] is True
         and r['original_hook_restored'] is True,'RISK_RECOVERY_ACTUAL_EXISTING_GUARD_REFUSAL_PROOF')


def main(args):
    need(args.arm in ARMS,'RISK_RECOVERY_ONLY_OWNER_SELECTED_UNSTARTED_ARMS')
    fn=adopted('main');sites=[]
    for node in ast.walk(fn):
        for field,value in ast.iter_fields(node):
            if isinstance(value,list):
                for i,n in enumerate(value):
                    if isinstance(n,ast.Assign) and len(n.targets)==1 and ast.unparse(n.targets[0])=='proof':sites.append((value,i))
    need(len(sites)==1,'RISK_RECOVERY_ONE_ACTUAL_QUALIFICATION_ADMISSION_SITE')
    statements,i=sites[0];statements[i+1:i+1]=ast.parse('check_qualification(proof,args.arm)').body
    return compile_body(fn,dict(vars(original),expected_request=expected_request,
        worker_command=worker_command,inspect=inspect,check_qualification=check_qualification))(args)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--arm',choices=ARMS,required=True)
    for name in ('request','staging','output'):p.add_argument('--'+name,type=Path,required=True)
    main(p.parse_args())
