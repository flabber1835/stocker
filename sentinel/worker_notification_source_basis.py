"""One exact diagnostic-only publisher successor; never arbitrary source reuse."""
from __future__ import annotations

import ast
import hashlib
import json

MODULE = 'sentinel.feed.rolling_publisher'
BASE_REVISION = '596e8496bb0028498847f8e8a4afb26df3f786ba'
REVIEWED_REVISION = '49faad3aa8cbb815b26f5fad3fc85e57588943db'
BASE_SHA256 = '30f3bb476e7dd07f0dbb201cd6f0f035f3f9beaad8efb7d4ac166d03b4c0068d'
REVIEWED_SHA256 = 'b31e0429c4e9c235c9ae18b39f98ce93b03f6817a973107c8aa83d9889c9d443'
BASE_AST_SHA256 = '792f5dab3a95a3df3d1cd9ff49e67a7dc5835be2cffe87e8def0549ab9ea0185'
STAGE_SEQUENCE = (
    'SHADOW_ADVANCE', 'ACQUISITION_LOCK', 'SOURCE_PREFLIGHT', 'SOURCE_PREFLIGHT',
    'SOURCE_REFERENCES', 'PRICE_ACQUISITION', 'CANDIDATE_BUILD',
    'CANDIDATE_VALIDATION', 'SOURCE_CORROBORATION', 'PUBLICATION',
)
DIAGNOSTIC_IMPORT = 'from sentinel import shadow_dependency_notifications as notices'
DIAGNOSTIC_CALL = 'notices.capture_stage(exc, operation_stage)'


def contribution(raw: bytes) -> str:
    """Closed source pair; every other byte sequence contributes its real hash."""
    actual = hashlib.sha256(raw).hexdigest()
    if actual in {BASE_SHA256, REVIEWED_SHA256}:
        return BASE_SHA256
    return actual


def remaining_ast_sha256(raw: bytes, *, baseline: bool = False) -> str:
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
