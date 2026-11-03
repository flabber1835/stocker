"""One closed public immutable stopped target, never financial authority."""
import hashlib,json,re
from pathlib import Path
from full_system_benchmark import need
HERE=Path(__file__).parent
TARGET='p01_iac_stopped_review_target.json'
TARGET_SHA='24f61df8a4e560ddcbae2192bc21f5fc0bcee29e2ee6d7412ee927625fce4c98'

def sha(raw):return hashlib.sha256(raw).hexdigest()
def encoded(value):return (json.dumps(value,sort_keys=True,indent=2,allow_nan=False)+'\n').encode()
def digest(value):return sha(json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode())
def plain(raw):
    def pairs(rows):
        out={}
        for k,v in rows:need(k not in out,'STOPPED_REVIEW_DUPLICATE_METADATA');out[k]=v
        return out
    def invalid(v):raise ValueError('REFUSED_STOPPED_REVIEW_NONFINITE_METADATA')
    return json.loads(raw,object_pairs_hook=pairs,parse_constant=invalid)
def read(path,limit=2*1024**2):
    with Path(path).open('rb') as stream:raw=stream.read(limit+1)
    need(len(raw)<=limit,'STOPPED_REVIEW_BOUNDED_METADATA');return raw

def check_target(value):
    need(type(value) is dict and sha(encoded(value))==TARGET_SHA,'STOPPED_REVIEW_EXACT_WHOLE_TARGET_PREIMAGE')
    need(set(value)=={'schema','authority','root_review_only_authorized','financial_authority','financial_resume_authorized',
        'qualification_or_financial_replay_authorized','original_states_adopted','original','public_members','review_context_files','adapter'}
        and value['schema']=='research.p01-stopped-evidence-review-target/1'
        and value['authority']=='READ_ONLY_STOPPED_EVIDENCE_REVIEW' and value['root_review_only_authorized'] is True
        and all(value[k] is False for k in ('financial_authority','financial_resume_authorized','qualification_or_financial_replay_authorized','original_states_adopted')),
        'STOPPED_REVIEW_ONLY_EXPLICIT_AUTHORITY')
    old=value['original']
    need(type(old['run_id']) is int and old['run_id']==41487773225 and old['source_count']==515
        and old['head']=='3ea405f31cfcc0d75ea5e330177de76e7c79053a'
        and old['request_sha256']=='9068e16677950f58dcf3055bc5b7cbee39f898115bfab2587478bbad96e8b230',
        'STOPPED_REVIEW_ORIGINAL_FINANCIAL_ENVELOPE')
    for key,code in (('qualification_worker',0),('worker',0),('reviewer',1)):
        stop=old['stops'][key]
        need(set(stop)=={'stopped','exit_code','oom_killed','wait_error'} and stop['stopped'] is True
            and type(stop['exit_code']) is int and stop['exit_code']==code and stop['oom_killed'] is False,
            'STOPPED_REVIEW_ORIGINAL_STOPS_NOT_RELABELED')
    return value

def target():
    raw=read(HERE/TARGET);need(sha(raw)==TARGET_SHA,'STOPPED_REVIEW_TARGET_RAW_HASH')
    return check_target(plain(raw))
