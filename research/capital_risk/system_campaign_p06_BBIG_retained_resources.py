"""Finite authenticated actual1383 metadata layout, no financial aliases."""
import json
from pathlib import Path,PurePosixPath
import system_campaign_p06_BBIG_data as data

HERE=Path(__file__).parent
PLAN='P06-admitted1383-complete-preservation-plan-v2.json'
PLAN_SHA='7b70ff6f2560842daf31303b6062d1b6c3daabda2995f3b5c43693e882971378'
SOURCE_ORIGIN='p06-point-retained-origin/'
OBSERVATIONS='p06-retained-ordinary-observation/'
def plan():
    raw=(HERE/PLAN).read_bytes();data.need(data.sha(raw)==PLAN_SHA,'P06_BBIG_EXACT_ACTUAL1383_METADATA_PLAN_BYTES')
    value=json.loads(raw)
    data.need(raw==data.encoded(value) and value['schema']=='research.P06-actual1383-retained-metadata-resource-plan/1'
        and (value['root_admission_sha256'],value['parent_outer_sha256'],value['completed'],value['cursor'],value['full_inputs'])==
            (data.ROOT,data.OUTER,1383,'2023-06-30',10)
        and value['artifact_id']==13482378564 and len(value['resources'])==13
        and value['financial_authority'] is value['financial_checkpoint_aliases_created'] is False
        and value['historical_and_current_capture_distinct'] is True,
        'P06_BBIG_FINITE_ACTUAL1383_METADATA_RESOURCE_PLAN')
    for name,pin in value['resources'].items():
        p=PurePosixPath(name)
        data.need(not p.is_absolute() and p.as_posix()==name and '..' not in p.parts and '\\' not in name
            and not any(n.endswith(('.json.gz','.tar','.zip')) for n in p.parts)
            and (name.startswith((SOURCE_ORIGIN,OBSERVATIONS)) or name in ('uncertainty-capture.json','p06-abmd-initial-synthetic-gateway.json'))
            and set(pin)=={'bytes','sha256'} and type(pin['bytes']) is int and pin['bytes']>0
            and len(pin['sha256'])==64 and all(c in '0123456789abcdef' for c in pin['sha256']),
            'P06_BBIG_ONLY_EXACT_SAFE_METADATA_RESOURCE_NAMES_AND_PINS')
    expected={'actual-future-event-2022-12-16.json':SOURCE_ORIGIN+'actual-future-event-2022-12-16.json',
        'uncertainty-capture.json':'uncertainty-capture.json','p06-abmd-initial-synthetic-gateway.json':'p06-abmd-initial-synthetic-gateway.json'}
    data.need(value['old_preserve_read_map']==expected and all(n in value['resources'] for n in expected.values()),
        'P06_BBIG_ONLY_THREE_EXACT_OLD_PRESERVE_READS_ONE_REAL_ORIGIN_RESOLUTION')
    data.need(len(value['whole_preserve_source_pins'])==value['whole_preserve_sources']==48
        and len(value['whole_preserve_destination_to_actual_source'])==value['whole_preserve_destinations']==57
        and set(value['whole_preserve_destination_to_actual_source'].values())==set(value['whole_preserve_source_pins'])
        and all(value['whole_preserve_source_pins'][n]==pin for n,pin in value['resources'].items()),
        'P06_BBIG_COMPLETE_48_SOURCE_57_DESTINATION_ORIGINAL_PRESERVATION_SET')
    for name in (*value['whole_preserve_source_pins'],*value['whole_preserve_destination_to_actual_source']):
        p=PurePosixPath(name)
        data.need(not p.is_absolute() and p.as_posix()==name and '..' not in p.parts and '\\' not in name,
            'P06_BBIG_COMPLETE_PRESERVATION_SAFE_EXACT_RELATIVE_PATHS')
    return value
def checked_member(root,name,value=None):
    value=plan() if value is None else value
    data.need(name in value['resources'],'P06_BBIG_ONLY_DECLARED_ACTUAL_METADATA_MEMBER')
    raw=(Path(root)/name).read_bytes()
    data.need(dict(bytes=len(raw),sha256=data.sha(raw))==value['resources'][name],
        'P06_BBIG_EXACT_ACTUAL_METADATA_MEMBER_BYTES:'+name)
    return raw
def inventory(root,current):
    value=plan()
    data.need((current['sha256'],current['completed'],current['source_cursor'],len(current['repairs']))==(data.OUTER,1383,'2023-06-30',10)
        and current['sha256']==data.digest({k:v for k,v in current.items() if k!='sha256'}),
        'P06_BBIG_METADATA_INVENTORY_ONLY_GENUINE_ADMITTED1383_PARENT10')
    root=Path(root)
    actual={p.relative_to(root).as_posix() for prefix in (SOURCE_ORIGIN,OBSERVATIONS) for p in (root/prefix).rglob('*') if p.is_file()}
    expected={n for n in value['resources'] if n.startswith((SOURCE_ORIGIN,OBSERVATIONS))}
    data.need(actual==expected and not (root/'actual-future-event-2022-12-16.json').exists(),
        'P06_BBIG_FULL_ACTUAL_METADATA_AXIS_WITHOUT_AMBIGUOUS_ROOT_ALIAS')
    for name,pin in value['whole_preserve_source_pins'].items():
        raw=(root/name).read_bytes()
        data.need(dict(bytes=len(raw),sha256=data.sha(raw))==pin,'P06_BBIG_WHOLE_ORIGINAL_PRESERVE_SOURCE_BYTES:'+name)
    result={n:checked_member(root,n,value) for n in value['resources']}
    data.need('actual-future-event-2022-12-16.json' not in value['resources']
        and result['uncertainty-capture.json']!=result[SOURCE_ORIGIN+'uncertainty-capture.json'],
        'P06_BBIG_KEEP_ORIGIN_TRQ_AND_BOTH_CAPTURE_GENERATIONS_DISTINCT')
    return result
def provenance_member(root,name):
    value=plan();mapping=value['old_preserve_read_map']
    data.need(name in mapping,'P06_BBIG_ONE_DECLARED_ORIGINAL_PRESERVE_LOOP_NAME')
    return checked_member(root,mapping[name],value)
def preservation_receipt(raws):
    value=plan()
    data.need(set(raws)==set(value['resources']) and all(dict(bytes=len(raw),sha256=data.sha(raw))==value['resources'][n] for n,raw in raws.items()),
        'P06_BBIG_COMPLETE_FRESH_METADATA_INVENTORY_BEFORE_RECEIPT')
    return dict(schema='research.P06-actual1383-metadata-preservation-receipt/1',passed=True,
        original_root_admission_sha256=data.ROOT,original_parent_sha256=data.OUTER,plan_file=PLAN,plan_sha256=PLAN_SHA,
        actual_source_members=value['resources'],old_preserve_read_map=value['old_preserve_read_map'],
        complete_original_preserve_source_pins=value['whole_preserve_source_pins'],
        complete_preserve_destination_to_actual_source=value['whole_preserve_destination_to_actual_source'],
        historical_and_current_capture_generations_preserved_separately=True,financial_checkpoint_aliases_created=False,
        financial_state_replayed=False,financial_sessions_advanced=0,financial_authority=False)
def verify_preserved(read_source,read_destination,rows,resolution,*,provenance):
    """Read-only exact source/destination byte relation; no checkpoint API."""
    value=plan();data.need(provenance=='p06-BBIG-ordinary11-origin','P06_BBIG_ONLY_QUALIFIED_PRESERVATION_DESTINATION')
    compact=lambda row:json.dumps(row,sort_keys=True,separators=(',',':'),allow_nan=False).encode()+b'\n'
    prefix=b''.join(map(compact,rows))
    data.need(len(rows)==130 and dict(bytes=len(prefix),sha256=data.sha(prefix))==value['committed130_prefix_pin']
        and resolution==value['prior_ABMD_resolution'],
        'P06_BBIG_ALREADY_PRESERVED_GENUINE130_AND_ACTUAL_FULL10_ABMD_RESOLUTION')
    for destination,source in value['whole_preserve_destination_to_actual_source'].items():
        a,b=read_source(source),read_destination(destination);pin=value['whole_preserve_source_pins'][source]
        data.need(dict(bytes=len(a),sha256=data.sha(a))==pin and a==b,
            'P06_BBIG_ALL57_PRESERVED_DESTINATIONS_EQUAL48_ACTUAL_PINNED_SOURCES:'+destination)
    expected=dict(passed=True,parent_outer_sha256=data.OUTER,whole_old_proof_sha256=value['raw147_proof_pin']['sha256'],
        whole_old_proof_rows=147,active_committed_seed_rows=130,active_committed_seed_sha256=value['committed130_prefix_pin']['sha256'],
        unadmitted_tail_rows_used=0,prior_transition_reexecuted=False)
    data.need(read_destination(provenance+'/prefix-preservation.json')==data.encoded(expected),
        'P06_BBIG_EXACT_ORIGINAL147_PROVENANCE130_PREFIX_PRESERVATION_RECEIPT')
    raws={n:read_source(n) for n in value['resources']}
    data.need(read_destination(provenance+'/actual-prior-metadata-preservation.json')==data.encoded(preservation_receipt(raws)),
        'P06_BBIG_COMPLETE_ACTUAL_METADATA_PRESERVATION_RECEIPT')
    return True
def source_names():return (Path(__file__).name,PLAN)
