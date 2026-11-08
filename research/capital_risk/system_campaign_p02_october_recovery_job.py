"""Same unchanged September30 P02 continuation after a verified unadvanced preflight refusal."""
import argparse
import base64
import json
import os
from pathlib import Path
import shutil
import traceback

from full_system_benchmark import need
from full_system_trials_job import command
from system_campaign_evidence_export import seal
from system_campaign_p02_october_job import SOURCES as PRIOR
from system_campaign_p02_continue_job import inspect as prior_inspect
from system_campaign_large_factual_admit import admit
from system_campaign_own_origin import capture as capture_origin
from system_campaign_ancestor import preserve as preserve_ancestor
from system_campaign_variants import build
from alpaca_fit_job import stopped_run, StopUnknown
from probe import check_context, memory_bytes
from stage import SECRET, PROTOCOL, IMAGE
from runtime_identity import EXECUTION_IMAGE
from seal import sha256_file
from system_campaign_sprint_facts import fetch_alias, PACKET_SOURCE_PATH

HERE=Path(__file__).resolve().parent
SOURCES=tuple(dict.fromkeys((*PRIOR,'system_campaign_mixed_preflight.py',
    'system_campaign_p02_october_recovery_job.py','system-campaign-p02-october-unadvanced-equivalence.json')))


def expected_request():
    spec=json.loads((HERE/'system-campaign-p02-october-predecessor.json').read_bytes())
    need(spec['arm']=='P02' and spec['run_id']==41151496224
         and not spec.get('unadvanced_qualification_failure')
         and not spec.get('review_refusal')
         and spec['receipt_schema']=='research.system-p02-uncertainty-suffix-receipt/1'
         and spec['selected_session']=='2022-09-30','UNCERTAINTY_EXACT_CALENDAR_OWN_PREDECESSOR')
    proof=json.loads((HERE/'system-campaign-uncertainty-qualification.json').read_bytes())
    return dict(schema='research.system-p02-uncertainty-suffix-request/1',campaign='system-optimization-002',
        only_candidate='P02',concurrent_candidate_limit=1,
        protocol_sha256=sha256_file(HERE/'system-campaign-search-protocol.json'),
        predecessor_file='system-campaign-p02-october-predecessor.json',
        predecessor_sha256=sha256_file(HERE/'system-campaign-p02-october-predecessor.json'),
        initial_min_disk_bytes=12*1024**3,
        qualified_packet_source_sha256=spec['base']['sources'][PACKET_SOURCE_PATH],
        execution_mode='GUARDED_COMPLETION_BATCH_EXACT_SUFFIX',
        predecessor_common_basis_sha256='8fae82a7f4bf696c397416db57425d12750175545b20510b84cb2beb1a88859b',
        cash_calendar_catalog_sha256=sha256_file(HERE/'system-campaign-february-cash-calendar-terminal-facts.json'),
        stock_calendar_catalog_sha256=sha256_file(HERE/'system-campaign-stock-calendar-terminal-facts.json'),
        reconstruction_mode='ORIGINAL_COLD_WITH_QUALIFIED_FAST_TRANSACTION_SCOPE',
        zogenix_contract_sha256=sha256_file(HERE/'system-campaign-zogenix-sensor-contract.json'),
        completion_contract_sha256=sha256_file(HERE/'system-campaign-completion-scope-contract.json'),
        october_cash_catalog_sha256=sha256_file(HERE/'system-campaign-october-cash-calendar-terminal-facts.json'),
        prior_unadvanced_equivalence_sha256=sha256_file(HERE/'system-campaign-p02-october-unadvanced-equivalence.json'),
        ordinary_registry_sha256=sha256_file(HERE/'system-campaign-ordinary-catalog-registry.json'),
        sprint_catalog_sha256=sha256_file(HERE/'system-campaign-sprint-terminal-facts.json'),
        spring2020_cash_catalog_sha256=sha256_file(HERE/'system-campaign-spring2020-cash-terminal-facts.json'),
        autumn2020_cash_catalog_sha256=sha256_file(HERE/'system-campaign-autumn2020-cash-terminal-facts.json'),
        completions2021_catalog_sha256=sha256_file(HERE/'system-campaign-2021-completions-terminal-facts.json'),
        following_catalog_sha256=sha256_file(HERE/'system-campaign-following-completions-terminal-facts.json'),
        future_amendment_catalog_sha256=sha256_file(HERE/'system-campaign-future-input-amendment-catalog.json'),
        uncertainty_input_descriptor_sha256=spec['uncertainty_input_descriptor_sha256'],
        canonical_controller_sources=proof['canonical_controller_sources'],
        sources={n:sha256_file(HERE/n) for n in SOURCES},source_archive_limit_bytes=2*1024**3,
        export_expanded_limit_bytes=2*1024**3,
        financial_wait_seconds=12600,review_wait_seconds=2700,artifact_retention_days=7,
        new_overlay=True,new_origin=False,source_conversion=False,production_contacted=False)


def inspect(name,identity=None):
    result=prior_inspect(name,identity)
    mode='review' if '-review-' in name else 'economic'
    need(result['Config']['Cmd']==['-B','-u','/driver/system_campaign_p02_october_run.py',
        '--mode',mode,'--spec','/evidence/spec.json' if mode=='review' else '/out/spec.json',
        '--request','/driver/system-campaign-p02-october-recovery-request.json'],
        'UNCERTAINTY_EXACT_FINANCIAL_OR_REVIEW_ENTRYPOINT')
    return result


def main(args):
    check_context(os.environ);need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','UNCERTAINTY_NO_ECONOMIC_WORKFLOW_RERUN')
    request=json.loads(args.request.read_bytes());need(request==expected_request(),'UNCERTAINTY_EXACT_ECONOMIC_REQUEST')
    spec=json.loads((HERE/request['predecessor_file']).read_bytes())
    stage=json.loads(args.staging.read_bytes())
    need(stage['status']=='STAGING_PASSED' and stage['run_id']==os.environ['GITHUB_RUN_ID']
         and stage['source_commit']==os.environ['GITHUB_SHA'] and stage['protocol_sha256']==PROTOCOL
         and stage['runtime_image']==IMAGE and stage['execution_image']==EXECUTION_IMAGE
         and stage['source_files_verified']==514 and stage['members_verified']==591
         and stage['manifest_sha256']=='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
         and stage['authenticated_before_parsing'] and stage['offline_image_source_verified']
         and stage['runtime_index_config_layer_chain_verified'] and not stage['replay_started'],
         'UNCERTAINTY_EXACT_ECONOMIC_STAGING')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'UNCERTAINTY_KEY')
    temp=Path(os.environ['RUNNER_TEMP']);frozen=temp/'capital-risk-stage-001/inputs'
    need(shutil.disk_usage(temp).free>=request['initial_min_disk_bytes'],'UNCERTAINTY_INITIAL_DISK_BUDGET')
    old=admit(spec,temp/'campaign-factual-transfer-p02-uncertainty-suffix',key,
              max_zip_bytes=request['source_archive_limit_bytes'])
    out=temp/'p02-uncertainty-financial-output';out.mkdir(mode=0o700)
    need(all((old/name).is_file() for name in ('core-review.json',
         'uncertainty-certificate.jsonl','correlation-inputs.jsonl.gz'))
         and (old/'common-factual-and-uncertainty-basis.json').is_file(),
         'UNCERTAINTY_EXACT_ADMITTED_CALENDAR_PREFIX_SUPPORT_BEFORE_WORKER')
    q=old/'core-review.json'
    need(sha256_file(q)==spec['review_sha256'],'UNCERTAINTY_ACTUAL_OLD_FINANCIAL_PREFIX_PROOF_BYTES')
    value=json.loads(q.read_bytes())
    need(value['status']=='PARTIAL_CORE_PREFIX_REVIEWED' and value['checkpoint_sha256']==spec['outer_sha256']
         and value['all_prefixes_verified'] and value['all_daily_factors_and_chains_verified']
         and value['counts']=={'formation':126,'daily':1196},'UNCERTAINTY_ACTUAL_OWN_FINANCIAL_PREFIX')
    need(json.loads((old/'common-factual-and-uncertainty-basis.json').read_bytes())['sha256']==request['predecessor_common_basis_sha256'],
         'UNCERTAINTY_ACTUAL_RETAINED_EFFECTIVE_COMMON_BASIS')
    source=temp/'p02-uncertainty-financial-source'
    binding=build(frozen/'source-fixed',source,json.loads((old/'source-bindings.json').read_bytes())['parameters'])
    need(binding==json.loads((old/'source-bindings.json').read_bytes()),'UNCERTAINTY_EXACT_FINANCIAL_SOURCE_TREE')
    capture_origin(old,old,out)
    for name,raw in [('source-bindings.json',(old/'source-bindings.json').read_bytes()),
                     ('request.json',args.request.read_bytes()),('spec.json',(HERE/request['predecessor_file']).read_bytes()),
                     ('admitted-prior-financial-review.json',q.read_bytes())]:
        (out/name).write_bytes(raw)
    fetch_alias(out,old)
    os.environ.pop('GH_TOKEN',None)
    for root in (source,old):
        for path in root.rglob('*'):os.chmod(path,0o555 if path.is_dir() else 0o444)
        os.chmod(root,0o555)
    need(memory_bytes()['MemAvailable']>=10*1024**3 and shutil.disk_usage(temp).free>=10*1024**3,
         'UNCERTAINTY_ECONOMIC_RESOURCE_GATE')
    receipt=dict(schema='research.system-p02-uncertainty-suffix-receipt/1',arm='P02',
        run_id=os.environ['GITHUB_RUN_ID'],head=os.environ['GITHUB_SHA'],
        request_sha256=sha256_file(args.request),protocol_sha256=request['protocol_sha256'],
        predecessor_run_id=spec['run_id'],selected_predecessor_outer_sha256=spec['outer_sha256'],
        uncertainty_input_descriptor_sha256=request['uncertainty_input_descriptor_sha256'],
        execution_mode=request['execution_mode'],sprint_catalog_sha256=request['sprint_catalog_sha256'],
        cash_calendar_catalog_sha256=request['cash_calendar_catalog_sha256'],
        ordinary_registry_sha256=request['ordinary_registry_sha256'],
        stock_calendar_catalog_sha256=request['stock_calendar_catalog_sha256'],
        reconstruction_mode=request['reconstruction_mode'],
        zogenix_contract_sha256=request['zogenix_contract_sha256'],
        completion_contract_sha256=request['completion_contract_sha256'],
        october_cash_catalog_sha256=request['october_cash_catalog_sha256'],
        prior_unadvanced_equivalence_sha256=request['prior_unadvanced_equivalence_sha256'],
        spring2020_cash_catalog_sha256=request['spring2020_cash_catalog_sha256'],
        autumn2020_cash_catalog_sha256=request['autumn2020_cash_catalog_sha256'],
        completions2021_catalog_sha256=request['completions2021_catalog_sha256'],
        following_catalog_sha256=request['following_catalog_sha256'],
        future_amendment_catalog_sha256=request['future_amendment_catalog_sha256'],
        new_origin=False,new_overlay=True,source_conversion=False,production_contacted=False,
        status='NOT_STARTED',performance_admitted=False)
    def cmd(name,mode,target):
        result=command(name,source,frozen,target,mode)
        i=result.index('--entrypoint');result[i:i]=['--mount',f'type=bind,source={old},target=/old,readonly']
        if mode=='review':
            i=result.index('--entrypoint');result[i:i]=['--mount',f'type=bind,source={out},target=/evidence,readonly']
        result[result.index('/driver/full_system_core.py'):]=['/driver/system_campaign_p02_october_run.py',
            '--mode',mode,'--spec','/evidence/spec.json' if mode=='review' else '/out/spec.json',
            '--request','/driver/system-campaign-p02-october-recovery-request.json']
        return result
    known=False
    try:
        name='capital-system-factual-p02-worker-'+os.environ['GITHUB_RUN_ID']+'-1'
        worker=stopped_run(cmd(name,'economic',out),name,out,deadline=request['financial_wait_seconds'],inspector=inspect)
        known=True;receipt['worker']=worker;receipt['status']='STOPPED_P02_UNCERTAINTY_PREFIX_PRESERVED'
        shutil.copyfile(out/'worker-inspect.json',out/'economic-worker-inspect.json')
        shutil.copyfile(out/'worker.log',out/'economic-worker.log')
        if (out/'book/checkpoint.json.gz').is_file() and not worker['oom_killed']:
            audit=temp/'p02-uncertainty-independent-review';audit.mkdir(mode=0o700)
            name='capital-system-factual-p02-review-'+os.environ['GITHUB_RUN_ID']+'-1'
            reviewer=stopped_run(cmd(name,'review',audit),name,audit,deadline=request['review_wait_seconds'],inspector=inspect)
            receipt['reviewer']=reviewer;shutil.copytree(audit,out/'independent-review-stop')
            if reviewer['exit_code']==0 and not reviewer['oom_killed']:
                proof=json.loads((audit/'core-review.json').read_bytes())
                for name in ('core-review.json','uncertainty-certificate-review.json','completion-position-guard-review.json','common-factual-and-uncertainty-basis.json'):
                    shutil.copyfile(audit/name,out/name)
                receipt['status']='COMPLETE_P02_UNCERTAINTY_SUFFIX_REVIEWED' if proof['complete'] and worker['exit_code']==0 else 'PARTIAL_P02_UNCERTAINTY_PREFIX_REVIEWED'
    except StopUnknown:
        receipt['status']='P02_UNCERTAINTY_REVIEW_STOP_UNKNOWN' if known else 'P02_UNCERTAINTY_WRITER_STOP_UNKNOWN'
    except Exception:
        receipt['status']='P02_UNCERTAINTY_REFUSED_KNOWN_PREFIX' if known else 'P02_UNCERTAINTY_REFUSED_BEFORE_STOP_PROOF'
        if known:(out/'driver-failure.txt').write_text(traceback.format_exc())
    args.output.parent.mkdir(parents=True,exist_ok=True)
    if known:
        receipt['encrypted_ancestor']=preserve_ancestor(old,out,spec)
        receipt['encrypted_output']=seal(out,args.output.parent/'p02-uncertainty.tar.crseal',key,args.request,'P02',
            stage='campaign-factual-suffix',protocol_sha256=request['protocol_sha256'])
    key=None;args.output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
    raise SystemExit(0 if receipt['status']=='COMPLETE_P02_UNCERTAINTY_SUFFIX_REVIEWED' else 2)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('request','staging','output'):p.add_argument('--'+n,type=Path,required=True)
    main(p.parse_args())
