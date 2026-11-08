"""Actual full11/173 metadata guards; future financial selection remains closed."""
import json
from pathlib import Path
import system_campaign_p06_BBIG_data as data
import system_campaign_p06_BBIG_models as models
import system_campaign_p06_BBIG_seed as seed
from system_campaign_bounded_sensor_origin_v2 import strict_json
from system_campaign_financial_partial import root_spec
HERE=Path(__file__).parent
FACT='P06-actual1426-full11-retained173-preconditions.json'
FACT_SHA='ad4f104054eb8b754756e62cedeec469308858501f3ad7bcbacaf11744677ac6'
ADMISSION='P06-WWE12-admission-binding-pending.json'
ADMISSION_SHA='1a533ff7c3b3d66e154239123249dfc9352be40f11fa25247df73baef4245f5b'
OUTER='3157c9a6b1eae175a87d0c282c68a5516ea4cb312068da4b43ee80feea4d93e4'
def fact():
    raw=(HERE/FACT).read_bytes();data.need(data.sha(raw)==FACT_SHA,'P06_WWE173_EXACT_ACTUAL1426_METADATA_FACT')
    value=json.loads(raw)
    data.need((value['current_outer_sha256'],value['current_completed'],value['current_cursor'],value['current_inputs'])==(OUTER,1426,'2023-08-31',11)
        and (value['committed_proof_rows'],value['raw_proof_rows'])==(173,179)
        and value['financial_authority'] is value['root_admission_ready'] is False
        and value['new_root_admission_sha256'] is value['new_neutral12_sha256'] is None,'P06_WWE173_REAL_PRECONDITIONS_WITHOUT_FUTURE_ROOT_OR_SEED')
    return value
def actual_parent(root,current,*,member=None):
    root=Path(root);value=fact();member=(lambda name:(root/name).read_bytes()) if member is None else member
    raw=member('book/checkpoint.json.gz')
    data.need(dict(bytes=len(raw),sha256=data.sha(raw))==value['selected_gzip'] and strict_json(raw)==current
        and current['sha256']==OUTER==data.digest({k:v for k,v in current.items() if k!='sha256'})
        and current['run']['state_sha256']==value['state_sha256']==data.digest(current['run']['state'])
        and current['run']['checkpoint_sha256']==value['inner_sha256']
        and current['repairs']==value['repairs'] and current['journals']==value['journals']
        and current['run']['input_sha256']==value['input_sha256']==data.digest(dict(base=current['base'],repairs=current['repairs']))
        and data.digest(current['base'])==value['base_sha256'],'P06_WWE173_ONLY_GENUINE_DISTINCT_CURRENT_FULL11_NO_PROJECTION')
    w=current['run']['state']['wealth_core'];held=[(slot,v) for slot,v in w['episodes'].items() if v['security_id']=='426024777347801008']
    data.need(json.loads(data.encoded(held))==value['held_WWE'] and current['run']['state']['pending']==[]
        and not any(v['security_id']=='351179184194166734' for v in w['episodes'].values())
        and all(w[k]=={} for k in ('unresolved_terminals','terminal_pending_terms','terminal_pending_sessions','terminal_carry_audit')),
        'P06_WWE173_ACTUAL_OWN27_NO_DELIVERY_ORDERS_OR_PENDING_TERMINAL')
    for d in current['repairs']:
        data.need(d['filename']==d['sha256']+'.json' and data.sha(member('book/repairs/'+d['filename']))==d['sha256'],
            'P06_WWE173_EVERY_REAL_FULL11_INPUT_DOCUMENT')
    old=models.original;catalog=models.initial.catalog();parent=strict_json(member(models.PARENT));neutral=strict_json(member(models.DIRECTORY+'/checkpoint.json.gz'))
    checked=models.bound_history()(root,current,catalog,root_metadata=root_spec('P06',catalog['parent_root_admission_sha256']),
        input_hash=lambda base,repairs:data.digest(dict(base=base,repairs=repairs)),member=member,
        initial_parent=strict_json(member(old.DIRECTORY+'/'+old.PARENT)),ordinary_neutral=strict_json(member(old.DIRECTORY+'/'+old.ORDINARY)),
        typed_neutral=strict_json(member(old.DIRECTORY+'/'+old.TYPED)),financial_parent=parent,neutral11=neutral)
    data.need(checked['full_inputs']==11 and neutral['sha256']==value['genuine_neutral11_sha256'],'P06_WWE173_ALL_ORIGINAL8_9_TYPED10_AND_GENUINE11_HISTORY')
    raw=member('uncertainty-certificate.jsonl');lines=raw.splitlines(keepends=True)
    data.need(dict(bytes=len(raw),sha256=data.sha(raw))==value['raw_proof'] and len(lines)==179
        and dict(bytes=len(b''.join(lines[:173])),sha256=data.sha(b''.join(lines[:173])))==value['committed_proof']
        and [json.loads(v)['session'] for v in lines[173:]]==value['excluded_tail_sessions'],
        'P06_WWE173_EXACT173_COMMITTED_OF179_EXCLUDES_ALL6_DIAGNOSTIC_TAILS')
    rows=seed.initial.seed_reader(inherited_root=Path(seed.initial.__file__).parent)(root,current)
    data.need(len(rows)==173 and rows[-1]['session']=='2023-08-31' and rows[-1]['chain_sha256']==value['committed_last_chain']
        and rows[-1]['next_state_sha256']==value['committed_last_state']==current['run']['state_sha256'],
        'P06_WWE173_ALL_ORIGINAL_PROOF_FINANCIAL_WATCH_CHAINS_AND_CURRENT_STATE')
    pin=value['original_FIN339_branch_oracle'];oracle_raw=member(pin['member']);oracle=json.loads(oracle_raw)
    data.need(pin['artifact_id']==13525611349 and pin['member']=='stopped-review/uncertainty-certificate-review.json'
        and dict(bytes=len(oracle_raw),sha256=data.sha(oracle_raw))=={k:pin[k] for k in ('bytes','sha256')}
        and data.sha(oracle_raw)==value['hosted_canonical_transition_oracle_sha256']=='190de5015b174b76f42786943f87ac5e3100555b660e0e116d7d305a18b71bf8'
        and oracle['passed'] is True and oracle['checkpoint_sha256']==OUTER
        and (oracle['rows'],oracle['retained_rows'])==(43,130),
        'P06_WWE173_EXACT_ORIGINAL_FIN339_TRANSPORT_ORACLE_NOT_NEW_READONLY_PATH')
    return dict(passed=True,actual_completed=1426,actual_inputs=11,committed_rows=173,excluded_tail_rows=6,
        actual_held_WWE=27,financial_authority=False,financial_sessions_reexecuted=0,new_root_admission_sha256=None)
def require_admitted(current,spec,request):
    raw=(HERE/ADMISSION).read_bytes();data.need(data.sha(raw)==ADMISSION_SHA,'P06_WWE173_EXACT_SEPARATE_ADMISSION_BINDING')
    value=json.loads(raw)
    data.need(value['admitted'] is True and value['root_admission_sha256'] is not None
        and value['independent_review_sha256'] is not None and value['readonly_artifact_id'] is not None,
        'P06_WWE173_FINANCIAL_ENTRY_CLOSED_UNTIL_REAL_POSITIVE1426_ROOT_ADMISSION')
    raise ValueError('P06_WWE173_NEW_ADMISSION_REQUIRES_SEPARATE_FINAL_PROFILE_QUALIFICATION')
def source_names():return (Path(__file__).name,FACT,ADMISSION,*models.source_names(),*seed.source_names())
