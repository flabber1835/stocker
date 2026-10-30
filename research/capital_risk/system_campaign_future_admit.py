"""Explicit review-refusal admission for this exact preserved P02 incident only."""
import gzip,json
from full_system_benchmark import need
from seal import sha256_file
import system_campaign_factual_admit as original


def prove(spec,inventory,root):
    if spec['review_refusal']=='FOLLOWING_FUTURE_APHA_CONFLICT':
        from system_campaign_future_amendment import validate_conflict,documents,OUTER
        need(spec['receipt_schema']=='research.system-p02-uncertainty-suffix-receipt/1'
             and spec['run_id']==41120539423 and spec['arm']=='P02'
             and spec['selected_session']=='2021-03-31' and spec['outer_sha256']==OUTER,
             'FUTURE_APHA_EXACT_FAILED_REVIEW_SCOPE')
        log=root/'independent-review-stop/worker.log'
        need(sha256_file(log)==spec['review_log_sha256']
             and log.read_text().rstrip().endswith('ValueError: REFUSED_FULL_SYSTEM_COMMON_BASIS_NO_CONFLICTING_TERM')
             and 'core-review.json' not in inventory and 'common-factual-and-uncertainty-basis.json' not in inventory,
             'FUTURE_APHA_ORIGINAL_COMMON_BASIS_REFUSAL_NOT_RELABELED')
        name='independent-review-stop/core-review.json'
        need(sha256_file(root/name)==spec['review_sha256'],'FUTURE_APHA_ACTUAL_FINANCIAL_REVIEW_BYTES')
        review=json.loads((root/name).read_bytes())
        need(review['counts']=={'formation':126,'daily':817} and review['accounting_snapshots']==1886
             and review['checkpoint_sha256']==OUTER and review['all_prefixes_verified']
             and review['all_daily_factors_and_chains_verified'] and not review['complete'],
             'FUTURE_APHA_ACTUAL_OWN_FINANCIAL_PREFIX_PASSED')
        name='independent-review-stop/uncertainty-certificate-review.json'
        need(sha256_file(root/name)==spec['interval_review_sha256'],'FUTURE_APHA_ACTUAL_INTERVAL_REVIEW_BYTES')
        interval=json.loads((root/name).read_bytes())
        need(interval['checkpoint_sha256']==OUTER and interval['rows']==363 and interval['comparisons']==704
             and interval['financial_path_invariant_over_declared_sensor_interval'],
             'FUTURE_APHA_ACTUAL_INTERVAL_PREFIX_PASSED')
        name='independent-review-stop/reviewed-recovered-tail-proof.json'
        need(sha256_file(root/name)==spec['reviewed_tail_proof_sha256'],'FUTURE_APHA_OLD_TAIL_REVIEW_BYTES')
        cp=json.loads(gzip.decompress((root/spec['selected_checkpoint']).read_bytes()))
        validate_conflict(cp,documents(root,cp))
        need(all(spec['inspections'][n]['exit_code']==1 for n in
             ('economic-worker-inspect.json','independent-review-stop/worker-inspect.json')),
             'FUTURE_APHA_ACTUAL_FAILED_STOPS_PRESERVED')
        return
    raise ValueError('REFUSED_FUTURE_AMENDMENT_UNDECLARED_ADMISSION')


def admit(spec,root,key,*,max_zip_bytes):
    need(spec.get('review_refusal')=='FOLLOWING_FUTURE_APHA_CONFLICT',
         'FUTURE_AMENDMENT_EXPLICIT_TYPED_ADMISSION')
    saved=original.prove_review_refusal
    original.prove_review_refusal=prove
    try:return original.admit(spec,root,key,max_zip_bytes=max_zip_bytes)
    finally:original.prove_review_refusal=saved
