"""Unselected typed two-GiB normal P02 admission; original helper stays strict."""
import ast,hashlib,re
from pathlib import Path
import system_campaign_factual_admit as original
from full_system_benchmark import need

SOURCE_SHA='63660cd6b2567099db9cb3d1cd9a8b05a16d54ceb1aa50a3f3acfa6d91bd6bd4'
GIB=1024**3
ANCESTOR='lineage/verified-ancestor.zip'


def archive_bound(spec,limit):
    need(type(limit) is int and limit==2*GIB and type(spec['zip_bytes']) is int
         and GIB<=spec['zip_bytes']<limit and spec['arm']=='P02'
         and spec['stage']=='campaign-factual-suffix'
         and spec['receipt_schema']=='research.system-p02-uncertainty-suffix-receipt/1'
         and spec['receipt_name']=='p02-uncertainty.json'
         and not spec.get('unadvanced_qualification_failure') and not spec.get('review_refusal'),
         'LARGE_ADMIT_EXPLICIT_NORMAL_REVIEWED_P02_SCOPE')
    ancestor=spec['known_opaque_ancestor']
    need(set(ancestor)=={'path','bytes','sha256'} and ancestor['path']==ANCESTOR
         and type(ancestor['bytes']) is int and 0<ancestor['bytes']<2*GIB
         and re.fullmatch('[a-f0-9]{64}',ancestor['sha256']) is not None,
         'LARGE_ADMIT_EXPLICIT_ONE_OPAQUE_ANCESTOR')
    inspections=spec['inspections']
    need(set(inspections)=={'economic-worker-inspect.json','independent-review-stop/worker-inspect.json'}
         and inspections['economic-worker-inspect.json']['exit_code'] in (0,1,2)
         and inspections['independent-review-stop/worker-inspect.json']['exit_code']==0
         and re.fullmatch('[a-f0-9]{64}',spec['review_sha256']) is not None,
         'LARGE_ADMIT_ACTUAL_NORMAL_WORKER_AND_PASSED_REVIEW_COMMITMENTS')


def inventory_bound(spec,inventory):
    ancestor=spec['known_opaque_ancestor'];expected=dict(bytes=ancestor['bytes'],sha256=ancestor['sha256'])
    need(0<len(inventory)<5000 and inventory.get(ANCESTOR)==expected,
         'LARGE_ADMIT_EXACT_PINNED_OPAQUE_MEMBER')
    total=sum(e['bytes'] for e in inventory.values());ordinary=[e for n,e in inventory.items() if n!=ANCESTOR]
    need(total<=2*GIB and sum(e['bytes'] for e in ordinary)<GIB
         and all(type(e['bytes']) is int and 0<=e['bytes']<256*1024**2 for e in ordinary),
         'LARGE_ADMIT_TWO_GIB_TOTAL_ONE_GIB_UNIQUE_AND_SMALL_NORMAL_MEMBERS')
    return True


def compiled_admit(raw,*,expected_sha256=SOURCE_SHA):
    need(hashlib.sha256(raw).hexdigest()==expected_sha256==SOURCE_SHA,'LARGE_ADMIT_EXACT_UNCHANGED_ORIGINAL_SOURCE')
    tree=ast.parse(raw);nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='admit']
    need(len(nodes)==1 and not nodes[0].decorator_list,'LARGE_ADMIT_SINGLE_ORIGINAL_METADATA_FUNCTION')
    function=nodes[0];zip_sites=plain_sites=0
    for node in ast.walk(function):
        if isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='archive_bound':
            need(ast.unparse(node)=='archive_bound(spec, max_zip_bytes)','LARGE_ADMIT_EXACT_ZIP_BOUND_SITE')
            node.func.id='_typed_archive_bound';zip_sites+=1
        if (isinstance(node,ast.Call) and isinstance(node.func,ast.Name) and node.func.id=='need'
            and len(node.args)==2 and isinstance(node.args[1],ast.Constant) and node.args[1].value=='FACTUAL_PLAINTEXT_BOUND'):
            need(ast.unparse(node.args[0])=="len(inventory) < 5000 and sum((v['bytes'] for v in inventory.values())) < 1024 ** 3",
                 'LARGE_ADMIT_EXACT_PLAINTEXT_BOUND_SITE')
            node.args[0]=ast.Call(func=ast.Name(id='_typed_inventory_bound',ctx=ast.Load()),
                                 args=[ast.Name(id='spec',ctx=ast.Load()),ast.Name(id='inventory',ctx=ast.Load())],keywords=[])
            plain_sites+=1
    need(zip_sites==plain_sites==1,'LARGE_ADMIT_EXACT_TWO_TRANSFORM_SITES')
    scope=dict(vars(original));scope.update(_typed_archive_bound=archive_bound,_typed_inventory_bound=inventory_bound)
    module=ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[]))
    exec(compile(module,'<unchanged-admission-with-typed-large-archive-guards>','exec'),scope)
    return scope['admit']


def admit(spec,root,key,*,max_zip_bytes=2*GIB):
    # Reject locally before credentials, filesystem creation or source compilation.
    original.check_context(original.os.environ)
    archive_bound(spec,max_zip_bytes)
    return compiled_admit(Path(original.__file__).read_bytes())(spec,root,key,max_zip_bytes=max_zip_bytes)
