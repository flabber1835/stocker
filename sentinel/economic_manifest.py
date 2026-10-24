"""Economic implementation identity, independent of the full runtime attestation.

The one initial extraction witness retains the predecessor's behavioral book
identity only for its complete exact economic implementation. Subsequent
operational releases retain their actual runtime hashes. Changed economic
bytes acquire their actual new implementation identity; unknown dependency
edges refuse rather than falling outside the manifest silently.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import re
from functools import lru_cache

MANIFEST_SHA256 = '0cc4a7032e4766c2dad2ad8cded314d6901438faf28958225c6db46b4e7bc10c'
MANIFEST = Path(__file__).with_name('economic-implementation-v2.json')
PREDECESSOR = 'b2e308bb664718da373175f1a7d988d07b159ae2'
PREDECESSOR_BEHAVIORAL_SHA256 = 'caab7a1872fe4ec178aec659716a4bc70c0cd5ea79a88e33ffacd2ae0c7cf095'


class EconomicManifestRefused(ValueError):
    pass


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=True,allow_nan=False).encode('ascii')


def _module_raw(name):
    import importlib
    module = importlib.import_module(name)
    return Path(module.__file__).resolve().read_bytes()


@lru_cache(maxsize=128)
def _syntax(module_name, raw):
    """Only immutable parse facts; fresh bytes, paths and verdicts stay outside."""
    tree = ast.parse(raw)
    nodes = tuple(ast.walk(tree))
    bindings = set()
    for node in tree.body:
        if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef,ast.ClassDef)):
            bindings.add(node.name)
        elif isinstance(node,(ast.Import,ast.ImportFrom)):
            bindings.update(alias.asname or (alias.name.split('.')[0] if isinstance(node,ast.Import)
                                             else alias.name) for alias in node.names)
        elif isinstance(node,(ast.Assign,ast.AnnAssign)):
            targets = node.targets if isinstance(node,ast.Assign) else [node.target]
            bindings.update(item.id for target in targets for item in ast.walk(target)
                            if isinstance(item,ast.Name) and isinstance(item.ctx,ast.Store))
    dynamic_names = {'__import__'}
    for node in nodes:
        if isinstance(node,ast.ImportFrom) and node.module in {'importlib','builtins'}:
            dynamic_names.update(alias.asname or alias.name for alias in node.names
                                 if alias.name in {'import_module','__import__'})
    result = []
    for node in nodes:
        if isinstance(node,ast.Call) and (
                isinstance(node.func,ast.Name) and node.func.id in dynamic_names
                or isinstance(node.func,ast.Attribute) and node.func.attr in {'import_module','__import__'}):
            raise EconomicManifestRefused('ECONOMIC_DYNAMIC_IMPORT_UNSUPPORTED:'+str(module_name))
        if isinstance(node,ast.Import):
            result.append(('import',None,0,tuple(alias.name for alias in node.names)))
        elif isinstance(node,ast.ImportFrom):
            result.append(('from',node.module or '',node.level,tuple(alias.name for alias in node.names)))
    return tuple(result),frozenset(bindings)


def _local_path(name):
    """Resolve source packages without executing an initializer for inspection."""
    if name == 'sentinel' or name.startswith('sentinel.'):
        root = Path(__file__).parent
    elif name == 'stock_strategy_shared' or name.startswith('stock_strategy_shared.'):
        from importlib.util import find_spec
        spec = find_spec('stock_strategy_shared')
        if spec is None or spec.origin is None:
            raise EconomicManifestRefused('ECONOMIC_SOURCE_PACKAGE_UNAVAILABLE:stock_strategy_shared')
        root = Path(spec.origin).resolve().parent
    else:
        return None
    return root.joinpath(*name.split('.')[1:])


def _package_dependencies(name):
    """Python executes existing ancestor initializers for every module import."""
    parts = name.split('.')
    result = set()
    for size in range(1,len(parts)):
        package = '.'.join(parts[:size])
        path = _local_path(package)
        if path is not None and (path/'__init__.py').is_file():
            result.add(package)
    return result


def local_imports(raw, *, module_name=None):
    """Resolve every declared local edge against the current module/path tree."""
    result = _package_dependencies(module_name) if module_name else set()
    for kind,base,level,names in _syntax(module_name,raw)[0]:
        if kind == 'import':
            result.update(name for name in names if _local_path(name) is not None)
        else:
            if level:
                if not module_name:
                    raise EconomicManifestRefused('ECONOMIC_RELATIVE_IMPORT_CONTEXT_REQUIRED')
                from importlib.util import resolve_name
                declaring = _local_path(module_name)
                if declaring is None:
                    raise EconomicManifestRefused('ECONOMIC_RELATIVE_IMPORT_CONTEXT_REQUIRED')
                package = (module_name if (declaring/'__init__.py').is_file()
                           and not declaring.with_suffix('.py').is_file()
                           else module_name.rsplit('.',1)[0])
                base = resolve_name('.'*level+base,package)
            base_path = _local_path(base)
            if base_path is not None:
                if base_path.with_suffix('.py').is_file():
                    result.add(base)
                else:
                    initializer = base_path/'__init__.py'
                    bindings = (_syntax(base,initializer.read_bytes())[1]
                                if initializer.is_file() else frozenset())
                    for name in names:
                        candidate = base_path / name
                        if candidate.with_suffix('.py').is_file() or (candidate/'__init__.py').is_file():
                            result.add(base+'.'+name)
                        elif name in bindings:
                            result.add(base)
                        else:
                            result.add(base+'.'+name)
    for name in tuple(result):
        result.update(_package_dependencies(name))
    result.discard(module_name)
    return sorted(result)


def manifest():
    raw = MANIFEST.read_bytes()
    if MANIFEST_SHA256 == '0'*64 or _sha(raw) != MANIFEST_SHA256:
        raise EconomicManifestRefused('ECONOMIC_MANIFEST_NOT_AUTHENTICATED')
    value = json.loads(raw)
    expected = {'schema','predecessor_revision','predecessor_behavioral_sha256','predecessor_files',
                'pure_contracts','input_compilers','dependencies','operational_ports',
                'implementation_sha256','module_sha256'}
    if (set(value) != expected or value['schema'] != 'sentinel.economic-implementation/2'
            or value['predecessor_revision'] != PREDECESSOR
            or value['predecessor_behavioral_sha256'] != PREDECESSOR_BEHAVIORAL_SHA256
            or set(value['pure_contracts']) & set(value['input_compilers'])
            or set(value['dependencies']) != set(value['pure_contracts']) | set(value['input_compilers'])):
        raise EconomicManifestRefused('ECONOMIC_MANIFEST_SHAPE_CHANGED')
    own, count = re.subn(rb"^MANIFEST_SHA256 = '[0-9a-f]{64}'$",
        b"MANIFEST_SHA256 = '"+b'0'*64+b"'",Path(__file__).read_bytes(),flags=re.M)
    if count != 1 or _sha(own) != value['module_sha256']:
        raise EconomicManifestRefused('ECONOMIC_MANIFEST_READER_CHANGED')
    files = {**value['pure_contracts'],**value['input_compilers']}
    ports = value['operational_ports']
    allowed_roles = {'STORAGE','SOURCE_IO','SOURCE_GUARD','RECOVERY','EXECUTION_ONLY','IDENTITY','DIAGNOSTICS'}
    external = {edge for edges in value['dependencies'].values() for edge in edges
                if (edge == 'sentinel' or edge.startswith('sentinel.')) and edge not in files}
    if (not isinstance(ports,dict) or set(ports) != external
            or any(role not in allowed_roles for role in ports.values())):
        raise EconomicManifestRefused('ECONOMIC_DEPENDENCY_UNCLASSIFIED')
    if (not files or any(not re.fullmatch(r'(?:sentinel|stock_strategy_shared)(?:\.[a-zA-Z_][a-zA-Z_0-9]*)*',name)
                         or not re.fullmatch('[0-9a-f]{64}',sha) for name,sha in files.items())
            or _sha(_canonical(files)) != value['implementation_sha256']):
        raise EconomicManifestRefused('ECONOMIC_IMPLEMENTATION_CLOSURE_CHANGED')
    return value


def identity(*, schema):
    value = manifest()
    expected = {**value['pure_contracts'],**value['input_compilers']}
    actual = {}
    for name in sorted(expected):
        raw = _module_raw(name)
        dependencies = local_imports(raw,module_name=name)
        if dependencies != value['dependencies'][name]:
            raise EconomicManifestRefused('ECONOMIC_DEPENDENCY_CHANGED:'+name)
        actual[name] = _sha(raw)
    implementation = _sha(_canonical(actual))
    behavioral = (value['predecessor_behavioral_sha256'] if actual == expected else implementation)
    return dict(schema=schema,files=[dict(module=name,sha256=sha) for name,sha in sorted(actual.items())],
        sha256=behavioral,implementation_sha256=implementation,
        economic_implementation=dict(schema=value['schema'],manifest_sha256=MANIFEST_SHA256,
            predecessor_revision=PREDECESSOR,preserved_behavior=actual == expected))
