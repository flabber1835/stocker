"""Strict input/evidence and actual neutral adoption DATA; no book runtime."""
from copy import deepcopy
import json
from pathlib import Path, PurePosixPath

from system_campaign_bounded_sensor_input import SCHEMA, need, sha, digest, parse
from system_campaign_bounded_sensor_catalog import encoded, validate
from system_campaign_bounded_sensor_semantics import verify as verify_semantics

ORIGIN='bounded-contingent-origin.json'
DIRECTORY='bounded-contingent-input-adoption'
DOCUMENT='bounded-contingent-sensor-input.json'
SOURCE='bounded-contingent-event-source.json'
RECEIPT_SCHEMA='research.bounded-contingent-input-origin/1'
ORIGIN_DIRECTORY='bounded-contingent-origin'

def resource_pins(catalog,typed,root_metadata):
    need(root_metadata['outer_sha256']==catalog['parent_outer_sha256']
         and root_metadata['repairs']==catalog['parent_descriptors'], 'LIFECYCLE_RESOURCE_EXACT_OWN_ROOT')
    return {**{'book/repairs/'+d['filename']:d['sha256'] for d in catalog['parent_descriptors']},
        'book/repairs/'+typed.sha256+'.json':typed.sha256,DOCUMENT:typed.sha256,
        SOURCE:catalog['market_source_sha256'],
        ORIGIN_DIRECTORY+'/catalog.json':sha(encoded(catalog)),
        ORIGIN_DIRECTORY+'/parent-checkpoint.json.gz':root_metadata['selected_file']['sha256'],
        'hydrated-uncertainty-event.json':root_metadata['bounded_input_resource_pins']['hydrated-uncertainty-event.json'],
        'hydrated-alder-unresolved-date.json':root_metadata['bounded_input_resource_pins']['hydrated-alder-unresolved-date.json'],
        'branch-controller-qualification.json':root_metadata['bounded_input_resource_pins']['branch-controller-qualification.json'],
        ORIGIN_DIRECTORY+'/prior-certificate.jsonl':root_metadata['bounded_input_resource_pins']['uncertainty-certificate.jsonl']}

def evidence(catalog):
    values=[('catalog',sha(encoded(catalog)),'Complete source-bound contingent legal endpoint catalog.'),
        ('source-payload',catalog['source_data']['payload_sha256'],'Authenticated own-parent native and identity source.'),
        ('source-review',catalog['source_data']['review_sha256'],'Independent full native and actual parent-role DATA review.'),
        ('source-qualification',catalog['source_data']['qualification_sha256'],'Separate closed source DATA qualification; no economic authority.'),
        ('primary-facts',catalog['primary_facts_sha256'],'Qualified mandatory upfront cash and nontransferable contingent-right legal bounds.'),
        ('event-market-source',catalog['market_source_sha256'],'Actual event-date quote, split and prior raw/source observations.'),
        ('raw-quote-preparation',catalog['raw_quote_preparation_sha256'],'Full frozen annual scan and exact native/event source commitments.'),
        ('event-contract',digest(catalog['event']),'Exact typed unowned/unordered sensor-only event contract.')]
    return [dict(reference='research.bounded-contingent-sensor/'+name,sha256=pin,description=description)
            for name,pin,description in values]

def document(catalog,*,root_lookup):
    validate(catalog,root_lookup=root_lookup)
    verify_semantics(catalog)
    return dict(schema=SCHEMA,predecessor_checkpoint_sha256=catalog['parent_inner_sha256'],
                event=deepcopy(catalog['event']),source_evidence=evidence(catalog))

def validate_document(path,catalog,*,root_lookup):
    value=document(catalog,root_lookup=root_lookup)
    raw=Path(path).read_bytes()
    need(raw==encoded(value),'LIFECYCLE_EXACT_RECONSTRUCTED_TYPED_DOCUMENT_BYTES')
    return parse(path,resume_session=catalog['parent_cursor'],
        predecessor_checkpoint_sha256=catalog['parent_inner_sha256'],
        expected_event=catalog['event'],expected_evidence=value['source_evidence'])

def descriptor(cp,catalog,typed):
    need(cp['repairs'][:len(catalog['parent_descriptors'])]==catalog['parent_descriptors']
         and len(cp['repairs'])==len(catalog['parent_descriptors'])+1,
         'LIFECYCLE_FULL_ORIGINAL_PREFIX_PLUS_ONE_INPUT')
    d=cp['repairs'][-1]
    need(d==dict(filename=typed.sha256+'.json',sha256=typed.sha256,
        resume_session=catalog['parent_cursor'],predecessor_checkpoint_sha256=catalog['parent_inner_sha256']),
        'LIFECYCLE_ACTUAL_EXACT_TYPED_DESCRIPTOR')
    return deepcopy(d)

def origin(parent,adopted,catalog,typed,proof,resources,*,input_hash,zero_adoption,root_metadata):
    """Accept only an actual neutral boundary already validated in the worker."""
    verify_semantics(catalog)
    need((parent['sha256'],parent['source_cursor'],parent['completed'])==
         (catalog['parent_outer_sha256'],catalog['parent_cursor'],catalog['parent_completed'])
         and parent['repairs']==catalog['parent_descriptors']
         and parent['base']==root_metadata['base'], 'LIFECYCLE_EXACT_OWN_PARENT')
    d=descriptor(adopted,catalog,typed)
    need(typed.event.model_dump()==catalog['event']
         and [v.model_dump() for v in typed.source_evidence]==evidence(catalog),
         'LIFECYCLE_EXACT_TYPED_EVENT_AND_EVIDENCE')
    event=zero_adoption(adopted,parent,typed.sha256,catalog['event']['native_session'])
    need(proof['event']==event and proof['original_outer_sha256']==parent['sha256']
         and proof['financial_state_unchanged'] is True
         and type(proof['financial_sessions_advanced']) is int and proof['financial_sessions_advanced']==0,
         'LIFECYCLE_ACTUAL_NEUTRAL_ADOPTION_PROOF')
    need(adopted['run']['input_sha256']==input_hash(adopted['base'],adopted['repairs']),
         'LIFECYCLE_ACTUAL_FULL_CANONICAL_INPUT_HASH')
    need(type(resources) is dict and resources
         and all(type(n) is str and n and not PurePosixPath(n).is_absolute() and '..' not in PurePosixPath(n).parts
                 and PurePosixPath(n).as_posix()==n
                 and '\\' not in n and ':' not in n and type(h) is str and len(h)==64
                 and all(c in '0123456789abcdef' for c in h) for n,h in resources.items()),
         'LIFECYCLE_EXACT_SAFE_ORIGIN_RESOURCE_COMMITMENTS')
    required=resource_pins(catalog,typed,root_metadata)
    need(required.keys()<=resources.keys() and all(resources[n]==h for n,h in required.items()),
         'LIFECYCLE_ALL_REQUIRED_ORIGINAL_AND_NEW_INPUT_RESOURCES')
    return dict(schema=RECEIPT_SCHEMA,passed=True,arm=catalog['arm'],
        initial_root_admission_sha256=catalog['parent_root_admission_sha256'],
        parent_outer_sha256=parent['sha256'],parent_descriptors=deepcopy(parent['repairs']),
        initial_adopted_outer_sha256=adopted['sha256'],adopted_descriptors=deepcopy(adopted['repairs']),
        adopted_input_sha256=adopted['run']['input_sha256'],new_descriptor=d,
        catalog_sha256=sha(encoded(catalog)),event_contract_sha256=digest(catalog['event']),
        source_evidence=deepcopy(evidence(catalog)),input_files=deepcopy(resources),
        financial_state_unchanged=True,financial_sessions_advanced=0,
        canonical_financial_source_changed=False,portfolio_cash_or_settlement_created=False)

def validate_origin(value,cp,catalog,*,input_hash,member,typed,root_metadata):
    verify_semantics(catalog)
    expected=descriptor(cp,catalog,typed)
    need(value['schema']==RECEIPT_SCHEMA and value['passed'] is True
         and value['arm']==catalog['arm'] and value['initial_root_admission_sha256']==catalog['parent_root_admission_sha256']
         and value['parent_outer_sha256']==catalog['parent_outer_sha256']
         and value['parent_descriptors']==catalog['parent_descriptors']
         and value['catalog_sha256']==sha(encoded(catalog))
         and value['event_contract_sha256']==digest(catalog['event'])
         and value['source_evidence']==evidence(catalog), 'LIFECYCLE_EXACT_ORIGINAL_INPUT_ORIGIN')
    need(value['adopted_descriptors']==cp['repairs']
         and cp['repairs'][:len(catalog['parent_descriptors'])]==catalog['parent_descriptors']
         and len(cp['repairs'])==len(catalog['parent_descriptors'])+1
         and cp['repairs'][-1]==value['new_descriptor']==expected
         and cp['base']==root_metadata['base']
         and cp['run']['input_sha256']==value['adopted_input_sha256']==input_hash(cp['base'],cp['repairs']),
         'LIFECYCLE_FULL_INPUT_HISTORY_AND_HASH_RETAINED')
    need(value['financial_state_unchanged'] is True and type(value['financial_sessions_advanced']) is int
         and value['financial_sessions_advanced']==0
         and value['canonical_financial_source_changed'] is False
         and value['portfolio_cash_or_settlement_created'] is False,
         'LIFECYCLE_ZERO_FINANCIAL_AUTHORITY')
    required=resource_pins(catalog,typed,root_metadata)
    need(required.keys()<=value['input_files'].keys()
         and all(value['input_files'][n]==h for n,h in required.items()),
         'LIFECYCLE_ALL_REQUIRED_ORIGINAL_AND_NEW_INPUT_RESOURCES')
    need(value['input_files'] and all(sha(member(name))==pin for name,pin in value['input_files'].items()),
         'LIFECYCLE_ALL_EXACT_ORIGIN_INPUT_RESOURCES')
    return True
