"""One exact scheduling successor, composed with the retained diagnostic seam."""
from __future__ import annotations

import ast
import hashlib
import json

MODULE = 'sentinel.feed.rolling_publisher'
BASE_REVISION = '131cc833923610d095492ca6b6890eadfbe8e163'
BASE_SHA256 = 'b31e0429c4e9c235c9ae18b39f98ce93b03f6817a973107c8aa83d9889c9d443'
REVIEWED_SHA256 = '0911777fdce9a86a27e253856b6f0b9ed927a52124f8dcb4f078311a22a9d8e7'
BASE_AST_SHA256 = 'fbe84f12c7c3f7c6a3a4298bf4a832c62d62940372e82eef5698629601e1677d'
SCHEDULING_IMPORT = 'from sentinel.feed import writer_schedule'
SCHEDULING_CONTEXT = 'writer_schedule.turn(conn, lease)'
INITIALIZATION = 'discard_connection = False'
DISPOSAL_OBSERVATION = 'discard_connection = writer_schedule.connection_discarded(exc)'
REUSABLE_GUARD = 'not discard_connection and not conn.closed'


def normalize_reviewed_source(raw: bytes) -> bytes:
    """Invert only this byte-exact successor before the existing closed seam.

    Unknown source is returned unchanged so the caller hashes its actual bytes.
    This never masks an arbitrary neighboring edit by matching an AST pattern.
    """
    if hashlib.sha256(raw).hexdigest() != REVIEWED_SHA256:
        return raw
    replacements = (
        (f'{SCHEDULING_IMPORT}\n'.encode(), b'', 1),
        (f'{SCHEDULING_CONTEXT}, '.encode(), b'', 3),
        (f'    {INITIALIZATION}\n'.encode(), b'', 1),
        (f'        {DISPOSAL_OBSERVATION}\n'.encode(), b'', 1),
        ((f'        if {REUSABLE_GUARD}:\n'
          '            _record_failure(conn, lease, exc, operational=operational)\n').encode(),
         b'        _record_failure(conn, lease, exc, operational=operational)\n', 1),
        ((f'        if {REUSABLE_GUARD}:\n'
          '            conn.rollback()\n'
          '            staging.clear(conn, run_id=lease.owner)\n'
          '            if operational:\n'
          '                from sentinel.feed import retention\n'
          '                conn.commit()\n'
          '                retention.maintain(conn)\n').encode(),
         (b'        conn.rollback()\n'
          b'        staging.clear(conn, run_id=lease.owner)\n'
          b'        if operational:\n'
          b'            from sentinel.feed import retention\n'
          b'            conn.commit()\n'
          b'            retention.maintain(conn)\n'), 1),
    )
    normalized = raw
    for before, after, count in replacements:
        if normalized.count(before) != count:
            raise ValueError('reviewed publisher scheduling source changed')
        normalized = normalized.replace(before, after)
    if hashlib.sha256(normalized).hexdigest() != BASE_SHA256:
        raise ValueError('reviewed publisher scheduling baseline changed')
    return normalized


def remaining_ast_sha256(raw: bytes, *, baseline: bool = False) -> str:
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
