"""Exact approved old reference data; never a financial checkpoint origin."""
from copy import deepcopy
import gzip
import json
from pathlib import Path

from p01_iac_unit_contract import FIRST,need,sha,digest,unique
from p01_iac_unit_parent import OUTER

HERE=Path(__file__).parent
SPEC='p01_iac_reference_evidence_spec.json'
ADMISSION='4939701ac1df8cfacf7e3a6012b3c1e94d33ec12dbe5fb511951ca4c8e1f6827'
ORIGIN=dict(run_id=41462104626,head='4e0940c4ef12036a04d54d28000b5e0368c63a88',artifact_id=13149998336,
    request_file='p01_iac_unit_fixture_request.json',request_sha256='fd2ff79b00472f482e53df2b411cdeec5c999e27529be287bcfc6f9c914216a7',
    driver_source_count=497)
COMPONENT='qualification/unit-normalization-component.json.gz'
ZERO='qualification-failure/reference/zero-session-boundaries.json'
APPROVED={COMPONENT:dict(bytes=14617713,sha256='19b826649a66e26340b4368aa2976c57cc025db05d126928d7324aa9bcc673bd'),
    ZERO:dict(bytes=26516617,sha256='a2bd4e3e5d26261e263693309616ce50a6e1cf39dd7d1e7353acbd9b4477a9ac')}
PROVENANCE='reference-evidence.json'
PROVENANCE_SCHEMA='research.p01-iac-reference-evidence-provenance/1'
PUBLIC_KEYS={'schema','origin','approved_members','root_reuse_admission_sha256','partial_review_sha256',
    'metadata_review_sha256','final_review_sha256','financial_authority','financial_predecessor_admitted'}
ORIGIN_KEYS=set(ORIGIN)|{'zip','protocol_sha256','stage','receipt','marker','capacity','qualification_cipher',
    'authenticated_manifest','actual_worker_stop','public_members'}


def encoded(value):
    """Typed checkpoint domain: canonical JSON without a trailing LF."""
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode('utf8')


def same(left,right):return encoded(left)==encoded(right)


def reference_spec():
    value=json.loads((HERE/SPEC).read_bytes(),object_pairs_hook=unique)
    need(type(value) is dict and set(value)==PUBLIC_KEYS and type(value['origin']) is dict
         and set(value['origin'])==ORIGIN_KEYS
         and value['schema']=='research.p01-approved-reference-evidence-spec/1'
         and value['root_reuse_admission_sha256']==ADMISSION and value['approved_members']==APPROVED
         and all(type(value['origin'][k]) is type(v) and value['origin'][k]==v for k,v in ORIGIN.items())
         and value['financial_authority'] is value['financial_predecessor_admitted'] is False,
         'REFERENCE_EXACT_ROOT_APPROVED_TWO_MEMBER_IDENTITY')
    return value


def runtime_hashes(value):
    need(type(value) is dict and value['checkpoint_sha256']==digest({k:v for k,v in value.items() if k!='checkpoint_sha256'})
         and value['state_sha256']==digest(value['state']), 'REFERENCE_COMPLETE_RUNTIME_AND_STATE_HASH')


def outer_hashes(value):
    need(type(value) is dict and value['sha256']==digest({k:v for k,v in value.items() if k!='sha256'}),
         'REFERENCE_COMPLETE_OUTER_CHECKPOINT_HASH')
    runtime_hashes(value['run'])


def validate_reference(component,zero):
    """Validate recorded objects only; canonical restoration remains hosted."""
    boundary=component['actual_reference_boundary'];paths=boundary['actual_components'];final=boundary['qualifier_checkpoint']
    need(component['schema']=='research.p01-iac-unit-synthetic-canonical-component/2'
         and boundary['schema']=='research.p01-iac-unit-unadmitted-reference-boundary/1'
         and boundary['actual_reference_records_preserved_before_fixtures'] is True
         and boundary['financial_authority'] is boundary['qualification_state_adopted'] is False
         and len(paths)==2 and [r['session'] for r in paths]==list(FIRST)
         and same(boundary['input_zero_checkpoint'],zero['input_checkpoint']),
         'REFERENCE_APPROVED_COMPLETE_TWO_SESSION_BOUNDARY')
    outer_hashes(zero['epoch_checkpoint']);outer_hashes(zero['input_checkpoint']);outer_hashes(final)
    need(zero['epoch_checkpoint']['sha256']==OUTER and zero['input_checkpoint']['completed']==628
         and zero['input_checkpoint']['source_cursor']=='2020-06-30'
         and final['completed']==630 and final['source_cursor']==FIRST[-1],
         'REFERENCE_SAVED_ZERO_AND_FINAL_CURSOR_NOT_FINANCIAL_ADMISSION')
    previous=zero['input_checkpoint']['run']
    for row in paths:
        need(type(row) is dict and set(row)=={'session','prior_checkpoint','publication','checkpoint'}
             and same(row['prior_checkpoint'],previous) and row['publication']['session']==row['session'],
             'REFERENCE_WHOLE_TYPED_RUNTIME_ADJACENCY_AND_PUBLICATION')
        runtime_hashes(row['prior_checkpoint']);runtime_hashes(row['checkpoint'])
        need(row['checkpoint']['state']['last_processed_session']==row['session']
             and row['checkpoint']['input_sha256']==zero['successor_input_sha256'],
             'REFERENCE_RECORDED_RUNTIME_CURSOR_AND_INPUT')
        previous=row['checkpoint']
    need(same(final['run'],previous),'REFERENCE_WHOLE_FINAL_RUNTIME_EQUALS_LAST_RECORDED_PATH')
    return dict(components=deepcopy(paths),final=deepcopy(final),zero=deepcopy(zero))


def load_reference_evidence(root,spec=None):
    """Read only the exact approved subset after host full-artifact authentication."""
    spec=reference_spec() if spec is None else spec
    need(same(spec,reference_spec()),'REFERENCE_EXACT_STATIC_METADATA_SPEC')
    root=Path(root);raws={}
    actual={p.relative_to(root).as_posix() for p in root.rglob('*') if p.is_file()}
    need(actual==set(APPROVED)|{PROVENANCE} and not any(p.is_symlink() for p in root.rglob('*')),
         'REFERENCE_WORKER_EXACT_TWO_APPROVED_MEMBERS_AND_PROVENANCE_ONLY')
    for name,entry in APPROVED.items():
        path=root/name
        need(path.is_file() and not path.is_symlink() and path.stat().st_size==entry['bytes'],
             'REFERENCE_BOUNDED_REGULAR_APPROVED_MEMBER')
        raw=path.read_bytes();need(sha(raw)==entry['sha256'],'REFERENCE_EACH_APPROVED_MEMBER_BYTE_PREIMAGE');raws[name]=raw
    proof=json.loads((root/PROVENANCE).read_bytes(),object_pairs_hook=unique)
    need(proof['schema']==PROVENANCE_SCHEMA and same(proof['specification'],spec)
         and proof['all_old_driver_sources_authenticated'] is True
         and proof['full_qualification_inventory_authenticated'] is True
         and proof['original_qualification_worker_exit_code']==1
         and type(proof['original_qualification_worker_exit_code']) is int
         and proof['financial_worker_started'] is False
         and proof['financial_authority'] is proof['qualification_state_adopted'] is False,
         'REFERENCE_COMPLETE_HOST_AUTHENTICATION_AND_NO_FINANCIAL_ADOPTION')
    raw_request=proof['original_raw_request_utf8'].encode('utf8')
    need(sha(raw_request)==ORIGIN['request_sha256'] and len(json.loads(raw_request)['sources'])==497,
         'REFERENCE_ORIGINAL_RAW_REQUEST_UNRELABELLED')
    component=json.loads(gzip.decompress(raws[COMPONENT]),object_pairs_hook=unique)
    zero=json.loads(raws[ZERO],object_pairs_hook=unique);value=validate_reference(component,zero)
    return dict(value,component=component,component_raw=raws[COMPONENT],provenance=proof,
        provenance_raw=(root/PROVENANCE).read_bytes(),approved_members=deepcopy(APPROVED))
