"""Static private manifest extension using the frozen canonical import resolver."""
from __future__ import annotations

import ast
from functools import lru_cache
import hashlib
import json
from pathlib import PurePosixPath
import re


class SourcePath:
    def __init__(self, files, name):
        self.files, self.name = files, PurePosixPath(name)

    def __truediv__(self, part):
        return SourcePath(self.files, self.name / part)

    def with_suffix(self, suffix):
        return SourcePath(self.files, self.name.with_suffix(suffix))

    def is_file(self):
        return self.name.as_posix() in self.files

    def read_bytes(self):
        return self.files[self.name.as_posix()]


def module_path(files, name):
    roots = {'sentinel': 'sentinel', 'stock_strategy_shared': 'shared/stock_strategy_shared'}
    parts = name.split('.')
    if parts[0] not in roots:
        return None
    return SourcePath(files, PurePosixPath(roots[parts[0]]).joinpath(*parts[1:]))


def module_bytes(files, name):
    path = module_path(files, name)
    if path is None:
        raise ValueError('REFUSED_NONLOCAL_ECONOMIC_MODULE')
    path = path.with_suffix('.py') if path.with_suffix('.py').is_file() else path/'__init__.py'
    if not path.is_file():
        raise ValueError('REFUSED_MISSING_ECONOMIC_MODULE_'+name)
    return path.read_bytes()


def resolver(files):
    # Reuse only these unchanged, pure AST functions. No strategy module is
    # imported or executed, and no portfolio transition can occur here.
    raw = files['sentinel/economic_manifest.py']
    names = {'_syntax', '_package_dependencies', 'local_imports'}
    nodes = [n for n in ast.parse(raw).body if isinstance(n, ast.FunctionDef) and n.name in names]
    if {n.name for n in nodes} != names:
        raise ValueError('REFUSED_CANONICAL_IMPORT_RESOLVER')
    namespace = dict(ast=ast, lru_cache=lru_cache, EconomicManifestRefused=ValueError,
                     _local_path=lambda name: module_path(files, name))
    exec(compile(ast.Module(body=nodes, type_ignores=[]), '<frozen-static-import-resolver>', 'exec'), namespace)
    return namespace['local_imports']


def extend(files):
    """Keep guards/provenance; bind the actual new private dependency closure."""
    manifest_name = 'sentinel/economic-implementation-v2.json'
    reader_name = 'sentinel/economic_manifest.py'
    value = json.loads(files[manifest_name])
    reader = files[reader_name]
    match = re.search(rb"^MANIFEST_SHA256 = '([0-9a-f]{64})'$", reader, re.M)
    if match is None or hashlib.sha256(files[manifest_name]).hexdigest().encode() != match[1]:
        raise ValueError('REFUSED_ORIGINAL_ECONOMIC_MANIFEST')
    local_imports = resolver(files)
    expected = {**value['pure_contracts'], **value['input_compilers']}
    dependencies = {}
    queue = list(expected)
    while queue:
        name = queue.pop()
        edges = local_imports(module_bytes(files, name), module_name=name)
        dependencies[name] = edges
        for edge in edges:
            if edge in expected or edge in value['operational_ports']:
                continue
            if not edge.startswith('stock_strategy_shared.'):
                raise ValueError('REFUSED_UNCLASSIFIED_ECONOMIC_EDGE_'+edge)
            expected[edge] = hashlib.sha256(module_bytes(files, edge)).hexdigest()
            value['input_compilers'][edge] = expected[edge]
            queue.append(edge)
    value['dependencies'] = dependencies
    canonical = json.dumps(expected, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')
    value['implementation_sha256'] = hashlib.sha256(canonical).hexdigest()
    raw = (json.dumps(value, indent=2, sort_keys=True)+'\n').encode()
    out = dict(files)
    out[manifest_name] = raw
    digest = hashlib.sha256(raw).hexdigest().encode()
    out[reader_name] = reader[:match.start(1)]+digest+reader[match.end(1):]
    normalized = re.sub(rb"^MANIFEST_SHA256 = '[0-9a-f]{64}'$", b"MANIFEST_SHA256 = '"+b'0'*64+b"'", out[reader_name], flags=re.M)
    if hashlib.sha256(normalized).hexdigest() != value['module_sha256']:
        raise ValueError('REFUSED_ECONOMIC_MANIFEST_READER_CHANGED')
    return out
