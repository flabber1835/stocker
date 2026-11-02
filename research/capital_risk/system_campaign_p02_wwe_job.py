"""Own August P02 stock-conversion suffix with exact parent content retention."""
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
from system_campaign_p02_outcome_job import SOURCES as PRIOR
from system_campaign_p02_outcome_job import expected_request as inherited_request
from system_campaign_p02_continue_job import inspect as prior_inspect
from system_campaign_large_factual_admit import admit
from system_campaign_own_origin import capture as capture_origin
from system_campaign_content_reference import preserve as preserve_content_reference, reference, PATH as REFERENCE_PATH
from system_campaign_variants import build
from alpaca_fit_job import stopped_run, StopUnknown
from probe import check_context, memory_bytes
from stage import SECRET, PROTOCOL, IMAGE
from runtime_identity import EXECUTION_IMAGE
from seal import sha256_file
from system_campaign_sprint_facts import fetch_alias, PACKET_SOURCE_PATH
from system_campaign_facts import digest

HERE=Path(__file__).resolve().parent
SOURCES=tuple(dict.fromkeys((*PRIOR,
    'system_campaign_content_reference.py',
    'system_campaign_registry_extension.py',
    'system_campaign_six_model_preflight.py',
    'system_campaign_wwe_facts.py',
    'system_campaign_wwe_gate.py',
    'system_campaign_wwe_review.py',
    'system-campaign-wwe-tko-terminal-facts.json',
    'system-campaign-wwe-registry-extension.json',
    'system_campaign_p02_wwe_run.py',
    'system_campaign_p02_wwe_diagnostics.py',
    'system_campaign_p02_wwe_job.py',
    'wwe-transfer-requirements.lock',
    'system_campaign_wwe_import_probe.py',
)))


def expected_request():
    name='system-campaign-p02-wwe-predecessor.json'
    spec=json.loads((HERE/name).read_bytes())
    need(spec['arm']=='P02' and spec['run_id']==41194712101
         and spec['selected_session']=='2023-08-31' and len(spec['repairs'])==33
         and spec['outer_sha256']=='2a1093a890294ed0c4577cb38f98d51a93752afd52d5cdc74145e1984efd504d'
         and spec['parent_certificate_rows']==972
         and not spec.get('unadvanced_qualification_failure') and not spec.get('review_refusal'),
         'WWE_EXACT_OWN_ADMITTED_33_INPUT_PREDECESSOR')
    retained=reference(spec)
    value=inherited_request()
    value.update(predecessor_file=name,predecessor_sha256=sha256_file(HERE/name),
        predecessor_common_basis_sha256=spec['admitted_common_basis_sha256'],
        execution_mode='RETAINED_SIX_MODEL_WWE_STOCK_SUFFIX',
        wwe_catalog_sha256=sha256_file(HERE/'system-campaign-wwe-tko-terminal-facts.json'),
        wwe_registry_extension_sha256=sha256_file(HERE/'system-campaign-wwe-registry-extension.json'),
        metadata_dependencies_sha256=sha256_file(HERE/'wwe-transfer-requirements.lock'),
        metadata_import_probe_sha256=sha256_file(HERE/'system_campaign_wwe_import_probe.py'),
        preworker_failure_run_id=41199820226,
        preworker_failure_log_sha256='536e0659dc8794afea7a0f7a2d8697e87f5d981bef4d3a03469f99dfcbe94778',
        parent_content_reference_sha256=digest(retained),
        actual_refusal_sha256='28ffff2be7890ba9677fbed7b970ff4f2f6910cb7ee81c37d8922354075f934d',
        parent_certificate_rows=spec['parent_certificate_rows'],
        parent_guard_review_sha256=spec['completion_guard_review_sha256'],
        diagnostic_driver_sha256=sha256_file(HERE/'system_campaign_p02_wwe_diagnostics.py'),
        sources={n:sha256_file(HERE/n) for n in SOURCES})
    return value


def inspect(name,identity=None):
    result=prior_inspect(name,identity)
    mode='review' if '-review-' in name else 'economic'
    need(result['Config']['Cmd']==['-B','-u','/driver/system_campaign_p02_wwe_run.py',
        '--mode',mode,'--spec','/evidence/spec.json' if mode=='review' else '/out/spec.json',
        '--request','/driver/system-campaign-p02-wwe-request.json'],
        'WWE_EXACT_FINANCIAL_OR_REVIEW_ENTRYPOINT')
    return result


def main(args):
    check_context(os.environ);need(os.environ.get('GITHUB_RUN_ATTEMPT')=='1','WWE_NO_ECONOMIC_WORKFLOW_RERUN')
    request=json.loads(args.request.read_bytes());need(request==expected_request(),'WWE_EXACT_ECONOMIC_REQUEST')
    spec=json.loads((HERE/request['predecessor_file']).read_bytes())
    stage=json.loads(args.staging.read_bytes())
    need(stage['status']=='STAGING_PASSED' and stage['run_id']==os.environ['GITHUB_RUN_ID']
         and stage['source_commit']==os.environ['GITHUB_SHA'] and stage['protocol_sha256']==PROTOCOL
         and stage['runtime_image']==IMAGE and stage['execution_image']==EXECUTION_IMAGE
         and stage['source_files_verified']==514 and stage['members_verified']==591
         and stage['manifest_sha256']=='80cfdade1e2b78706af5881f89414cf1428cb08b364464275b606939c4d1fb4a'
         and stage['authenticated_before_parsing'] and stage['offline_image_source_verified']
         and stage['runtime_index_config_layer_chain_verified'] and not stage['replay_started'],
         'WWE_EXACT_ECONOMIC_STAGING')
    key=base64.b64decode(os.environ.pop(SECRET,''),validate=True);need(len(key)==32,'WWE_KEY')
    temp=Path(os.environ['RUNNER_TEMP']);frozen=temp/'capital-risk-stage-001/inputs'
    need(shutil.disk_usage(temp).free>=request['initial_min_disk_bytes'],'WWE_INITIAL_DISK_BUDGET')
    old=admit(spec,temp/'campaign-factual-transfer-p02-wwe-suffix',key,
              max_zip_bytes=request['source_archive_limit_bytes'])
    out=temp/'p02-wwe-financial-output';out.mkdir(mode=0o700)
    need(all((old/name).is_file() for name in ('core-review.json',
         'uncertainty-certificate.jsonl','correlation-inputs.jsonl.gz'))
         and (old/'common-factual-and-uncertainty-basis.json').is_file(),
         'WWE_EXACT_ADMITTED_CALENDAR_PREFIX_SUPPORT_BEFORE_WORKER')
    q=old/'core-review.json'
    need(sha256_file(q)==spec['review_sha256'],'WWE_ACTUAL_OLD_FINANCIAL_PREFIX_PROOF_BYTES')
    value=json.loads(q.read_bytes())
    need(value['status']=='PARTIAL_CORE_PREFIX_REVIEWED' and value['checkpoint_sha256']==spec['outer_sha256']
         and value['all_prefixes_verified'] and value['all_daily_factors_and_chains_verified']
         and value['counts']=={'formation':126,'daily':1426},'WWE_ACTUAL_OWN_FINANCIAL_PREFIX')
    need(json.loads((old/'common-factual-and-uncertainty-basis.json').read_bytes())['sha256']==request['predecessor_common_basis_sha256'],
         'WWE_ACTUAL_RETAINED_EFFECTIVE_COMMON_BASIS')
    need(sha256_file(old/'completion-position-guard-review.json')==request['parent_guard_review_sha256'],
         'ABIOMED_ACTUAL_PARENT_GUARD_PROOF_BYTES')
    source=temp/'p02-wwe-financial-source'
    binding=build(frozen/'source-fixed',source,json.loads((old/'source-bindings.json').read_bytes())['parameters'])
    need(binding==json.loads((old/'source-bindings.json').read_bytes()),'WWE_EXACT_FINANCIAL_SOURCE_TREE')
    capture_origin(old,old,out)
    retained_reference=preserve_content_reference(old,out,spec)
    need(retained_reference==reference(spec)
         and digest(retained_reference)==request['parent_content_reference_sha256'],
         'WWE_ACTUAL_HOSTED_PARENT_REFERENCE_VERIFIED_BEFORE_FINANCIAL_WORKER')
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
         'WWE_ECONOMIC_RESOURCE_GATE')
    receipt=dict(schema='research.system-p02-wwe-suffix-receipt/1',arm='P02',
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
        spring2023_cash_catalog_sha256=request['spring2023_cash_catalog_sha256'],
        h2_2023_cash_catalog_sha256=request['h2_2023_cash_catalog_sha256'],
        abiomed_contract_sha256=request['abiomed_contract_sha256'],
        chinook_contract_sha256=request['chinook_contract_sha256'],
        outcome_contract_sha256=request['outcome_contract_sha256'],
        actual_refusal_sha256=request['actual_refusal_sha256'],
        wwe_catalog_sha256=request['wwe_catalog_sha256'],
        wwe_registry_extension_sha256=request['wwe_registry_extension_sha256'],
        parent_content_reference=dict(path=REFERENCE_PATH,bytes=(out/REFERENCE_PATH).stat().st_size,
                                      sha256=sha256_file(out/REFERENCE_PATH)),
        parent_certificate_rows=request['parent_certificate_rows'],
        parent_guard_review_sha256=request['parent_guard_review_sha256'],
        diagnostic_driver_sha256=request['diagnostic_driver_sha256'],
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
        result[result.index('/driver/full_system_core.py'):]=['/driver/system_campaign_p02_wwe_run.py',
            '--mode',mode,'--spec','/evidence/spec.json' if mode=='review' else '/out/spec.json',
            '--request','/driver/system-campaign-p02-wwe-request.json']
        return result
    known=False
    try:
        name='capital-system-factual-p02-worker-'+os.environ['GITHUB_RUN_ID']+'-1'
        worker=stopped_run(cmd(name,'economic',out),name,out,deadline=request['financial_wait_seconds'],inspector=inspect)
        known=True;receipt['worker']=worker;receipt['status']='STOPPED_P02_WWE_PREFIX_PRESERVED'
        shutil.copyfile(out/'worker-inspect.json',out/'economic-worker-inspect.json')
        shutil.copyfile(out/'worker.log',out/'economic-worker.log')
        if (out/'book/checkpoint.json.gz').is_file() and not worker['oom_killed']:
            audit=temp/'p02-wwe-independent-review';audit.mkdir(mode=0o700)
            name='capital-system-factual-p02-review-'+os.environ['GITHUB_RUN_ID']+'-1'
            reviewer=stopped_run(cmd(name,'review',audit),name,audit,deadline=request['review_wait_seconds'],inspector=inspect)
            receipt['reviewer']=reviewer;shutil.copytree(audit,out/'independent-review-stop')
            if reviewer['exit_code']==0 and not reviewer['oom_killed']:
                proof=json.loads((audit/'core-review.json').read_bytes())
                for name in ('core-review.json','uncertainty-certificate-review.json','completion-position-guard-review.json','common-factual-and-uncertainty-basis.json'):
                    shutil.copyfile(audit/name,out/name)
                receipt['status']='COMPLETE_P02_WWE_SUFFIX_REVIEWED' if proof['complete'] and worker['exit_code']==0 else 'PARTIAL_P02_WWE_PREFIX_REVIEWED'
    except StopUnknown:
        receipt['status']='P02_WWE_REVIEW_STOP_UNKNOWN' if known else 'P02_WWE_WRITER_STOP_UNKNOWN'
    except Exception:
        receipt['status']='P02_WWE_REFUSED_KNOWN_PREFIX' if known else 'P02_WWE_REFUSED_BEFORE_STOP_PROOF'
        if known:(out/'driver-failure.txt').write_text(traceback.format_exc())
    args.output.parent.mkdir(parents=True,exist_ok=True)
    if known:
        receipt['encrypted_output']=seal(out,args.output.parent/'p02-wwe.tar.crseal',key,args.request,'P02',
            stage='campaign-factual-suffix',protocol_sha256=request['protocol_sha256'])
    key=None;args.output.write_text(json.dumps(receipt,indent=2)+'\n');print(json.dumps(receipt))
    raise SystemExit(0 if receipt['status']=='COMPLETE_P02_WWE_SUFFIX_REVIEWED' else 2)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ('request','staging','output'):p.add_argument('--'+n,type=Path,required=True)
    main(p.parse_args())
