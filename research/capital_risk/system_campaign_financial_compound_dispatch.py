"""Version selection and outer retention; immutable input generations coexist."""
from contextlib import contextmanager, ExitStack
import ast
import inspect
import json
from pathlib import Path
from types import CodeType

from system_campaign_financial_compound_input_v2 import need,sha


def versions():
    import system_campaign_financial_compound_runtime as v1
    import system_campaign_financial_compound_runtime_v2 as v2
    import system_campaign_financial_distribution_standard_runtime as standard
    return (v1,v2,standard)


def selected(cp,arm):
    found=[v for v in versions() if v.applies(cp,arm)]
    need(len(found)<=1,'COMPOUND_VERSION_ONE_UNAMBIGUOUS_EXACT_INITIAL_PHASE')
    return found[0] if found else None


def retained_versions(root,cp):
    root=Path(root);modules=versions();found={m.CATALOG_REF:[] for m in modules}
    for d in cp['repairs']:
        raw=(root/'book/repairs'/d['filename']).read_bytes()
        need(sha(raw)==d['sha256'],'COMPOUND_VERSION_ALL_RETAINED_SOURCE_BYTES')
        for row in json.loads(raw).get('source_evidence',[]):
            if row['reference'] in found:found[row['reference']].append(d)
    need(all(len(v)<=1 for v in found.values()),'COMPOUND_VERSION_ONE_ACTIVATION_PER_GENERATION')
    descriptors=[v[0] for v in found.values() if v]
    phases=[(v['resume_session'],v['predecessor_checkpoint_sha256']) for v in descriptors]
    need(len(set(phases))==len(phases),'COMPOUND_VERSION_NO_AMBIGUOUS_SAME_PHASE_ADOPTION')
    return tuple(m for m in modules if found[m.CATALOG_REF])


@contextmanager
def retained_loader_surfaces(modules):
    """Let original inner codecs capture the actual retained projection loader."""
    if not modules:
        yield
        return
    from research.pooled_vacancy_funding import backtest, repair
    installed = backtest.load_repair
    owner = getattr(installed, '__self__', None)
    need(any(isinstance(owner, module.ProjectionContext) for module in modules)
         and owner.active and owner.api.backtest is backtest and owner.api.repair is repair,
         'COMPOUND_RETAINED_EXACT_ACTIVE_INSTALLED_LOADER_OWNER')
    original = repair.load_repair
    repair.load_repair = installed
    try:
        yield
    finally:
        repair.load_repair = original


_RETAINED_CALLER_BINDINGS = {}


def _caller_code_shape(code):
    return (code.co_code, code.co_argcount, code.co_posonlyargcount, code.co_kwonlyargcount,
            code.co_flags, code.co_names, code.co_varnames, code.co_freevars, code.co_cellvars,
            tuple(_caller_code_shape(value) if isinstance(value, CodeType) else value
                  for value in code.co_consts))


def _observer_terminal_code(raw, *, module_context=True):
    if not module_context:
        owner, = [n for n in ast.parse(raw).body if isinstance(n, ast.ClassDef) and n.name == 'ActualEvents']
        function, = [n for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == 'terminal']
        namespace = {}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])),
                     '<source-qualified-frozen-observer-terminal-code-only>', 'exec'), namespace)
        return _caller_code_shape(namespace['terminal'].__code__)
    module = compile(raw, '<source-qualified-observer-module-code-only>', 'exec', dont_inherit=True)
    owner, = [code for code in module.co_consts if isinstance(code, CodeType) and code.co_name == 'ActualEvents']
    function, = [code for code in owner.co_consts if isinstance(code, CodeType) and code.co_name == 'terminal']
    return _caller_code_shape(function)


def _observer_predicate_code(raw, *, module_context=True):
    if not module_context:
        function, = [n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef) and n.name == 'actual_terminal_call']
        namespace = {}
        exec(compile(ast.fix_missing_locations(ast.Module(body=[function], type_ignores=[])),
                     '<source-qualified-frozen-observer-predicate-code-only>', 'exec'), namespace)
        return _caller_code_shape(namespace['actual_terminal_call'].__code__)
    module = compile(raw, '<source-qualified-observer-module-code-only>', 'exec', dont_inherit=True)
    function, = [code for code in module.co_consts if isinstance(code, CodeType) and code.co_name == 'actual_terminal_call']
    return _caller_code_shape(function)


def _terminal_delegation_call(frame, callee, step_code, state, ledger, session, *, original, terminal, binding):
    """Qualify transparent foreign observer frames, then use the original gate."""
    receiver = callee.f_locals.get('self')
    inner_owner, inner_function = binding(getattr(receiver, 'terminal', None))
    terms = callee.f_locals.get('terms');kwargs = callee.f_locals.get('kwargs')
    need(callee.f_code is inner_function.__code__ and inner_owner.step_code is step_code and callee.f_locals.get('state') is state
         and isinstance(kwargs, dict) and kwargs.get('ledger') is ledger
         and terms is not None and terms.session == session,
         'RETAINED_CALLER_EXACT_RECEIVING_OBSERVER_FRAME')
    outer_owner, outer_function = inner_owner, inner_function
    while frame.f_code is not step_code:
        owner, function = binding(getattr(frame.f_locals.get('self'), 'terminal', None))
        forwarded = frame.f_locals.get('kwargs')
        need(frame.f_code is function.__code__ and owner.step_code is step_code and frame.f_locals.get('self') is owner
             and frame.f_locals.get('state') is state and frame.f_locals.get('terms') is terms
             and isinstance(forwarded, dict) and forwarded.keys() == kwargs.keys()
             and all(forwarded[key] is kwargs[key] for key in kwargs)
             and forwarded.get('ledger') is ledger,
             'RETAINED_CALLER_FOREIGN_FRAME_ARGUMENTS_IDENTICAL')
        need(owner.current is not None and (terms.session, terms.security_id) not in owner.terms,
             'RETAINED_CALLER_ONLY_FOREIGN_UNSELECTED_TERMINAL_DELEGATION')
        delegated = owner.terminal_original
        need(getattr(delegated, '__self__', None) is inner_owner
             and getattr(delegated, '__func__', None) is inner_function,
             'RETAINED_CALLER_COMPLETE_EXACT_OBSERVER_DELEGATION_CHAIN')
        inner_owner, inner_function = owner, function
        outer_owner, outer_function = owner, function
        frame = frame.f_back
        need(frame is not None, 'RETAINED_CALLER_CANONICAL_FRAME_REQUIRED')
    installed = terminal.apply_terminal
    need(getattr(installed, '__self__', None) is outer_owner
         and getattr(installed, '__func__', None) is outer_function,
         'RETAINED_CALLER_OUTERMOST_OBSERVER_ACTUALLY_INSTALLED')
    return original(frame, step_code, state, ledger, session)


@contextmanager
def retained_terminal_callers(modules):
    if not modules:
        yield
        return
    import system_campaign_financial_future as future
    from stock_strategy_shared.wealth_core import terminal
    frozen_path = Path(__file__).parent / 'system_campaign_financial_ordinary_observer_v1.py'
    frozen = frozen_path.read_bytes();future_raw = Path(future.__file__).read_bytes()
    request = json.loads((Path(__file__).parent / 'system-campaign-factual-request.json').read_bytes())
    need(sha(frozen) == 'a09361056879e891d831daec06686895a6cbb20dca0b1a0a9cded8dae1c650a3'
         and sha(future_raw) == request['sources']['system_campaign_financial_future.py'],
         'RETAINED_CALLER_EXACT_ORIGINAL_AND_CURRENT_OBSERVER_SOURCES')
    shapes = {str(frozen_path.resolve()): _observer_terminal_code(frozen, module_context=False),
              str(Path(future.__file__).resolve()): _observer_terminal_code(future_raw)}
    gates = {str(frozen_path.resolve()): _observer_predicate_code(frozen, module_context=False),
             str(Path(future.__file__).resolve()): _observer_predicate_code(future_raw)}

    def binding(method):
        owner = getattr(method, '__self__', None);function = getattr(method, '__func__', None)
        namespace = getattr(function, '__globals__', {})
        path = str(Path(namespace.get('__file__', '')).resolve())
        cls = namespace.get('ActualEvents')
        need(owner is not None and cls is not None and isinstance(owner, cls)
             and function is cls.terminal and path in shapes
             and _caller_code_shape(function.__code__) == shapes[path],
             'RETAINED_CALLER_EXACT_SOURCE_QUALIFIED_OBSERVER_CODE_AND_OWNER')
        return owner, function

    changes = [];method = terminal.apply_terminal
    try:
        while getattr(method, '__self__', None) is not None:
            owner, function = binding(method);namespace = function.__globals__;key = id(namespace)
            if not any(value[0] is namespace for value in changes):
                previous = _RETAINED_CALLER_BINDINGS.get(key)
                current = namespace['actual_terminal_call']
                if previous is not None:
                    need(previous[0] is namespace and current is previous[2],
                         'RETAINED_CALLER_NESTED_BINDING_EXACT_NAMESPACE_AND_FUNCTION')
                original = previous[1] if previous is not None else current
                need(getattr(original, '__globals__', None) is namespace
                     and _caller_code_shape(original.__code__) == gates[str(Path(namespace['__file__']).resolve())],
                     'RETAINED_CALLER_EXACT_UNCHANGED_ORIGINAL_GATE_CALLBACK')
                def routed(frame, step_code, state, ledger, session, original=original):
                    return _terminal_delegation_call(frame, inspect.currentframe().f_back, step_code,
                        state, ledger, session, original=original, terminal=terminal, binding=binding)
                changes.append((namespace, current, previous))
                namespace['actual_terminal_call'] = routed
                _RETAINED_CALLER_BINDINGS[key] = (namespace, original, routed)
            method = owner.terminal_original
        yield
    finally:
        for namespace, original, previous in reversed(changes):
            namespace['actual_terminal_call'] = original
            if previous is None:_RETAINED_CALLER_BINDINGS.pop(id(namespace), None)
            else:_RETAINED_CALLER_BINDINGS[id(namespace)] = previous


@contextmanager
def retained_context(root,cp,out):
    # Both enter outside the preexisting B19/APHA stack. Each delegates foreign
    # parsed object types; neither hides Codec from APHA's immutable unwrap.
    retained = retained_versions(root,cp)
    with ExitStack() as stack:
        for module in versions():stack.enter_context(module.retained_context(root,cp,out))
        with retained_loader_surfaces(retained), retained_terminal_callers(retained):
            yield


def review_retained(root,cp):
    for module in retained_versions(root,cp):
        if hasattr(module,'review_retained'):module.review_retained(root,cp)


@contextmanager
def initial_context(cp,out,spec,loaded):
    module=selected(cp,spec['arm'])
    need(module is not None,'COMPOUND_VERSION_INITIAL_REQUIRES_ONE_SELECTED_PHASE')
    if module.__name__.endswith('_v2'):
        from system_campaign_financial_resume import AdoptionGate
        with AdoptionGate(cp,Path(out)/'book',Path(out)/'input-adoption',loaded.sha256,loaded.earliest_affected_session):
            with module.initial_context(cp,out,spec,loaded),module.ordinary_events(out,cp):yield
    else:
        with module.initial_context(cp,out,spec,loaded):yield
