"""Entire existing35-term observer/review on the complete actual21/22 history."""
from pathlib import Path
from types import FunctionType
from full_system_benchmark import need
import system_campaign_p03_PTLA_observers as previous
import system_campaign_p03_PFNX_history as history

def tail_materials(root,current):
 root=Path(root);result=history.full(root,current)
 need(result['passed'] is True and result['full_inputs']==len(current['repairs']) and len(current['repairs'])in (21,22),
  'PFNX_OBSERVER_WHOLE_ACTUAL_CURRENT21_OR22_BEFORE_METADATA_USE')
 parent=current if current['sha256']==history.spec()['outer_sha256'] else history.archived_parent(lambda n:(root/n).read_bytes())
 history.resources.parent_contract(parent,history.spec())
 return previous.tail_materials(root,parent,validate_history=history.full_parent)

def bind(name):
 fn=previous.bind
 bound=FunctionType(fn.__code__,dict(fn.__globals__,tail_materials=tail_materials),fn.__name__,fn.__defaults__)
 bound.__kwdefaults__=fn.__kwdefaults__;return bound(name)

def observer(root,current):
 from full_system_core import hosted
 hosted();return bind('observer')(root,current)

def review(root,current,out):
 from full_system_core import hosted
 hosted();return bind('review')(root,current,out)

def stage_retained(root,current,out):
 from full_system_core import hosted
 hosted();return bind('stage_retained')(root,current,out)

def source_names():return (Path(__file__).name,Path(previous.__file__).name,Path(previous.original.__file__).name,*history.source_names())
