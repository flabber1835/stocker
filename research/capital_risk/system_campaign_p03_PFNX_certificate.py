"""Whole original consumed DOVA/STML factory, then one original PFNX layer."""
import ast
from pathlib import Path
from types import FunctionType
from full_system_benchmark import need
from system_campaign_facts import sha
import system_campaign_p03_PTLA_certificate as previous
import system_campaign_p03_PFNX_history as history
import system_campaign_second_bounded_factory as factory
resources,source=history.resources,history.source
bind_consumed=previous.bind_consumed

def archived_bases_function():
 fn=previous.archived_bases
 bound=FunctionType(fn.__code__,dict(fn.__globals__,resources=resources,history=history),fn.__name__,fn.__defaults__)
 bound.__kwdefaults__=fn.__kwdefaults__;return bound

def archived_bases(root,parent,rows,qualified):return archived_bases_function()(root,parent,rows,qualified)

def consumed_tree(raw):
 need(sha(raw)==sha(Path(previous.__file__).read_bytes()),'PFNX_CERTIFICATE_WHOLE_ORIGINAL_CONSUMED_TWO_EVENT_FACTORY')
 fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='certificate_class'];hits=0
 for node in ast.walk(fn):
  if isinstance(node,ast.Compare) and ast.unparse(node.left)=="history.full(root, current)['full_inputs']" and len(node.comparators)==1:
   need(isinstance(node.comparators[0],ast.Constant) and node.comparators[0].value==21,'PFNX_CERTIFICATE_ONE_ORIGINAL_HISTORY_COUNT_PER_GUARD')
   node.comparators[0].value=22;hits+=1
 need(hits==2,'PFNX_CERTIFICATE_EXACT_TWO_ORIGINAL_FULL_HISTORY_COUNT_SITES');return ast.fix_missing_locations(fn)

def consumed_function():
 scope=dict(vars(previous),history=history,resources=resources,archived_bases=archived_bases)
 exec(compile(ast.Module(body=[consumed_tree(Path(previous.__file__).read_bytes())],type_ignores=[]),'<whole-original-DOVA-STML-factory-genuine217-and-neutral22>','exec'),scope)
 return scope['certificate_class']

def certificate_class(codec,parent,current,spec,baseline,root):
 from full_system_core import hosted
 hosted()
 from system_campaign_financial_branches import Certificate
 from system_campaign_second_bounded_codec import SuccessorCodec
 value=source.catalog();resources.seed_contract(parent,baseline[1],baseline[2])
 need(history.full(root,current)['full_inputs']==22 and current['run']['state']==parent['run']['state'],
  'PFNX_CERTIFICATE_GENUINE_CANONICAL_NEUTRAL22_UNCHANGED671_STATE')
 need(type(codec) is SuccessorCodec and codec.event==value['event'] and codec.evidence==source.evidence(value) and codec.objects,
  'PFNX_CERTIFICATE_ACTUAL_INSTALLED_PFNX_TYPED_CODEC_AND_OBJECTS')
 old=codec.previous_owner();joint=consumed_function()(old,parent,current,spec,baseline,root)
 result=factory.second_factory(value['event'],value['market_source'],codec,codec.native,inherited_root=Path(previous.dova.__file__).parent,previous_class=joint)
 need(result.append is joint.append is Certificate.append and issubclass(result,joint)
  and result.__dict__['_bounded_layer_codec'] is codec and joint.__dict__['_bounded_layer_codec'] is old,
  'PFNX_CERTIFICATE_ONE_B19_APPEND_AND_COMPLETE_THREE_EVENT_CHAIN')
 # The new event keeps its original pre-event seed predicate; only DOVA/STML are consumed.
 return result

def source_names():return (Path(__file__).name,Path(previous.__file__).name,Path(factory.__file__).name,*history.source_names())
