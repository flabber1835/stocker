"""Retained failed V recorder and a single explicitly versioned successor."""
import argparse,ast,json
from pathlib import Path
from full_system_benchmark import need
from seal import sha256_file
from system_campaign_facts import sha
from system_campaign_parallel_discovery import compile_body
import system_campaign_volatility_discovery_job as original
import system_campaign_p01_accurate_job as source_prior

HERE=Path(__file__).parent;ARMS=original.ARMS
PRIOR=source_prior.REQUEST;PRIOR_SHA='70cb685834aa55378375978e97fac0d012729aa0586f7f18ea9fede9925aa8f8'
REQUEST='system-campaign-volatility-discovery-request-002.json'
RECOVERY='system-campaign-volatility-recorder-failure-001.json'
SOURCES=tuple(dict.fromkeys((*source_prior.SOURCES,PRIOR,RECOVERY,
    'system_campaign_volatility_discovery_gate_v2.py','system_campaign_volatility_discovery_run_v2.py',
    'system_campaign_volatility_discovery_job_v2.py','system_campaign_volatility_discovery_probe_v2.py')))

def expected_request():
    raw=(HERE/PRIOR).read_bytes();need(sha(raw)==PRIOR_SHA,'V_RECORDER_EXACT_P01_SOURCE_CLOSURE')
    prior=json.loads(raw);need(len(prior['sources'])==402
        and all(sha256_file(HERE/n)==v for n,v in prior['sources'].items()),'V_RECORDER_ALL402_PRIOR_SOURCES_UNCHANGED')
    request=original.expected_request();failure=json.loads((HERE/RECOVERY).read_bytes())
    need(failure['run_id']==41360218956 and tuple(failure['arms'])==ARMS
         and all(v['qualifier_exit_code']==1 and v['no_diagnostic_origin_or_worker'] for v in failure['arms'].values()),
         'V_RECORDER_EXACT_FAILED_RECORDERS_NO_DIAGNOSTIC_RESTART')
    request.update(schema='research.volatility-discovery-recorder-recovery-request/1',
        prior402_request_sha256=PRIOR_SHA,recorder_recovery_file=RECOVERY,
        recorder_recovery_sha256=sha256_file(HERE/RECOVERY),
        typed_publication_digest='EXISTING_DISCOVERY_MATERIAL_DIGEST',
        sources={n:sha256_file(HERE/n) for n in SOURCES})
    return request

def entrypoint(arm,mode):
    need(arm in ARMS and mode in ('qualify','discovery'),'V_RECORDER_EXACT_TWO_ENTRYPOINTS')
    return ['-B','-u','/driver/system_campaign_volatility_discovery_run_v2.py',
            '--mode',mode,'--arm',arm,'--spec','/out/spec.json']

def worker_command(*args):
    return compile_body(original.previous.adopted('worker_command'),
        dict(vars(original.original),entrypoint=entrypoint))(*args)

def inspect(name,identity=None):
    need(name.split('-')[4].upper() in ARMS,'V_RECORDER_INSPECT_ONLY_TWO_V_ARMS')
    return compile_body(original.previous.adopted('inspect'),
        dict(vars(original.original),entrypoint=entrypoint))(name,identity)

def main(args):
    fn,=[n for n in ast.parse(Path(original.__file__).read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='main']
    return compile_body(fn,dict(vars(original),expected_request=expected_request,
        worker_command=worker_command,inspect=inspect))(args)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--arm',choices=ARMS,required=True)
    for name in ('request','staging','output'):p.add_argument('--'+name,type=Path,required=True)
    main(p.parse_args())
