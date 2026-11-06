"""Finite actual805 ABMD continuation; all original cooperative methods retained."""
import ast,json
from pathlib import Path
from types import SimpleNamespace
import system_campaign_p07_abmd_certificate as frozen
import system_campaign_p07_abmd_lifecycle as lifecycle
import system_campaign_p07_abmd_models as models
import system_campaign_p07_abmd_origin as origin
import system_campaign_p07_vivo_data as data

HERE=Path(__file__).parent
SOURCE='P07-admitted-ABMD-continuation-factory-DATA-SOURCE.txt'
SOURCE_SHA='43e319690ef34374daaa441e9a2096edcef882d05230735512e9673d98a9f810'

def source():
    raw=(HERE/SOURCE).read_bytes();data.need(data.sha(raw)==SOURCE_SHA,'VIVO_ENTIRE_ORIGINAL_POSTEVENT_FACTORY_SOURCE')
    return raw

def exact_metadata(original,current,spec,catalog,origin_value,rows,committed,resolutions,allowed,archive_raw,*,source_plan):
    data.parent_contract(current,spec);p=data.identity_plan()
    result=original(current,spec,catalog,origin_value,rows,committed,resolutions,allowed,archive_raw,source_plan=source_plan)
    raw=b''.join(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()+b'\n' for v in rows)
    data.need(len(rows)==len(committed)==805 and dict(bytes=len(raw),sha256=data.sha(raw))==p['committed_prefix']
         and rows[-1]['chain_sha256']==p['last_chain_sha256']
         and rows[-1]['next_state_sha256']==p['last_next_state_sha256']
         and len(resolutions)==1 and origin_value['descriptor']==p['actual_ABMD_descriptor']
         and data.sha(data.encoded(origin_value))==p['actual_ABMD_origin_sha256'],
         'VIVO_FINITE_ACTUAL805_SEED_AND_REAL_ABMD_ORIGIN_NO_RAW_JANUARY_TAILS')
    return result

def factory_namespace():
    scope=dict(frozen=frozen,lifecycle=lifecycle,models=models,origin=origin,ast=ast,json=json,Path=Path,
        sha=data.sha,digest=data.digest,need=data.need,FROZEN_SHA='4f3db7f1cefffbad4c6eb48c0efe82678282c96c2a7b97c039db2307b9d86baa',
        SCHEMA='research.p07-abmd-admitted-continuation-qualification/1')
    tree=ast.Module(body=[n for n in ast.parse(source()).body if isinstance(n,ast.FunctionDef)],type_ignores=[])
    exec(compile(tree,'<whole-admitted-postevent-ABMD-factory-functions>','exec'),scope)
    original=scope['qualify_metadata']
    scope['qualify_metadata']=lambda *a,**k:exact_metadata(original,*a,**k)
    return SimpleNamespace(**scope)

def certificate_class(*args,**kwargs):
    from full_system_core import hosted
    hosted()
    data.parent_contract(kwargs['current_checkpoint'],kwargs['admitted_spec'])
    return factory_namespace().certificate_class(*args,**kwargs)

def source_names():return (Path(__file__).name,SOURCE)
