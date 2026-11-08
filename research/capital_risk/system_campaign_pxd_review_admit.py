"""Exact compact corrected review for component qualification, never finance."""
import ast
import hashlib
import json
from pathlib import Path
import re

from full_system_benchmark import need
from system_campaign_facts import sha
import system_campaign_factual_admit as original
from system_campaign_pxd_facts import contract

CRYPTO_SHA='63660cd6b2567099db9cb3d1cd9a8b05a16d54ceb1aa50a3f3acfa6d91bd6bd4'
OUTER='1f42c8345ac1df9cb1cbddff84cb2624a6fb9087ee5d3d663f528fd13ca341f0'


def scope(spec):
    need(sha((json.dumps(spec,indent=2,sort_keys=True)+'\n').encode())
             =='88ba93fc870cc9a53fe3dbd2b382ad8a1b68f729d27713157d7cf445f90fb35a'
         and spec['schema']=='research.p02-corrected-review-component-admission/1'
         and spec['review_only'] is True and spec['financial_resume_authorized'] is False
         and spec['financial_admission'] is False and spec['run_id']==41218813778
         and spec['head']=='2cdb37b29d546d3063f79b890b474e68f285cbca'
         and spec['artifact_id']==13049271803 and spec['zip_bytes']==120767
         and spec['receipt_sha256']=='6c09c50a7714ff917d06aa4568795d930853701cd9d052e320df4ffed7dbf040'
         and spec['manifest_metadata_sha256']=='4da76fd7dba524850039c71afd55f6c3952d5b1684ba54067f073d8333cd1174'
         and spec['reviewed_checkpoint_sha256']==OUTER and spec['inventory_members']==21,
         'PXD_REVIEW_ADMISSION_EXACT_NONFINANCIAL_CORRECTED_ARTIFACT')


def stopped_function():
    path=Path(__file__).parent/'system_campaign_p02_close_diagnostics.py'
    need(sha(path.read_bytes())==contract()['inherited_sources'][path.name],
         'PXD_REVIEW_ADMISSION_ORIGINAL_STOP_FENCES_UNCHANGED')
    fn,=[n for n in ast.parse(path.read_bytes()).body if isinstance(n,ast.FunctionDef) and n.name=='stopped']
    sites=[n for n in ast.walk(fn) if isinstance(n,ast.Compare) and ast.unparse(n.left)=="c['Cmd']"]
    need(len(sites)==1,'PXD_REVIEW_ADMISSION_ONE_EXACT_ENTRYPOINT_FENCE')
    sites[0].comparators=[ast.parse("['-B','-u','/driver/system_campaign_close_review_run.py','--request','/driver/system-campaign-p02-close-review-request.json']",mode='eval').body]
    namespace=dict(need=need,re=re,SECRET='CAPITAL_RISK_RESEARCH_KEY_20261027')
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<unchanged-stop-fences-exact-corrected-review-entry>','exec'),namespace)
    return namespace['stopped']


def prove(spec,manifest,receipt,inventory,root):
    scope(spec)
    raw=(json.dumps(manifest,indent=2)+'\n').encode()
    need(sha(raw)==spec['manifest_metadata_sha256'] and len(inventory)==21
         and sum(v['bytes'] for v in inventory.values())<=16*1024**2,
         'PXD_REVIEW_ADMISSION_ALL_EXACT_COMPACT_MEMBERS')
    need(receipt['status']=='STOPPED_CLOSE_PREFIX_REVIEWED_NO_FINANCIAL_REPLAY'
         and all(receipt[k] is False for k in ('financial_replay_started','financial_book_included',
             'financial_resume_authorized','production_contacted'))
         and receipt['reviewed_checkpoint_sha256']==OUTER,
         'PXD_REVIEW_ADMISSION_ACTUAL_ZERO_FINANCIAL_SCOPE')
    stopped_function()(json.loads((root/'worker-inspect.json').read_bytes()),receipt['reviewer'],
        'review',str(spec['run_id']),'system-campaign-p02-close-review-request.json')
    need(receipt['reviewer']['exit_code']==0 and receipt['reviewer']['oom_killed'] is False,
         'PXD_REVIEW_ADMISSION_ACTUAL_SUCCESSFUL_STOP')
    proof=json.loads((root/'close-review-materialization.json').read_bytes())
    core=json.loads((root/'core-review.json').read_bytes())
    need(proof['checkpoint_sha256']==core['checkpoint_sha256']==OUTER
         and proof['financial_sessions_advanced']==0 and proof['actual_nested_canonical_repair_loaded'] is True
         and core['counts']==dict(formation=126,daily=1592) and core['accounting_snapshots']==3436
         and core['all_prefixes_verified'] is True and core['all_daily_factors_and_chains_verified'] is True,
         'PXD_REVIEW_ADMISSION_ACTUAL_COMPLETED_CORRECTION_PROOF')


def admit(spec,root,key):
    scope(spec)
    raw=Path(original.__file__).read_bytes()
    need(sha(raw)==CRYPTO_SHA,'PXD_REVIEW_ADMISSION_ORIGINAL_CRYPTO_SOURCE')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='admit']
    boundaries=[i for i,n in enumerate(fn.body) if isinstance(n,ast.For)
        and ast.unparse(n.iter)=="spec['inspections'].items()"]
    need(len(boundaries)==1,'PXD_REVIEW_ADMISSION_ONE_FINANCIAL_CLASSIFIER_BOUNDARY')
    fn.body=fn.body[:boundaries[0]]+ast.parse('_prove_compact(spec,m,r,inventory,dest)\nreturn dest').body
    namespace=dict(vars(original),_prove_compact=prove)
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
        '<unchanged-crypto-prefix-with-explicit-compact-review-proof>','exec'),namespace)
    return namespace['admit'](spec,root,key,max_zip_bytes=256*1024**2)
