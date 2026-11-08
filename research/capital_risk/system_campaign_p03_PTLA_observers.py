"""Original ordinary observer/reviewer over all34 inherited terms plus PTLA."""
import json
from pathlib import Path
from types import FunctionType
from full_system_benchmark import need
import system_campaign_bounded_sensor_observers_v2 as original
import system_campaign_p03_PTLA_history as history
data=history.data


def inherited(root,current,*,validate_history=history.full):
 root=Path(root);result=validate_history(root,current)
 need(result['passed'] is True and result['full_inputs']==len(current['repairs'])
  and len(current['repairs'])in (20,21),'PTLA_OBSERVER_COMPLETE_ACTUAL20_OR21_HISTORY_BEFORE_METADATA_USE')
 parent=current if len(current['repairs'])==20 else history.archived_parent(lambda n:(root/n).read_bytes())
 history.resources.parent_contract(parent,history.spec())
 metadata=history.previous.archived_parent(lambda n:(root/n).read_bytes())
 need(len(metadata['repairs'])==19 and metadata['completed']==606 and metadata['repairs']==parent['repairs'][:19]
  and metadata['sha256']!=parent['sha256'],'PTLA_OBSERVER_GENUINE_ARCHIVED19_METADATA_NOT_A_FINANCIAL_SEED')
 tail,resources=original.tail_materials(root,metadata)
 contract=json.loads((root/original.DIRECTORY/original.CONTRACT).read_bytes())
 for name,pin in contract['resources'].items():
  need(original.sha((root/original.DIRECTORY/name).read_bytes())==pin,'PTLA_OBSERVER_ALL_ORIGINAL_STATIC_SOURCE_RESOURCES')
 old=original.merge(contract['terms'],tail)
 need(len(old)==34 and not any(t['security_id']==data.SID for t in old),'PTLA_OBSERVER_EXACT34_OLD_TERMS_AND_NEW_IDENTITY')
 return parent,tail,resources,old


def extend(old_tail,old_resources,old_terms,document,material,material_raw,descriptor,material_name):
 terms=data.terms()
 need(document['add']==[t['added'] for t in terms] and material['terms']==terms
  and json.loads(material_raw)==material and Path(material_name).name==material_name and material_name.endswith('.json')
  and descriptor['filename']==descriptor['sha256']+'.json'
  and original.sha(data.encoded(document))==descriptor['sha256'],
  'PTLA_OBSERVER_EXACT_ACTUAL_COMMITTED_NEW_DOCUMENT_AND_MATERIAL')
 need(len(original.merge(old_terms,terms))==35,'PTLA_OBSERVER_ALL34_PRIOR_PLUS_EXACTLY_ONE_NEW_TERM')
 resources=dict(old_resources);destination=original.DIRECTORY+'/materials/'+descriptor['sha256']+'/'+material_name
 need(destination not in resources or resources[destination]==material_raw,'PTLA_OBSERVER_NO_REPLACED_ORIGINAL_SOURCE_RESOURCE')
 resources[destination]=material_raw
 return original.merge(old_tail,terms),resources


def tail_materials(root,current,*,validate_history=history.full):
 root=Path(root);parent,tail,resources,old=inherited(root,current,validate_history=validate_history)
 if len(current['repairs'])==20:return tail,resources
 member=lambda n:(root/n).read_bytes();document=history.document(parent,member)
 name=history.material_name(parent);raw=member(name);material=json.loads(raw)
 return extend(tail,resources,old,document,material,raw,current['repairs'][-1],name)


def bind(name):
 need(name in ('observer','review','stage_retained'),'PTLA_OBSERVER_ONLY_COMPLETE_ORIGINAL_ENTRY_FUNCTIONS')
 fn=getattr(original,name);need(fn.__closure__ is None,'PTLA_OBSERVER_COMPLETE_ORIGINAL_CLOSED_FUNCTION')
 bound=FunctionType(fn.__code__,dict(fn.__globals__,tail_materials=tail_materials),fn.__name__,fn.__defaults__)
 bound.__kwdefaults__=fn.__kwdefaults__
 return bound


def observer(root,current):
 from full_system_core import hosted
 hosted();return bind('observer')(root,current)


def review(root,current,out):
 from full_system_core import hosted
 hosted();return bind('review')(root,current,out)


def stage_retained(root,current,out):
 from full_system_core import hosted
 hosted();return bind('stage_retained')(root,current,out)
