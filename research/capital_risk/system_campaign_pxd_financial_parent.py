"""Separate original financial, corrected-review and component authorities."""
import ast
import gzip
import json
from pathlib import Path
import re
import shutil

from full_system_benchmark import need, save
from system_campaign_facts import digest, sha
import system_campaign_factual_admit as crypto
from system_campaign_close_review_admit import admit as admit_original
from system_campaign_pxd_review_admit import admit as admit_corrected
from system_campaign_pxd_pause import adoption

HERE=Path(__file__).resolve().parent
SPEC='system-campaign-p02-pxd-predecessor.json'
SPEC_SHA='4b4f70e74af93608ecee318a6ba9e4dea115688529e638d39c7d494f7b355fdb'
PATH='lineage/composite-financial-parent-reference.json'
ALIASES={
    'core-review.json':'core-review.json',
    'completion-position-guard-review.json':'completion-position-guard-review.json',
    'uncertainty-certificate-review.json':'uncertainty-certificate-review.json',
    'common-factual-and-uncertainty-basis.json':'common-factual-and-uncertainty-basis.json',
    'independent-review-stop/close-lineage-review.json':'close-lineage-review.json',
}


def document(name):
    need(Path(name).name==name,'PXD_PARENT_EXACT_PUBLIC_DOCUMENT_NAME')
    return json.loads((HERE/name).read_bytes())


def scope(spec):
    need(sha((json.dumps(spec,indent=2,sort_keys=True)+'\n').encode())==SPEC_SHA
         and spec['schema']=='research.p02-composite-financial-predecessor/1'
         and spec['financial_resume_authorized'] is True and spec['review_only'] is False
         and spec['new_origin'] is False and spec['source_conversion'] is False
         and spec['production_contacted'] is False,'PXD_PARENT_DISTINCT_EXACT_FINANCIAL_AUTHORITY')
    original=document(spec['source_financial_file'])
    corrected=document(spec['corrected_review_file'])
    qualified=document(spec['qualified_component_file'])
    for key,prefix in (('source_financial_file','source_financial'),
                       ('corrected_review_file','corrected_review'),
                       ('qualified_component_file','qualified_component')):
        need(sha((HERE/spec[key]).read_bytes())==spec[prefix+'_sha256'], 'PXD_PARENT_EACH_AUTHORITY_DOCUMENT_HASH')
    for key in ('arm','stage','run_id','head','artifact_id','protocol_sha256','selected_checkpoint',
                'selected_file','selected_session','outer_sha256','inner_sha256','state_sha256',
                'input_sha256','base','journals','repairs','source_binding_sha256'):
        need(spec[key]==original[key], 'PXD_PARENT_EXACT_ORIGINAL_FINANCIAL_FIELD_'+key)
    need(original['review_only'] is True and original['financial_resume_authorized'] is False
         and original['inspections']['economic-worker-inspect.json']['exit_code']==1
         and original['inspections']['independent-review-stop/worker-inspect.json']['exit_code']==1
         and corrected['review_only'] is True and corrected['financial_resume_authorized'] is False
         and qualified['financial_predecessor_authorized'] is False,
         'PXD_PARENT_ALL_ORIGINAL_LIMITATIONS_AND_FAILURES_RETAINED')
    need(spec['selected_session']=='2024-04-30' and spec['measured_closes']==1592
         and spec['formation_closes']==126 and len(spec['repairs'])==36
         and spec['parent_certificate_rows']==1138
         and (spec['original_writer_exit_code'],spec['original_reviewer_exit_code'],
              spec['corrected_reviewer_exit_code'])==(1,1,0), 'PXD_PARENT_EXACT_OWN36_AND_SEPARATE_REVIEW')
    full=spec['full_client_admission']
    need(full['review_sha256']=='270ac2e09e684c203011991d42d9cbf7ca705c5ba9b7b067adb8a747e7809f97'
         and all(full[key] is True for key in ('all172_members_retained','all_parent_content_verified',
                  'all_accounting_and_daily_chains_reviewed','financial_admission'))
         and full['accounting_snapshots']==3436,'PXD_PARENT_COMPLETE_ACTUAL_CLIENT_ADMISSION')
    need(set(spec['review_aliases'])==set(ALIASES)
         and all(value['source_member']==ALIASES[name] for name,value in spec['review_aliases'].items()),
         'PXD_PARENT_ONLY_FIVE_NONFINANCIAL_REVIEW_ALIASES')
    return original,corrected,qualified


def reference(spec):
    original,corrected,qualified=scope(spec)
    return dict(schema='research.composite-financial-parent-content-reference/1',arm='P02',
        selected_outer_sha256=spec['outer_sha256'],selected_inner_sha256=spec['inner_sha256'],
        selected_state_sha256=spec['state_sha256'],selected_input_sha256=spec['input_sha256'],
        selected_file=spec['selected_file'],source_binding_sha256=spec['source_binding_sha256'],
        complete_journals_sha256=digest(spec['journals']),complete_repairs_sha256=digest(spec['repairs']),
        composite_spec_sha256=digest(spec),original_financial_artifact=original,
        corrected_review_artifact=corrected,qualified_component=qualified,
        full_client_admission=spec['full_client_admission'],review_aliases=spec['review_aliases'],
        original_failed_reviewer_relabelled=False,qualification_copy_is_predecessor=False,
        duplicate_parent_transport_bytes_included=False,production_contacted=False)


def qualified_proof(spec,manifest,receipt,inventory,root):
    need(spec==document('system-campaign-pxd-qualified-component.json')
         and spec['run_id']==41228433478 and len(inventory)==15
         and sha((json.dumps(manifest,indent=2)+'\n').encode())==spec['manifest_metadata_sha256'],
         'PXD_PARENT_EXACT_COMPLETED_COMPONENT_INVENTORY')
    need(receipt['status']=='STOPPED_PXD_ZERO_SESSION_STARTUP_QUALIFIED'
         and receipt['financial_sessions_advanced']==0
         and all(receipt[k] is False for k in ('financial_replay_authorized',
              'financial_resume_from_qualification_copy_authorized','financial_book_included','production_contacted')),
         'PXD_PARENT_COMPONENT_LIMITATIONS_REMAIN_NONFINANCIAL')
    raw=(HERE/'system_campaign_p02_close_diagnostics.py').read_bytes()
    old_request=document('system-campaign-pxd-qualification-request.json')
    need(sha(raw)==old_request['sources']['system_campaign_p02_close_diagnostics.py'],
         'PXD_PARENT_UNCHANGED_COMPONENT_STOP_FENCES')
    need(all(sha((HERE/name).read_bytes())==expected for name,expected in old_request['sources'].items()),
         'PXD_PARENT_ALL277_ACTUALLY_QUALIFIED_SOURCE_BYTES_UNCHANGED')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='stopped']
    site,=[n for n in ast.walk(fn) if isinstance(n,ast.Compare) and ast.unparse(n.left)=="c['Cmd']"]
    site.comparators=[ast.parse("['-B','-u','/driver/system_campaign_pxd_qualification_run.py','--request','/driver/system-campaign-pxd-qualification-request.json']",mode='eval').body]
    namespace=dict(need=need,re=re,SECRET='CAPITAL_RISK_RESEARCH_KEY_20261027')
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
                 '<unchanged-stop-fences-exact-qualified-PXD-entry>','exec'),namespace)
    namespace['stopped'](json.loads((root/'worker-inspect.json').read_bytes()),receipt['worker'],
                         'review',str(spec['run_id']),'system-campaign-pxd-qualification-request.json')
    zero=json.loads((root/'zero-session-startup-proof.json').read_bytes())
    summary=json.loads((root/'qualification-summary.json').read_bytes())
    need(receipt['worker']['exit_code']==0 and not receipt['worker']['oom_killed']
         and zero['input_adoptions']==1 and zero['canonical_adoption_checkpoint_writes']==2
         and zero['attempted_financial_transitions']==0
         and zero['qualification_checkpoint_sha256']==spec['qualification_checkpoint_sha256']
         and summary['source_checkpoint_sha256']==spec['original_checkpoint_sha256']
         and summary['actual_new_input_sha256']==spec['qualified_overlay_sha256']
         and summary['common_basis_sha256']==spec['common_basis_sha256']
         and summary['typed_inputs']==8 and summary['completed']==1592
         and summary['actual_all_prefixes_and_tails_verified'] is True,
         'PXD_PARENT_ACTUAL_SUCCESSFUL_COMPONENT_STARTUP_AND_PREFIX_PROOF')


def admit_qualification(spec,root,key):
    raw=Path(crypto.__file__).read_bytes()
    need(sha(raw)=='63660cd6b2567099db9cb3d1cd9a8b05a16d54ceb1aa50a3f3acfa6d91bd6bd4',
         'PXD_PARENT_ORIGINAL_CRYPTO_PREFIX_UNCHANGED')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='admit']
    boundary,=[i for i,n in enumerate(fn.body) if isinstance(n,ast.For)
               and ast.unparse(n.iter)=="spec['inspections'].items()"]
    fn.body=fn.body[:boundary]+ast.parse('_qualified(spec,m,r,inventory,dest)\nreturn dest').body
    namespace=dict(vars(crypto),_qualified=qualified_proof)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<unchanged-crypto-with-distinct-nonfinancial-component-proof>','exec'),namespace)
    return namespace['admit'](spec,root,key,max_zip_bytes=256*1024**2)


def compose(spec,original,corrected,qualified,destination):
    scope(spec)
    need(not destination.exists() and original.resolve()!=destination.resolve(),
         'PXD_PARENT_NEW_DISJOINT_VIEW_ONLY')
    shutil.copytree(original,destination)
    for name,entry in spec['review_aliases'].items():
        raw=(corrected/entry['source_member']).read_bytes()
        need(len(raw)==entry['bytes'] and sha(raw)==entry['sha256'],'PXD_PARENT_EXACT_CORRECTED_ALIAS_BYTES')
        if name in ('core-review.json','completion-position-guard-review.json','uncertainty-certificate-review.json'):
            need(raw==(original/'independent-review-stop'/name).read_bytes(),
                 'PXD_PARENT_ALREADY_COMPLETED_ORIGINAL_REVIEW_OUTPUT_IDENTICAL')
        target=destination/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
    for name in ('book','provider-source'):
        for source in (original/name).rglob('*'):
            if source.is_file():
                need((destination/source.relative_to(original)).read_bytes()==source.read_bytes(),
                     'PXD_PARENT_EVERY_FINANCIAL_INPUT_AND_ARCHIVED_CHECKPOINT_EXACT')
    for name in ('source-bindings.json','uncertainty-certificate.jsonl','correlation-inputs.jsonl.gz'):
        need((destination/name).read_bytes()==(original/name).read_bytes(),
             'PXD_PARENT_FINANCIAL_SENSOR_AND_CAUSAL_DATA_BYTES_UNCHANGED')
    cp=json.loads(gzip.decompress((original/spec['selected_checkpoint']).read_bytes()))
    qcp=json.loads(gzip.decompress((qualified/'qualification-checkpoint.json.gz').read_bytes()))
    zero=json.loads((qualified/'zero-session-startup-proof.json').read_bytes())
    qualified_spec=document(spec['qualified_component_file'])
    need(adoption(qcp,cp,qualified_spec['qualified_overlay_sha256'],'2024-05-02')
         ==zero['exact_canonical_boundary_event'],'PXD_PARENT_QUALIFICATION_BOUND_TO_ORIGINAL_UNCHANGED_STATE')
    need(cp['sha256']==spec['outer_sha256'] and cp['completed']==1592
         and json.loads((destination/'common-factual-and-uncertainty-basis.json').read_bytes())['sha256']
             ==spec['admitted_common_basis_sha256'],'PXD_PARENT_SELECTED_ORIGINAL_CP_AND_SEVEN_MODEL_BASIS')
    save(destination/'composite-parent-admission.json',reference(spec))
    return destination


def admit(spec,root,key,*,max_zip_bytes=512*1024**2):
    original_spec,corrected_spec,qualified_spec=scope(spec)
    need(max_zip_bytes==512*1024**2,'PXD_PARENT_FINITE_ORIGINAL_ARCHIVE_BOUND')
    root=Path(root)
    original=admit_original(original_spec,root.with_name(root.name+'-original'),key)
    corrected=admit_corrected(corrected_spec,root.with_name(root.name+'-corrected'),key)
    qualified=admit_qualification(qualified_spec,root.with_name(root.name+'-qualified'),key)
    crypto.hosted_destination(root)
    return compose(spec,original,corrected,qualified,root)


def preserve(old,out,spec):
    value=reference(spec)
    need(json.loads((old/'composite-parent-admission.json').read_bytes())==value,
         'PXD_PARENT_ACTUAL_AUTHENTICATED_COMPOSITION_REQUIRED')
    target=out/PATH
    need(not target.exists(),'PXD_PARENT_COMPOSITE_REFERENCE_NEVER_OVERWRITES_OLD_REFERENCE')
    save(target,value)
    return value
