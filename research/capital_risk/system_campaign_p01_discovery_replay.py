"""Source-bound discovery body; only full-checkpoint scheduling differs."""
import ast
from copy import deepcopy
import json
from pathlib import Path
from full_system_benchmark import need
from system_campaign_facts import sha
import system_campaign_discovery_replay as original

def replay_tree(raw):
    prior=json.loads((Path(__file__).parent/'system-campaign-p02-remainder-request.json').read_bytes())
    need(sha(raw)==prior['sources']['system_campaign_discovery_replay.py'],
         'P01_EXACT_QUALIFIED_DISCOVERY_REPLAY_SOURCE')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='replay']
    fn=deepcopy(fn)
    loop,=[n for n in ast.walk(fn) if isinstance(n,ast.For)
           and isinstance(n.target,ast.Name) and n.target.id=='expected' and ast.unparse(n.iter)=='wanted']
    calls=[(i,n) for i,n in enumerate(loop.body) if isinstance(n,ast.Expr)
           and isinstance(n.value,ast.Call) and ast.unparse(n.value.func)=='checkpoint']
    need(len(calls)==1,'P01_ONE_PER_SESSION_CHECKPOINT_SCHEDULING_SITE')
    index,node=calls[0]
    loop.body[index]=ast.If(test=ast.Compare(left=ast.Attribute(value=ast.Name(id='packet',ctx=ast.Load()),attr='day',ctx=ast.Load()),
        ops=[ast.In()],comparators=[ast.Name(id='checkpoint_days',ctx=ast.Load())]),body=[node],orelse=[])
    sites=[]
    for parent in ast.walk(fn):
        for field,value in ast.iter_fields(parent):
            if not isinstance(value,list):continue
            for i,n in enumerate(value):
                if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='complete':
                    sites.append((value,i))
    need(len(sites)==1,'P01_ONE_NORMAL_OR_SIGNAL_STOP_FINAL_CHECKPOINT_SITE')
    body,index=sites[0];body[index:index]=ast.parse('checkpoint()').body
    assignment,=[i for i,n in enumerate(fn.body) if isinstance(n,ast.Assign)
        and isinstance(n.value,ast.Call) and ast.unparse(n.value.func)=='source_iterator']
    fn.body[assignment+1:assignment+1]=ast.parse("checkpoint_days=set({day[:7]:day for day in wanted}.values())-{wanted[-1]}").body
    return ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[]))

def replay(*args,**kwargs):
    scope=dict(vars(original))
    exec(compile(replay_tree(Path(original.__file__).read_bytes()),
                 '<qualified-original-discovery-month-end-checkpoint-scheduling>','exec'),scope)
    return scope['replay'](*args,**kwargs)
