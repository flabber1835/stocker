"""Versioned full-request APIs for checkout host and flattened mounted driver."""
import ast
from copy import deepcopy
import importlib
import json
from pathlib import Path

from system_campaign_p10_ahl2_contract import need, sha
from system_campaign_p10_ahl2_wire import object_bytes

HERE=Path(__file__).resolve().parent
PRIOR_REQUEST='system-campaign-p10-ahl2-request-001.json'
PRIOR_SHA='f01ac73cf874a07092eaa83b41c2d9bfd274a8de4fdc03e748ed27c6286921fa'
REQUEST='system-campaign-p10-ahl2-context-request-001.json'
WORKFLOW='capital-system-p10-ahl2-context.yml'
WORKFLOW_SHA='0ed598783b78d514177b9fc0232abe95b191e74749016fe0b659f8c968f020d6'
MODULES=tuple('system_campaign_p10_ahl2_context'+suffix+'.py' for suffix in ('','_job','_run','_probe'))
ENTRY='/driver/system_campaign_p10_ahl2_context_run.py'

def prior_request():
    raw=(HERE/PRIOR_REQUEST).read_bytes()
    need(sha(raw)==PRIOR_SHA,'P10_CONTEXT_EXACT_IMMUTABLE445_REQUEST_PREIMAGE')
    value=object_bytes(raw)
    need(len(value['sources'])==445,'P10_CONTEXT_ALL445_PREDECESSOR_SOURCES')
    return value

def frozen_body(name):
    old=prior_request()
    need(type(name) is str and name in old['sources'] and Path(name).name==name,'P10_CONTEXT_ONLY_EXACT_OLD445_FUNCTION_SOURCE')
    raw=(HERE/name).read_bytes()
    need(sha(raw)==old['sources'][name],'P10_CONTEXT_ORIGINAL_PUBLISHED_SOURCE:'+name)
    return raw

def source_closure():
    old=prior_request()['sources']
    need(all(sha((HERE/name).read_bytes())==h for name,h in old.items()),'P10_CONTEXT_EVERY445_PUBLISHED_BYTE_UNCHANGED')
    names=set(old)|{PRIOR_REQUEST,*MODULES};todo=list(MODULES)
    while todo:
        name=todo.pop()
        if not name.endswith('.py'):continue
        for node in ast.walk(ast.parse((HERE/name).read_bytes())):
            modules=([node.module] if isinstance(node,ast.ImportFrom) and node.level==0 else
                     [n.name for n in node.names] if isinstance(node,ast.Import) else [])
            for module in modules:
                target=module+'.py' if module else ''
                if target and '.' not in module and (HERE/target).is_file() and target not in names:
                    names.add(target);todo.append(target)
    return {name:sha((HERE/name).read_bytes()) for name in sorted(names)}

def worker_expected_request():
    """No checkout path, workflow file, repository ancestor or caller-supplied SHA."""
    value=deepcopy(prior_request())
    value.update(schema='research.p10-own-ahl2-diagnostic-context-request/1',workflow=WORKFLOW,
                 workflow_sha256=WORKFLOW_SHA,sources=source_closure())
    value['request_context']=dict(schema='research.p10-host-worker-request-context/1',
        predecessor_request_sha256=PRIOR_SHA,all445_published_source_bytes_unchanged=True,
        host_workflow_actual_bytes_required=True,worker_repository_layout_required=False,
        worker_workflow_file_required=False,worker_raw_request_copy_required=True,
        worker_entrypoint=ENTRY,financial_source_input_and_qualification_scope_unchanged=True)
    return value

def host_expected_request(workflow_path):
    """Host caller supplies the actual checkout workflow path explicitly."""
    path=Path(workflow_path)
    need(path.name==WORKFLOW and sha(path.read_bytes())==WORKFLOW_SHA,'P10_CONTEXT_ACTUAL_HOST_WORKFLOW_BYTES')
    return worker_expected_request()

def worker_raw_request(path):
    raw=Path(path).read_bytes();driver_raw=(HERE/REQUEST).read_bytes()
    need(raw==driver_raw,'P10_CONTEXT_OUT_REQUEST_EXACT_RAW_DRIVER_COPY')
    value=object_bytes(raw)
    need(value==worker_expected_request(),'P10_CONTEXT_ENTIRE_WORKER_REQUEST_MODEL_AND_SOURCE_CLOSURE')
    return value

def entrypoint(role):
    need(role in ('qualify','worker','review'),'P10_CONTEXT_EXACT_DECLARED_ROLE')
    return ['-B','-u',ENTRY,'--mode','discovery' if role=='worker' else role,
            '--spec','/out/spec.json','--request','/out/request.json']

def frozen_namespace(name,functions):
    """Compile exact old functions into an isolated namespace; no old-global edits."""
    raw=frozen_body(name);module=importlib.import_module(name.removesuffix('.py'))
    need(Path(module.__file__).resolve()==(HERE/name).resolve() and sha(Path(module.__file__).read_bytes())==sha(raw),
         'P10_CONTEXT_ACTUAL_OLD_MODULE_NAMESPACE_IDENTITY')
    tree=ast.parse(raw);nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in functions]
    need({n.name for n in nodes}==set(functions),'P10_CONTEXT_EXACT_REQUIRED_OLD_FUNCTION_API')
    namespace=dict(vars(module));return raw,nodes,namespace

def worker_namespace():
    raw,nodes,namespace=frozen_namespace('system_campaign_p10_ahl2_run.py',('main',))
    fn,=nodes
    imports=[n for n in ast.walk(fn) if isinstance(n,ast.ImportFrom) and n.module=='system_campaign_p10_ahl2_job'
             and [(a.name,a.asname) for a in n.names]==[('expected_request',None)]]
    need(len(imports)==1,'P10_CONTEXT_ONE_PUBLISHED_WORKER_REQUEST_IMPORT_SITE')
    imports[0].module='system_campaign_p10_ahl2_context'
    imports[0].names=[ast.alias(name='worker_expected_request',asname='expected_request')]
    sites=[i for i,n in enumerate(fn.body) if isinstance(n,ast.Assign)
           and ast.unparse(n)=='request = json.loads(args.request.read_bytes())']
    need(len(sites)==1,'P10_CONTEXT_ONE_RAW_REQUEST_BEFORE_MODEL_SITE')
    fn.body.insert(sites[0],ast.Expr(ast.Call(func=ast.Name(id='worker_raw_request',ctx=ast.Load()),
        args=[ast.Attribute(value=ast.Name(id='args',ctx=ast.Load()),attr='request',ctx=ast.Load())],keywords=[])))
    namespace['worker_raw_request']=worker_raw_request
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[])),
                 '<p10-context-original-worker-main>','exec'),namespace)
    return namespace
