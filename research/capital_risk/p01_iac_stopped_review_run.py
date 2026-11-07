"""Fixed hosted review-only entry; never a financial startup or transition."""
import argparse,traceback
from pathlib import Path
from full_system_benchmark import need,save
from seal import sha256_file
from p01_iac_stopped_review_target import HERE,TARGET,target,read,plain
REQUEST='p01_iac_stopped_review_request.json'
ADAPTER_SHA='6254996408ae4915e84089dcfed68a1f9bd075e6c0168cdf82afb75fe31bfe23'

def main(args):
    from p01_iac_stopped_review_job import validate_worker_request
    request=validate_worker_request(HERE/REQUEST)
    need(args.spec==Path('/out/spec.json'),'STOPPED_REVIEW_FIXED_SPEC_PATH')
    from full_system_core import hosted
    hosted()
    from p01_iac_stopped_review_transport import verify_tree
    spec=target();out=Path('/out');evidence=Path('/evidence')
    need(read(out/'target.json')==read(HERE/TARGET),'STOPPED_REVIEW_TARGET_COPY_EXACT')
    auth=plain(read(out/'review-authentication.json'));verify_tree(evidence,spec,auth)
    execution=plain(read(out/'review-execution.json'))
    need(execution['schema']=='research.p01-stopped-evidence-review-execution/1'
        and execution['request_sha256']==sha256_file(HERE/REQUEST) and execution['source_count']==len(request['sources'])
        and execution['target_request_sha256']==spec['original']['request_sha256']
        and execution['financial_authority'] is False and execution['qualification_or_financial_replay_authorized'] is False,
        'STOPPED_REVIEW_EXECUTION_TARGET_ENVELOPES_SEPARATE')
    # Only after full old transport/tree authentication may canonical restore imports occur.
    import p01_iac_namespace_review_recovery as adapter
    from p01_iac_unit_contract import specification,SPEC
    need(sha256_file(Path(adapter.__file__))==ADAPTER_SHA and read(args.spec)==read(HERE/SPEC),'STOPPED_REVIEW_EXACT_ORDER_ADAPTER_AND_OLD628_SPEC')
    try:
        result=adapter.review(specification(),out,evidence)
        report=out/'iac-unit-financial-review.json'
        need(result['reference_reuse_review']['actual_new_request_sha256']==spec['original']['request_sha256']
            and result['reference_reuse_review']['actual_new_driver_source_count']==515
            and result['qualification_state_adopted'] is False and result['financial_predecessor_admitted'] is False,
            'STOPPED_REVIEW_RESULT_TARGET_515_NOT_NEW_EXECUTION')
        save(out/'review-result-link.json',dict(schema='research.p01-stopped-review-result-link/1',execution_request_sha256=sha256_file(HERE/REQUEST),
            target_request_sha256=spec['original']['request_sha256'],adapter_sha256=ADAPTER_SHA,
            report=dict(bytes=report.stat().st_size,sha256=sha256_file(report)),review_returned_without_exception=True,financial_authority=False))
        return 0
    except BaseException:
        with (out/'worker-error.txt').open('x',encoding='utf8',newline='\n') as stream:stream.write(traceback.format_exc())
        raise

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--spec',type=Path,required=True);raise SystemExit(main(parser.parse_args()))
