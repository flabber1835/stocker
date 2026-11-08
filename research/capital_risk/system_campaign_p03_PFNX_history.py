"""Whole admitted21 history plus one actual PFNX input; no local book creation."""
import ast,gzip,json
from pathlib import Path
from types import FunctionType,SimpleNamespace
from full_system_benchmark import need
from system_campaign_facts import sha,digest
from system_campaign_bounded_sensor_origin_v2 import strict_json
from system_campaign_pxd_pause import adoption
import system_campaign_full_history_successor as original
import system_campaign_p03_STML_history as templates
import system_campaign_p03_PTLA_history as previous
import system_campaign_p03_PFNX_source as source
import system_campaign_p03_PFNX_resources as resources
PREFIX=resources.PREFIX
PARENT=PREFIX+'/origin/parent-checkpoint.json.gz'
DIRECTORY=PREFIX+'/adoption'
NEUTRAL=DIRECTORY+'/checkpoint.json.gz'
PROOF=DIRECTORY+'/proof.json'
OVERLAY=PREFIX+'/input-overlay.json'
SOURCE=PREFIX+'/event-source.json'
CATALOG=PREFIX+'/source-catalog.json'
QUALIFICATION=PREFIX+'/packet-qualification.json'
PACKET_FLAGS=('unselected_has_no_right_value','native_day_bar_preserved','effective_day_quote_absent',
 'original_incomplete_guard_retained','wrong_predecessor_and_consumed_native_cursor_refused','no_financial_transition')

def spec():return resources.spec()

def full_parent(root,parent):
 from full_system_core import hosted
 hosted();resources.parent_contract(parent,spec());source.parent_contract(parent,spec())
 result=previous.full(root,parent)
 need(result['passed'] is True and result['full_inputs']==21,'PFNX_HISTORY_WHOLE_ACTUAL_ADMITTED_PTLA_FULL21_VISITOR')
 return result

def archived_parent(member):
 raw=member(PARENT);target=spec();need(resources.pin(raw)==target['selected_file'],'PFNX_HISTORY_ONLY_GENUINE671_ARCHIVE_BYTES')
 parent=strict_json(raw);source.parent_contract(parent,target);return parent

def packet_qualification(value,parent):
 catalog=source.catalog();doc=source.document(parent,value=catalog);packet=value['packet']
 need(value['passed'] is True and value['catalog_sha256']==sha(source.encoded(catalog))
  and value['typed_document_sha256']==sha(source.encoded(doc)) and value['market_source_sha256']==catalog['market_source_sha256']
  and type(value['financial_sessions_advanced']) is int and value['financial_sessions_advanced']==0
  and type(packet['actual_packet_checks']) is int and packet['actual_packet_checks']==2 and packet['actual_selected_signal_range']==[12.,14.]
  and all(packet[k] is True for k in PACKET_FLAGS),'PFNX_HISTORY_COMPLETE_ORIGINAL_TWO_PACKET_AND_FULL_RANGE_QUALIFICATION')
 return True

def document(parent,member):
 value=source.catalog();doc=source.document(parent,value=value)
 need(member(CATALOG)==source.encoded(value) and member(SOURCE)==source.encoded(value['market_source']) and member(OVERLAY)==source.encoded(doc),
  'PFNX_HISTORY_ENTIRE_COMMITTED_CATALOG_MARKET_AND_TYPED_INPUT')
 packet_qualification(json.loads(member(QUALIFICATION)),parent);return doc

def history_function():
 fn=templates.history;scope=dict(vars(templates),spec=spec,document=document,PARENT=PARENT,NEUTRAL=NEUTRAL,PROOF=PROOF,
  source=SimpleNamespace(**dict(vars(source),DAY=source.NATIVE)))
 bound=FunctionType(fn.__code__,scope,fn.__name__,fn.__defaults__);bound.__kwdefaults__=dict(fn.__kwdefaults__,previous_history=full_parent)
 return bound

def history(root,current,*,member,previous_history=full_parent):
 return history_function()(root,current,member=member,previous_history=previous_history)

def full(root,current):
 root=Path(root);return history(root,current,member=lambda name:(root/name).read_bytes())

def boundary_tree(raw):
 need(sha(raw)==sha(Path(templates.__file__).read_bytes()),'PFNX_HISTORY_WHOLE_EXISTING_CANONICAL_BOUNDARY_SOURCE')
 fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='boundary'];hits={19:0,20:0}
 for node in ast.walk(fn):
  if isinstance(node,ast.Constant) and type(node.value) is int and node.value in hits:
   old=node.value;node.value={19:21,20:22}[old];hits[old]+=1
 need(hits=={19:1,20:2},'PFNX_HISTORY_ONLY_EXACT_ORIGINAL_BOUNDARY_COUNT_SITES');return ast.fix_missing_locations(fn)

def boundary(parent,neutral,member,rows):
 scope=dict(vars(templates),spec=spec,archived_parent=archived_parent,document=document,NEUTRAL=NEUTRAL,PROOF=PROOF,DIRECTORY=DIRECTORY,
  source=SimpleNamespace(**dict(vars(source),DAY=source.NATIVE)))
 exec(compile(ast.Module(body=[boundary_tree(Path(templates.__file__).read_bytes())],type_ignores=[]),'<whole-original-boundary-actual21-to22>','exec'),scope)
 return scope['boundary'](parent,neutral,member,rows)

def source_names():return (Path(__file__).name,Path(templates.__file__).name,Path(previous.__file__).name,Path(original.__file__).name,*resources.source_names())
