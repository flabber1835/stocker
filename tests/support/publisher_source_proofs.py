"""Qualification-only exact historical AST proofs and source witnesses."""
import ast
import hashlib
import json
from pathlib import Path

from sentinel import transition_registry
from sentinel.worker_notification_source_basis import (
    STAGE_SEQUENCE, DIAGNOSTIC_IMPORT, DIAGNOSTIC_CALL,
)
from sentinel.corpus_writer_source_basis import (
    SCHEDULING_IMPORT, SCHEDULING_CONTEXT, INITIALIZATION,
    DISPOSAL_OBSERVATION, REUSABLE_GUARD,
)

BASELINE_ROOT = Path(__file__).with_name('simplification_baseline')


def baseline_catalog():
    raw = (BASELINE_ROOT / 'source-witnesses.json').read_bytes()
    if hashlib.sha256(raw).hexdigest() != '81928641311c17e4dbefe5bcb6a06a01dcb920cac77b74318b891ab195d2475e':
        raise ValueError('independent Git source witness catalog changed')
    value = json.loads(raw)
    if value['revision'] != '0067e90b9f3a0e3e0b8c859fe4a90212e750ef16':
        raise ValueError('independent Git source witness revision changed')
    return value


def baseline_source(name):
    """Read unchanged plain source only when it matches the Git witness."""
    value = baseline_catalog()
    raw = (transition_registry.ROOT / name).read_bytes()
    if hashlib.sha256(raw).hexdigest() != value['files'][name]:
        raise ValueError('historical source witness needs explicit hash fixture:' + name)
    return raw


def publisher_baseline():
    raw = (BASELINE_ROOT / 'feed_rolling_publisher.py').read_bytes()
    if hashlib.sha256(raw).hexdigest() != '0911777fdce9a86a27e253856b6f0b9ed927a52124f8dcb4f078311a22a9d8e7':
        raise ValueError('publisher Git baseline changed')
    return raw


def admission_baseline():
    raw = (BASELINE_ROOT / 'runtime_admission.py').read_bytes()
    if hashlib.sha256(raw).hexdigest() != 'e14403cd0b01a454465cd6338d359b3de87f9d35c84da46f3347dd593415f829':
        raise ValueError('admission Git baseline changed')
    return raw


def diagnostic_remaining_ast_sha256(raw: bytes, *, baseline: bool = False) -> str:
    """Qualification only: remove the exact reviewed diagnostic additions."""
    from sentinel.semantic_source_basis import _ast_value

    tree = ast.parse(raw)
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == '_prepare']
    if len(functions) != 1:
        raise ValueError('publisher preparation function changed')
    function = functions[0]
    if not baseline:
        assignments = sorted((node for node in ast.walk(function)
                              if isinstance(node, ast.Assign) and any(
                                  isinstance(target, ast.Name) and target.id == 'operation_stage'
                                  for target in node.targets)), key=lambda node: node.lineno)
        if (len(assignments) != len(STAGE_SEQUENCE)
                or any(len(node.targets) != 1 or not isinstance(node.value, ast.Constant)
                       or node.value.value != stage
                       for node, stage in zip(assignments, STAGE_SEQUENCE))):
            raise ValueError('publisher diagnostic stage sequence changed')
        expected_import = ast.dump(ast.parse(DIAGNOSTIC_IMPORT).body[0])
        expected_call = ast.dump(ast.parse(DIAGNOSTIC_CALL).body[0])
        expected_failure = ast.dump(ast.parse(
            '_record_failure(conn, lease, exc, operational=operational)').body[0])
        handlers = [node for node in ast.walk(function) if isinstance(node, ast.ExceptHandler)
                    and isinstance(node.type, ast.Name) and node.type.id == 'BaseException'
                    and node.name == 'exc']
        if (len(handlers) != 1 or len(handlers[0].body) < 3
                or ast.dump(handlers[0].body[0]) != expected_import
                or ast.dump(handlers[0].body[1]) != expected_call
                or ast.dump(handlers[0].body[2]) != expected_failure):
            raise ValueError('publisher original-failure diagnostic hook changed')
        del handlers[0].body[:2]
        permitted = {id(node) for node in assignments}

        class StripStages(ast.NodeTransformer):
            def visit_Assign(self, node):
                return None if id(node) in permitted else self.generic_visit(node)

        StripStages().visit(function)
    # No administrative name/reference elsewhere may be hidden by this seam.
    if any(isinstance(node, ast.Name) and node.id in {'operation_stage', 'notices'}
           or isinstance(node, ast.ImportFrom) and any(
               item.name == 'shadow_dependency_notifications' for item in node.names)
           for node in ast.walk(tree)):
        raise ValueError('unreviewed publisher diagnostic reference')
    return hashlib.sha256(json.dumps(_ast_value(tree), separators=(',', ':'),
                                     ensure_ascii=True).encode()).hexdigest()

def scheduling_remaining_ast_sha256(raw: bytes, *, baseline: bool = False) -> str:
    """Qualification only: retain the complete AST outside the reviewed scope."""
    from sentinel.semantic_source_basis import _ast_value

    tree = ast.parse(raw)
    if not baseline:
        imports = [node for node in tree.body
                   if ast.dump(node) == ast.dump(ast.parse(SCHEDULING_IMPORT).body[0])]
        if len(imports) != 1:
            raise ValueError('publisher scheduling import changed')
        tree.body.remove(imports[0])
        functions = [node for node in tree.body
                     if isinstance(node, ast.FunctionDef) and node.name == '_prepare']
        if len(functions) != 1:
            raise ValueError('publisher preparation function changed')
        function = functions[0]

        def exact(statement, source):
            return ast.dump(statement) == ast.dump(ast.parse(source).body[0])

        initializations = [node for node in function.body if exact(node, INITIALIZATION)]
        if len(initializations) != 1:
            raise ValueError('publisher scheduling initialization changed')
        function.body.remove(initializations[0])
        scopes = []
        for node in ast.walk(function):
            if not isinstance(node, ast.With):
                continue
            for index, item in enumerate(node.items):
                if ast.dump(item.context_expr) == ast.dump(ast.parse(SCHEDULING_CONTEXT).body[0].value):
                    if item.optional_vars is not None:
                        raise ValueError('publisher scheduling context changed')
                    scopes.append((node, index))
        if len(scopes) != 3:
            raise ValueError('publisher scheduling phase scopes changed')
        for node, index in scopes:
            del node.items[index]

        tries = [node for node in function.body if isinstance(node, ast.Try)]
        if len(tries) != 1:
            raise ValueError('publisher scheduling cleanup boundary changed')
        owned_try = tries[0]
        handlers = [node for node in owned_try.handlers
                    if isinstance(node.type, ast.Name) and node.type.id == 'BaseException'
                    and node.name == 'exc']
        if len(handlers) != 1:
            raise ValueError('publisher scheduling exception boundary changed')
        handler = handlers[0]
        observations = [node for node in handler.body if exact(node, DISPOSAL_OBSERVATION)]
        if len(observations) != 1:
            raise ValueError('publisher scheduling disposal observation changed')
        handler.body.remove(observations[0])
        expected_guard = ast.dump(ast.parse(REUSABLE_GUARD).body[0].value)
        expected_failure = '_record_failure(conn, lease, exc, operational=operational)'
        guards = [node for node in handler.body
                  if isinstance(node, ast.If) and ast.dump(node.test) == expected_guard
                  and not node.orelse and len(node.body) == 1
                  and exact(node.body[0], expected_failure)]
        if len(guards) != 1:
            raise ValueError('publisher scheduling failure-recording guard changed')
        index = handler.body.index(guards[0])
        handler.body[index:index + 1] = guards[0].body
        if (len(owned_try.finalbody) != 1
                or not isinstance(owned_try.finalbody[0], ast.If)
                or ast.dump(owned_try.finalbody[0].test) != expected_guard
                or owned_try.finalbody[0].orelse):
            raise ValueError('publisher scheduling final cleanup guard changed')
        owned_try.finalbody = owned_try.finalbody[0].body
    if any(isinstance(node, ast.Name) and node.id in {'writer_schedule', 'discard_connection'}
           or isinstance(node, ast.ImportFrom) and any(
               item.name == 'writer_schedule' for item in node.names)
           for node in ast.walk(tree)):
        raise ValueError('unreviewed publisher scheduling reference')
    return hashlib.sha256(json.dumps(_ast_value(tree), separators=(',', ':'),
                                     ensure_ascii=True).encode()).hexdigest()
