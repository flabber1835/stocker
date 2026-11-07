"""Finite whole-module compiler-context gate identity; frozen v1/v2 bodies."""
import ast,builtins,json
from contextlib import contextmanager
from pathlib import Path
from types import CodeType,FunctionType,SimpleNamespace
import system_campaign_p05_remaining_runtime_v2 as v2

original=v2.original
HERE=Path(__file__).parent
FIELD,MODE=v2.FIELD,v2.MODE
need,sha,encoded=v2.need,v2.sha,v2.encoded
initial,family=v2.initial,v2.family
QUALIFICATION='P05-retained18-whole-module-gate-v3-qualification.json'
V2_Q_SHA='2f0993882df2cdeec70dfcffbde522e5e9c95455977a191559cafdff0542a8db'
METHODS=('__init__','write','advance','__enter__','__exit__')
def source_names():return tuple(sorted(set((Path(__file__).name,QUALIFICATION,*v2.source_names()))))
def qualified_base():
    v2.qualified_base();raw=(Path(v2.__file__).parent/v2.QUALIFICATION).read_bytes()
    need(sha(raw)==V2_Q_SHA,'P05_RUNTIME18_V3_ENTIRE_FROZEN_V2_QUALIFICATION')
    q=json.loads(raw);source=Path(v2.__file__).read_bytes()
    need(q['passed'] is q['prepared'] is True and q['financial_authority'] is False
        and q['files'][Path(v2.__file__).name]==dict(bytes=len(source),sha256=sha(source)),
        'P05_RUNTIME18_V3_WHOLE_FROZEN_V2_RUNTIME_BYTES')
def declaration(spec):
    qualified_base()
    return dict(v2.declaration(spec),whole_module_compiler_context_required_for_gate_identity=True,
        whole_original_gate_ast_sha256=original.GATE_AST)
def whole_module_gate(tree):
    """Compile module; execute only its verified class body defining methods."""
    classes=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='AdoptionGate']
    need(len(classes)==1 and sha(ast.dump(classes[0],include_attributes=False).encode())==original.GATE_AST,
        'P05_RUNTIME18_V3_WHOLE_ORIGINAL_GATE_AST_BEFORE_CLASS_BODY_BUILD')
    module=compile(tree,'<entire-original-module-compile-only-never-executed>','exec',dont_inherit=True)
    candidates=[v for v in module.co_consts if isinstance(v,CodeType) and v.co_name==v.co_qualname=='AdoptionGate']
    need(len(candidates)==1 and candidates[0].co_freevars==(),
        'P05_RUNTIME18_V3_ONE_TOP_LEVEL_WHOLE_MODULE_GATE_CODE_OBJECT')
    body=FunctionType(candidates[0],{'__name__':'system_campaign_financial_resume'})
    result=builtins.__build_class__(body,'AdoptionGate')
    need(all(hasattr(result,n) and isinstance(getattr(result,n).__code__,CodeType) for n in METHODS),
        'P05_RUNTIME18_V3_ALL_FIVE_METHODS_FROM_WHOLE_MODULE_CLASS_CODE')
    return result
def original_gate_tree(raw):
    need(sha(raw)==json.loads((Path(original.__file__).parent/v2.BASE_Q).read_bytes())['files'][Path(original.__file__).name]['sha256'],
        'P05_RUNTIME18_V3_WHOLE_FROZEN_ORIGINAL_GATE_VALIDATOR_SOURCE')
    fn,=[n for n in ast.parse(raw).body if isinstance(n,ast.FunctionDef) and n.name=='original_gate']
    site,=[n for n in fn.body if isinstance(n,ast.Expr) and isinstance(n.value,ast.Call) and isinstance(n.value.func,ast.Name) and n.value.func.id=='exec']
    need(ast.unparse(site)=="exec(compile(ast.Module(body=[cls], type_ignores=[]), '<whole-original-gate-source-method-identity>', 'exec', dont_inherit=True), namespace)",
        'P05_RUNTIME18_V3_ONE_EXACT_ISOLATED_CLASS_COMPILATION_SITE')
    fn.body[fn.body.index(site)]=ast.parse("namespace['AdoptionGate']=whole_module_gate(tree)").body[0]
    return ast.fix_missing_locations(fn)
def original_gate(Original,module_path):
    qualified_base();namespace=dict(vars(original),whole_module_gate=whole_module_gate)
    exec(compile(ast.Module(body=[original_gate_tree(Path(original.__file__).read_bytes())],type_ignores=[]),
        '<whole-original-gate-validator-one-module-context-class-binding>','exec'),namespace)
    return namespace['original_gate'](Original,module_path)
def gate_class(Original,*a,**k):
    base=v2.bind_function(original.gate_class,original_gate=original_gate)
    wrapper=v2.bind_function(v2.gate_class,original=SimpleNamespace(gate_class=base))
    need(base.__code__ is original.gate_class.__code__ and wrapper.__code__ is v2.gate_class.__code__,
        'P05_RUNTIME18_V3_ENTIRE_ORIGINAL_AND_FAILURE_RECLOSING_GATE_WRAPPERS')
    return wrapper(Original,*a,**k)
def selected(*a,**k):return v2.bind_function(v2.selected,declaration=declaration)(*a,**k)
def expected_request(*a,**k):return v2.bind_function(original.expected_request,declaration=declaration,source_names=source_names,HERE=HERE)(*a,**k)
def old_entry(*a,**k):return v2.bind_function(v2.old_entry,selected=selected)(*a,**k)
def entry_context(*a,**k):
    return v2.bind_function(v2.entry_context,selected=selected,old_entry=old_entry,gate_class=gate_class)(*a,**k)
def launch_context(*a,**k):return v2.bind_function(v2.launch_context,selected=selected)(*a,**k)
def bind_launch(*a,**k):return v2.bind_function(v2.bind_launch,launch_context=launch_context)(*a,**k)
