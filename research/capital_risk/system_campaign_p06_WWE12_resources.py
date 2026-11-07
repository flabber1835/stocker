"""Exact authenticated historical resources, with no current-book aliases."""
import json
from pathlib import Path,PurePosixPath
import system_campaign_p06_WWE12_data as data
from system_campaign_bounded_sensor_origin_v2 import exact
HERE=Path(__file__).parent
PLAN='P06-WWE12-authenticated-retained-resources-v2.json'
PLAN_SHA='4dac453c6d203136ee074407dc16fba81c2531fd141e5ecba19019040a01b1af'

def plan():
    raw=(HERE/PLAN).read_bytes();data.need(data.sha(raw)==PLAN_SHA,'P06_WWE12_EXACT_AUTHENTICATED_RESOURCE_PLAN')
    value=json.loads(raw)
    data.need((value['artifact_id'],value['root_admission_sha256'],value['completed'],value['cursor'],value['full_inputs'])==
        (13525611349,data.ROOT,1426,'2023-08-31',11) and len(value['resources'])==88
        and value['lineage_preservation_owner']=='UNCHANGED_ORIGINAL_RESUME_PRESERVE_ORIGINALS'
        and value['financial_authority'] is value['financial_book_aliases_created'] is False
        and value['raw_proof_source']=='uncertainty-certificate.jsonl'
        and value['raw_proof_destination']=='p06-WWE-ordinary12-origin/actual-old-full179-uncertainty-certificate.jsonl',
        'P06_WWE12_ONLY_FIN339_HISTORICAL_RESOURCES_NO_NEW_BOOK_OR_SEED')
    for name,pin in value['resources'].items():
        p=PurePosixPath(name)
        data.need(not p.is_absolute() and p.as_posix()==name and '..' not in p.parts and '\\' not in name
            and not name.startswith(('book/','lineage/','root-review344/','p06-WWE-'))
            and name not in ('request.json','spec.json','uncertainty-certificate.jsonl','uncertainty-capture.json')
            and set(pin)=={'bytes','sha256'} and type(pin['bytes']) is int and pin['bytes']>0,
            'P06_WWE12_FINITE_SAFE_HISTORICAL_RESOURCE_PATHS')
    return value

def checked(member,name):
    value=plan();data.need(name in value['resources'],'P06_WWE12_ONLY_DECLARED_HISTORICAL_MEMBER')
    raw=member(name);data.need(dict(bytes=len(raw),sha256=data.sha(raw))==value['resources'][name],
        'P06_WWE12_EXACT_HISTORICAL_MEMBER_BYTES:'+name)
    return raw

def inventory(member):
    value=plan()
    for name in value['resources']:checked(member,name)
    return dict(passed=True,plan_sha256=PLAN_SHA,resources=value['resources'],financial_authority=False,
        financial_book_aliases_created=False,financial_sessions_reexecuted=0)

def preserve(root,out,parent,spec):
    from full_system_core import hosted
    hosted();data.parent_contract(parent,spec);root,out=Path(root),Path(out)
    result=inventory(lambda n:(root/n).read_bytes())
    for name in plan()['resources']:exact(out/name,(root/name).read_bytes())
    value=plan();raw=(root/value['raw_proof_source']).read_bytes()
    data.need(dict(bytes=len(raw),sha256=data.sha(raw))==value['raw_proof'],'P06_WWE12_ENTIRE_RAW179_PROOF_PROVENANCE')
    exact(out/value['raw_proof_destination'],raw)
    exact(out/'p06-WWE-ordinary12-origin/authenticated-resource-preservation.json',data.encoded(result))
    return result

def verify_preserved(source,destination):
    result=inventory(source)
    for name in plan()['resources']:
        data.need(destination(name)==source(name),'P06_WWE12_ALL_HISTORICAL_DESTINATIONS_BYTE_IDENTICAL:'+name)
    value=plan();raw=source(value['raw_proof_source'])
    data.need(dict(bytes=len(raw),sha256=data.sha(raw))==value['raw_proof']
        and destination(value['raw_proof_destination'])==raw
        and json.loads(destination('p06-WWE-ordinary12-origin/authenticated-resource-preservation.json'))==result,
        'P06_WWE12_COMPLETE_RAW179_AND_RESOURCE_PRESERVATION_RECEIPT')
    return True

def source_names():return (Path(__file__).name,PLAN,*data.source_names())
