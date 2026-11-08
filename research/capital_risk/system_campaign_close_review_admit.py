"""Exact failed-output admission for hosted review only; no financial resume."""
import gzip
import json
from pathlib import Path
from types import FunctionType

from full_system_benchmark import need
from system_campaign_facts import sha
import system_campaign_factual_admit as original
from system_campaign_p02_close_diagnostics import stopped

SOURCE_SHA='63660cd6b2567099db9cb3d1cd9a8b05a16d54ceb1aa50a3f3acfa6d91bd6bd4'
DRIVER_SHA='1669a45a0010287289e0b0a59c7e85142e00aff50ec55d1ab4e03e63ff39c00c'
DIAGNOSTIC_SHA='dbd44d546239883382c9e7825beafbae11a30a0f7eddfef7820ba2d29504d544'
REASON='CLOSE_REVIEW_CODEC_NOT_MATERIALIZED'
OUTER='1f42c8345ac1df9cb1cbddff84cb2624a6fb9087ee5d3d663f528fd13ca341f0'


def require_review_only(spec):
    need(spec.get('review_only') is True and spec.get('financial_resume_authorized') is False
         and spec['arm']=='P02' and spec['stage']=='campaign-factual-suffix'
         and spec.get('review_refusal')==REASON
         and spec['run_id']==41214327942
         and spec['head']=='1d339cfd1426a90b6fd3c4cd8c8100829ad39c57'
         and spec['artifact_id']==13048057396 and spec['zip_bytes']==158619057
         and spec['zip_sha256']=='028f0c7da0d7a21bdefeb4bebefb0976d313c8ad5b9676a10a79c89bd949ce3d'
         and spec['request_sha256']=='bf01f5d065c4a00b006f59f70138cc8ad3ea716a91c35b3cd5a75a3ad0bc91a0'
         and spec['receipt_schema']=='research.system-p02-close-suffix-receipt/1'
         and spec['outer_sha256']==OUTER and spec['selected_session']=='2024-04-30',
         'CLOSE_REVIEW_ONLY_EXACT_ACTUAL_FAILED_OUTPUT_NOT_FINANCIAL_ADMISSION')


def prove(spec, inventory, root):
    require_review_only(spec)
    need(sha((Path(__file__).parent/'system_campaign_p02_close_run.py').read_bytes())==DRIVER_SHA
         and sha((Path(__file__).parent/'system_campaign_p02_close_diagnostics.py').read_bytes())==DIAGNOSTIC_SHA,
         'CLOSE_REVIEW_ONLY_EXACT_ORIGINAL_DIAGNOSTIC_AND_REVIEW_SOURCE')
    need(len(inventory)==spec['inventory_members']==172, 'CLOSE_REVIEW_ONLY_FULL_ACTUAL_INVENTORY')
    for role,name in (('worker','economic-worker-inspect.json'),('review','independent-review-stop/worker-inspect.json')):
        x=json.loads((root/name).read_bytes())
        need(x['State']['ExitCode']==spec['inspections'][name]['exit_code']==1,
             'CLOSE_REVIEW_ONLY_ORIGINAL_NONZERO_STOPS_REMAIN_EXPLICIT')
        stopped(x,dict(stopped=True,oom_killed=False,exit_code=1),role,str(spec['run_id']),
                'system-campaign-p02-close-request.json')
    raw=(root/'independent-review-stop/worker.log').read_bytes()
    need(sha(raw)==spec['review_refusal_log_sha256']
         and 'close_model, = closing.objects' in raw.decode('utf8')
         and 'ValueError: not enough values to unpack (expected 1, got 0)' in raw.decode('utf8'),
         'CLOSE_REVIEW_ONLY_EXACT_ACTUAL_MATERIALIZATION_FAILURE')
    cp=json.loads(gzip.decompress((root/spec['selected_checkpoint']).read_bytes()))
    core_raw=(root/'independent-review-stop/core-review.json').read_bytes();core=json.loads(core_raw)
    need(sha(core_raw)==spec['review_sha256'] and cp['sha256']==core['checkpoint_sha256']==OUTER
         and cp['source_cursor']=='2024-04-30' and cp['completed']==1592 and len(cp['repairs'])==36
         and core['status']=='PARTIAL_CORE_PREFIX_REVIEWED'
         and core['counts']=={'formation':126,'daily':1592}
         and core['all_prefixes_verified'] is True and core['all_daily_factors_and_chains_verified'] is True,
         'CLOSE_REVIEW_ONLY_ACTUAL_PRE_FAILURE_CORE_PROOF_AND_UNCHANGED_TARGET')
    need(sha((root/'independent-review-stop/uncertainty-certificate-review.json').read_bytes())==spec['interval_review_sha256'],
         'CLOSE_REVIEW_ONLY_ACTUAL_COMPLETE_CONTROLLER_PROOF_BYTES')


def admit(spec, root, key):
    require_review_only(spec)
    need(sha(Path(original.__file__).read_bytes())==SOURCE_SHA,
         'CLOSE_REVIEW_ONLY_UNCHANGED_ORIGINAL_CRYPTO_SOURCE')
    fn=original.admit
    need(fn.__closure__ is None, 'CLOSE_REVIEW_ONLY_ORIGINAL_ADMISSION_WITHOUT_CLOSURE')
    checked=FunctionType(fn.__code__,dict(fn.__globals__,prove_review_refusal=prove),fn.__name__,fn.__defaults__)
    checked.__kwdefaults__=fn.__kwdefaults__
    return checked(spec,root,key,max_zip_bytes=512*1024**2)
