"""Independent hosted read-only accounting/policy reviewer; no account imports."""
import argparse,csv,gzip,hashlib,itertools,json,os
from pathlib import Path
from fractions import Fraction as Q
import risk_review_math as math
from risk_profiles import selected
from risk_metrics import windows,development_record
from weighted_job import inspect_weighted

def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def normalized(finance,expected_source):
    value=json.loads(json.dumps(finance));math.need(value['account']['source_sha256']==expected_source,'EXACT_COMPARATOR_SOURCE')
    # The only allowed differences. Their canonical chains are independently checked.
    del value['account']['source_sha256'];del value['account']['chain_sha256'];del value['account_state_sha256']
    return value

def compare_oracle(actual,prior,source,prior_source):
    count=0
    for left,right in itertools.zip_longest(math.rows(actual/'book/daily.jsonl.gz'),math.rows(prior/'daily.jsonl.gz')):
        math.need(left is not None and right is not None and left['session']==right['session'],'ORACLE_DAILY_AXIS')
        math.need(normalized(left['finance'],source)==normalized(right['finance'],prior_source),'ORACLE_ALL_ECONOMIC_FIELDS');count+=1
    math.need(count==4639,'ORACLE_COMPLETE_PATH')
    # The account event-state/source identity and chain only may differ here.
    events=0
    for left,right in itertools.zip_longest(math.rows(actual/'book/events.jsonl.gz'),math.rows(prior/'events.jsonl.gz')):
        math.need(left is not None and right is not None,'ORACLE_EVENT_AXIS')
        for item,expected in ((left,source),(right,prior_source)):
            math.need(item['record']['state_without_chain']['source_sha256']==expected,'ORACLE_EVENT_SOURCE')
            del item['record']['state_without_chain']['source_sha256'];del item['record']['chain_sha256']
        math.need(left==right,'ORACLE_EVERY_EVENT_ECONOMIC_FIELD');events+=1
    return dict(status='EVERY_ECONOMIC_FIELD_EXACT',daily=count,events=events,
        exact_financial_exclusions=['$.account.source_sha256','$.account.chain_sha256','$.account_state_sha256'])

def main():
    p=argparse.ArgumentParser();p.add_argument('--profile',required=True);p.add_argument('--writer-name',required=True)
    for n in ('actual','source','bundle','qualified','output'):p.add_argument('--'+n,type=Path,required=True)
    a=p.parse_args();math.need(os.environ.get('HOLDING_QUAL_HOSTED')=='1','REFUSED_LOCAL_HOSTED_REVIEW')
    profile=selected(a.profile);a.output.mkdir(exist_ok=False);stop=inspect_weighted(a.actual.parent/(a.writer_name+'-inspect.json'),a.writer_name)
    math.need(stop['exit_code']==0 and not stop['oom'],'ACTUAL_PROFILE_STOP_FIRST')
    binding=json.loads((a.actual/'source-bindings.json').read_bytes());b=binding['binding'];source_sha=binding['source_sha256']
    math.need(source_sha==math.digest(b) and b['profile']==profile.model_dump(mode='json'),'PROFILE_SOURCE_COMMITMENT')
    here=Path(__file__).parent
    for name,h in {**b['original_sources'],**b['research_sources']}.items():math.need(sha(here/name)==h,'ACTUAL_PROFILE_SOURCE_'+name)
    for name,h in b['canonical'].items():math.need(sha(a.source.parent/'source-fixed'/name)==h,'ACTUAL_FROZEN_CANONICAL_SOURCE')
    math.need(sha(a.actual/'identity/identity-bindings.jsonl')==sha(a.qualified/'controls/comparison/identity/identity-bindings.jsonl'),'ORIGINAL_PERMANENT_IDENTITY_BINDINGS')
    math.OUT=a.actual;math.ORIGINAL=a.source;math.PRICES=a.qualified/'price/qualification/prices/price-bindings.jsonl'
    with gzip.open(a.bundle/'cash.csv.gz','rt') as f:cash={r['session']:r for r in csv.DictReader(f)}
    review,values=math.review_book('book',cash,profile=profile)
    math.need(review['records']==4639 and review['formation_records']==126 and review['uncommitted_event_tail_records']==0
        and all(s['tail_bytes']==0 for s in review['prefix_review']['journals'].values()),'COMPLETE_PROFILE_ACCOUNTING')
    cp=math.gzload(a.actual/'book/checkpoint.json.gz');math.need(cp['runtime']['source_sha256']==source_sha,'CURRENT_PROFILE_IDENTITY')
    retained=json.loads((a.actual/'book/retained-checkpoint-review.json').read_bytes());math.need(retained['checkpoints']==len(retained['files']) and retained['all_tails_zero'],'HOSTED_RESTORE_SCOPE')
    for name,h in retained['files'].items():math.need(sha(a.actual/'book'/name)==h,'ACTUAL_TYPED_RESTORED_FILE')
    baseline_path=a.qualified/'controls/comparison/H0';baseline_values=[]
    for r in math.rows(baseline_path/'daily.jsonl.gz'):baseline_values.append((r['session'],r['finance']['nav']))
    result=dict(status='INDEPENDENT_FULL_PROFILE_REVIEW_PASSED',profile=profile.model_dump(mode='json'),source_sha256=source_sha,
        writer_stop=stop,accounting=review,typed_checkpoint_files=retained['checkpoints'],all_actual_typed_files_hash_checked=True,
        metrics=windows(values),baseline_metrics=windows(baseline_values),production_contacted=False,local_account_or_core_executed=False)
    if profile.family in ('ORACLE_H0','ORACLE_P2'):
        prior=baseline_path if profile.family=='ORACLE_H0' else a.qualified/'oldp2/comparison/P2'
        oldcp=math.gzload(prior/'checkpoint.json.gz');result['compatibility']=compare_oracle(a.actual,prior,source_sha,oldcp['runtime']['source_sha256'])
    dev=development_record(profile,result['metrics'],result['baseline_metrics'],Q(review['development_fee_burden']),review['development_treatment_count'])
    dev.update(review_passed=True,source_sha256=source_sha)
    (a.output/'review.json').write_bytes(math.encode(result)+b'\n');(a.output/'development.json').write_bytes(math.encode(dev)+b'\n');print('INDEPENDENT_RISK_PROFILE_REVIEW_FINISHED')

if __name__=='__main__':main()
