"""Exact own-kernel POST_PLAN proof; canonical delegates remain unchanged."""
import ast
from copy import deepcopy
from dataclasses import fields, is_dataclass
import inspect
from pathlib import Path
from types import CodeType

from system_campaign_p10_ahl2_contract import need, sha, digest, AFFECTED
from system_campaign_p10_ahl2_context import frozen_body
import system_campaign_p10_ahl2_observe as original

KERNEL = 'sentinel/core/kernel.py'
KERNEL_SHA = 'd8a630466fc0c6668fbe98b1fe18f0514c8b70e5b2d1faaa8c9d6ba237fce739'


def code_source_valid(code,raw,filename):
    # Compile for code comparison only; never execute the compiled module.
    module = compile(raw,filename,'exec',dont_inherit=True,optimize=0)
    expected = [c for c in module.co_consts if isinstance(c,CodeType) and c.co_name == 'advance_session']
    need(len(expected) == 1 and code == expected[0] and code.co_filename == filename,
         'P10_POST_PLAN_ACTUAL_CODE_CONTENT_EQUALS_EXACT_AUTHENTICATED_SOURCE')


def source_shape(raw):
    need(sha(raw) == KERNEL_SHA, 'P10_POST_PLAN_EXACT_OWN_KERNEL_BEFORE_AST')
    fn, = [n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef) and n.name == 'advance_session']
    plans = [n for n in ast.walk(fn) if isinstance(n, ast.Assign)
             and [ast.unparse(t) for t in n.targets] == ['plan']
             and isinstance(n.value, ast.Call) and ast.unparse(n.value.func) == 'plan_session']
    need(len(plans) == 1 and plans[0] in fn.body, 'P10_POST_PLAN_ONE_TOP_LEVEL_COMPLETED_PLAN')
    calls = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
             and ast.unparse(n.func) == 'terminal_returns.values']
    need(len(calls) == 1, 'P10_POST_PLAN_ONE_ACTUAL_VALUES_CALLSITE')
    call = calls[0]
    owners = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
              and ast.unparse(n.func) == 'median5_controller.witness'
              and any(k.arg == 'terminal_values' and k.value is call for k in n.keywords)]
    need(len(owners) == 1 and plans[0].end_lineno < call.lineno
         and ast.unparse(call) == 'terminal_returns.values(prior=env, published=published)',
         'P10_POST_PLAN_WITNESS_AFTER_COMPLETED_PLAN_EXACT_ARGUMENTS')
    return dict(module_sha256=sha(raw), function_ast_sha256=sha(ast.dump(fn, include_attributes=False).encode()),
                function_start=fn.lineno, function_end=fn.end_lineno,
                plan_start=plans[0].lineno, plan_end=plans[0].end_lineno,
                values_start=call.lineno, values_end=call.end_lineno)


def frame_proof(frame, *, code, globals_, prior, view, record, source):
    """Pure frame/data predicate; actual code/global objects are bound on enter."""
    need(frame.f_code is code and frame.f_globals is globals_
         and globals_.get('__name__') == 'sentinel.core.kernel'
         and source['values_start'] <= frame.f_lineno <= source['values_end'],
         'P10_POST_PLAN_ACTUAL_CODE_OBJECT_GLOBALS_AND_CALLSITE')
    local = frame.f_locals
    need(local.get('env') is prior and local.get('plan') is not None,
         'P10_POST_PLAN_EXACT_PRIOR_AND_COMPLETED_PLAN_LOCAL')
    full = local.get('published')
    need(is_dataclass(full) and type(view) is type(full) and len(view.terminal_events) == 1
         and any(view.terminal_events[0] is term for term in full.terminal_events)
         and all(getattr(view, field.name) is getattr(full, field.name)
                 for field in fields(full) if field.name != 'terminal_events'),
         'P10_POST_PLAN_EXACT_SINGLE_TERM_VIEW_ALL_OTHER_FIELDS_IDENTICAL')
    need(record['session'] == full.session == AFFECTED and record['engines']
         and 'ENGINE_RETURN' in record['order'],
         'P10_POST_PLAN_ACTUAL_ENGINE_RETURN_PRECEDES_SENSOR')
    return full


def sensor_record_valid(record, source):
    need(digest(record['publication']) == record['publication_sha256']
         and len(record['sensors']) == len(record['publication']['terminal_events']) == 3,
         'P10_POST_PLAN_FULL_SERIALIZED_SENSOR_PUBLICATION_AND_VIEW_COUNT')
    for sensor,term in zip(record['sensors'],record['publication']['terminal_events']):
        expected = dict(schema='research.p10-actual-post-plan-callsite/1', **source,
            actual_code_object_identity=True, actual_module_globals_identity=True,
            prior_object_identity=True, completed_plan_local=True,
            engine_return_before_sensor=True, single_term_identity=True,
            all_other_publication_field_objects_identical=True,
            full_publication_sha256=record['publication_sha256'],term_sha256=digest(term),
            prior_runtime_sha256=record['prior']['checkpoint_sha256'])
        need(sensor['post_plan_context'] == expected
             and type(sensor['selected']) is bool and sensor['canonical_kernel_callsite'] is True,
             'P10_POST_PLAN_EACH_SAVED_CONTEXT_EXACT_SOURCE_PRIOR_TERM_AND_ALL_FIELDS')
    return record


def values_tree():
    raw = frozen_body('system_campaign_p10_ahl2_observe.py')
    owner, = [n for n in ast.parse(raw).body if isinstance(n, ast.ClassDef) and n.name == 'Observer']
    fn, = [deepcopy(n) for n in owner.body if isinstance(n, ast.FunctionDef) and n.name == 'values']
    block, = [n for n in fn.body if isinstance(n, ast.If)]
    start, = [i for i, n in enumerate(block.body) if isinstance(n, ast.Assign)
              and ast.unparse(n) == 'frames = []']
    end, = [i for i, n in enumerate(block.body) if isinstance(n, ast.Expr)
            and isinstance(n.value, ast.Call) and ast.unparse(n.value.func) == 'need'
            and len(n.value.args) == 2 and isinstance(n.value.args[1], ast.Constant)
            and n.value.args[1].value == 'P10_SENSOR_ACTUAL_CANONICAL_KERNEL_CALLSITE']
    need(end - start == 3, 'P10_POST_PLAN_EXACT_FAILED_STACK_BLOCK_ONLY')
    block.body[start:end+1] = ast.parse('post_plan_context = self.context_proof(prior, published)').body
    appends = [n for n in ast.walk(fn) if isinstance(n, ast.Call)
               and ast.unparse(n.func) == "self.current['sensors'].append"]
    need(len(appends) == 1 and isinstance(appends[0].args[0], ast.Call)
         and ast.unparse(appends[0].args[0].func) == 'dict', 'P10_POST_PLAN_ONE_SENSOR_PROOF_APPEND')
    appends[0].args[0].keywords.append(ast.keyword(arg='post_plan_context', value=ast.Name(id='post_plan_context', ctx=ast.Load())))
    return ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[]))


class Observer(original.Observer):
    def __enter__(self):
        from full_system_core import hosted
        hosted()
        from sentinel.core import kernel
        path = Path(kernel.__file__).resolve()
        need(path == Path('/variant/sentinel/core/kernel.py')
             and self.binding.source_binding['all_sources'][KERNEL] == KERNEL_SHA,
             'P10_POST_PLAN_ACTUAL_OWN_KERNEL_MODULE_PATH_AND_SOURCE_MAP')
        raw = path.read_bytes()
        self.kernel_source = source_shape(raw)
        self.kernel_code = kernel.advance_session.__code__
        code_source_valid(self.kernel_code,raw,str(path))
        self.kernel_globals = vars(kernel)
        need(kernel.advance_session.__globals__ is self.kernel_globals
             and self.kernel_code.co_filename == str(path)
             and self.kernel_code.co_name == 'advance_session'
             and self.kernel_code.co_firstlineno == self.kernel_source['function_start'],
             'P10_POST_PLAN_BOUND_ACTUAL_ADVANCE_SESSION_FUNCTION')
        return super().__enter__()

    def context_proof(self, prior, view):
        matches = []
        frame = inspect.currentframe().f_back
        try:
            while frame is not None:
                if frame.f_code is self.kernel_code:
                    matches.append(frame)
                frame = frame.f_back
            need(len(matches) == 1, 'P10_POST_PLAN_ONE_ACTUAL_KERNEL_CODE_OBJECT_FRAME')
            full = frame_proof(matches[0], code=self.kernel_code, globals_=self.kernel_globals,
                prior=prior, view=view, record=self.current, source=self.kernel_source)
            need(self.material(full) == self.current['publication']
                 and digest(self.material(full)) == self.current['publication_sha256'],
                 'P10_POST_PLAN_ENTIRE_KERNEL_PUBLICATION_MATCHES_ACTUAL_BEGIN')
            return dict(schema='research.p10-actual-post-plan-callsite/1', **self.kernel_source,
                actual_code_object_identity=True, actual_module_globals_identity=True,
                prior_object_identity=True, completed_plan_local=True,
                engine_return_before_sensor=True, single_term_identity=True,
                all_other_publication_field_objects_identical=True,
                full_publication_sha256=self.current['publication_sha256'],
                term_sha256=digest(self.material(view.terminal_events[0])),
                prior_runtime_sha256=self.current['prior']['checkpoint_sha256'])
        finally:
            matches.clear()
            del frame

    def values(self, *, prior, published):
        scope = dict(vars(original))
        exec(compile(values_tree(), '<exact-p10-post-plan-observation-only>', 'exec'), scope)
        return scope['values'](self, prior=prior, published=published)
