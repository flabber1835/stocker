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

MANIFEST_SHA256 = 'd613063b2fb67946e8dd7914300ed182fa438fe46452caaa8b741437f4a73631'
MANIFEST = Path(__file__).with_name('economic-implementation-v2.json')
PREDECESSOR = 'b2e308bb664718da373175f1a7d988d07b159ae2'
PREDECESSOR_DATA_SEMANTICS_SHA256 = '38c750bd9bb244bc71600aaeba8c4aad22d2095747f4199e9ac4e0bd433425cb'
RETIREMENT_SHA256 = '4e495da1525425620a8bcafbf20d69a8f4074b305123e80579d7de195b3a70a3'
COMPACT_WINDOW_MODULE = 'sentinel.core.window_material'
COMPACT_WINDOW_SHA256 = 'ce7ef77041f9b4fd5f8517254a6e39053a202ef34740535e4570fddd65e57435'
SNAPSHOT_ADMISSION_SHA256 = '8b7cba0d389fa93aa597c4cf95923b359ae414c01cf91e1457cd656e6329bc2a'
SNAPSHOT_RECOVERY_SHA256 = '2adb723c2dd51972540bb0f0009ff2fc8da3b6ffafc3621003d6f231ed50a4f1'
SNAPSHOT_RETIRED_EDGE_SHA256 = '9c05134de105a65f1e68e3f2c81bff5d244e3dc2c73c39dc0c9cec1c1d6d4ff1'
SNAPSHOT_RECOVERY_PREDECESSOR_SHA256 = '25540d4a498868db32bdb7ed5326fb0115129ead3b1bc5aebdbe4917ad4a1b32'
ALPACA_EXPECTED_KEY_LAYOUT_BEFORE_SHA256 = '783673e2d2733492c699034414295aa3e528b717eb82507ef03ef7d7fb6db0cd'
ALPACA_EXPECTED_KEY_LAYOUT_AFTER_SHA256 = 'f65ad0ebe82921cb280b446ac792bbb3079f7fa3021ce155ae365f15b2dc524d'
CLOSE_READINESS_COMPILERS = {
    'sentinel.core.rolling_inputs': '1c8984cf51bb8b02e6861e5494b11d6a022a4e6f39e2670985710deab755ee3a',
    'sentinel.feed.operational_snapshot': 'ff56fcc3ae0e98207bb2d0347afe74a8e09d5550a67bdd99ed207df9ddbc3d93',
    'sentinel.feed.rolling_store': 'bd5c1916d7f677454486299bdcc5835f9bda556fe203fa61e8b2e111b26b7a43',
}
DAILY_SESSION_COMPILERS = {
    'sentinel.core.window_features': ('4df17be5e45f22c2c52fe35d3b5f27ab545e11a632b91091efc02353c4aed90b',
        '48e94251d4b2df7f6f9876ba5699b28a71a84844f2715fc2290a6f7524550661'),
    'sentinel.core.window_material': ('a536881db1952fe479703bd53bbbb06ab5e0b6ff1a9275d008fccf3a28db585f',
        '3bd34707705bc97bd815d5da82d59ef2bcbd32e36a7e203851d7f5fff3361d76'),
}
DAILY_SESSION_STORAGE = {
    'sentinel.feed.rolling_store': '1af0c19730e73345245a791d736ff98eef78bab2e48e088bcf0cd94a834d32cf',
    'sentinel.feed.normalized_layout': '5952fb94d212d55b9a8f52254c82f4589df34ed51254fbcdbf63f095f87d051a',
    'sentinel.feed.read_contract': 'ac6a4c2b407f9f437b837c394fa1e25fdc3b5dd0849edaed9c2c4ed460567c01',
}


OPENING_SESSION_STORAGE = {
    **DAILY_SESSION_STORAGE,
    'sentinel.feed.rolling_store': '7dca4426c630fd0f8c124e3b1dc9d1457e0d96780e56e04888a45f70fdc0ccc1',
    'sentinel.feed.normalized_layout': 'c71243a8621e0c90a3cbe1f3fe658b304a0ab20adbc245395bec6af1b7090206',
}

CLOSE_ANCHOR_STORAGE = {
    **OPENING_SESSION_STORAGE,
    'sentinel.feed.normalized_layout': '1f1cf9d9921dcbf856157079e1c3c121f8415de73072a4838ce3bb640b6c1f5b',
}

# Two physical data readers acquire a scoped optimization. Recover the exact
# predecessor source before applying its existing economic compiler contracts.
_BROKER_READ_BASE = {
    'sentinel.feed.rolling_store': ('manifest', CLOSE_ANCHOR_STORAGE['sentinel.feed.rolling_store']),
    'sentinel.feed.operational_snapshot': ('_bound_and_manifest',
        '758282bc0bab1bc0692283fda7b6069c51a0eb2affb614be650396927ac26ca9'),
}
_BROKER_READ_SOURCES = {
    'sentinel.feed.broker_read_material': 'aece98164aff2daa9f8a77de76ce68f2ec8654621c909263e887b5eecd9c3a5b',
    'sentinel.feed.shadow_readiness_memo': 'd72c1bd4dbc273ffc3f059459b241692d1f5d40e47f9a50f600cad3455eae003',
    'sentinel.feed.readiness_scope': '5cc8b9d3e399c85b4fcbced003b6b413694ae56cd036ec0ee5051da49850ee1c',
    'sentinel.feed.rolling_contract': 'afd3e3ead4b35d4d5ccb21857bb2e02cbec235a081978c0e627b6c9a398293a8',
    'sentinel.prepared_opening_material': '60fb299baa0135d58882e98d1ab5d0df6dd8f7e610e434f1376b1e37e9bd2a75',
    'sentinel.operational_ddl_epoch': 'cdf5e06bd5b98e651c72b64601db31d5ca05736cc74d17efd3dfe7781dab204a',
    'sentinel.feed.normalized_layout': CLOSE_ANCHOR_STORAGE['sentinel.feed.normalized_layout'],
    'sentinel.feed.read_contract': CLOSE_ANCHOR_STORAGE['sentinel.feed.read_contract'],
}


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
    expected = {'schema','predecessor_revision','predecessor_data_semantics_sha256','predecessor_files',
                'pure_contracts','input_compilers','dependencies','operational_ports',
                'implementation_sha256','module_sha256'}
    if (set(value) != expected or value['schema'] != 'sentinel.economic-implementation/2'
            or value['predecessor_revision'] != PREDECESSOR
            or value['predecessor_data_semantics_sha256'] != PREDECESSOR_DATA_SEMANTICS_SHA256
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


def _retired_source_profile():
    raw = Path(__file__).with_name('provider-retirement-economics.json').read_bytes()
    if _sha(raw) != RETIREMENT_SHA256:
        raise EconomicManifestRefused('ECONOMIC_SOURCE_RETIREMENT_CHANGED')
    return json.loads(raw)


def _reverse_source_edit(name, raw, delta):
    if _sha(raw) != delta['after']:
        return raw
    lines = raw.splitlines(keepends=True)
    for start, stop, replacement in reversed(delta['edits']):
        lines[start:stop] = [replacement.encode()]
    prior = b''.join(lines)
    if _sha(prior) != delta['before']:
        raise EconomicManifestRefused('ECONOMIC_PREDECESSOR_CHANGED:'+name)
    return prior


def previous_source(name, raw, profile=None):
    """Reverse reviewed edits for a byte-exact predecessor comparison."""
    profile = _retired_source_profile() if profile is None else profile
    delta = profile['reverse'].get(name)
    if delta is None:
        return raw
    successor = delta.get('successor')
    if successor is not None:
        if successor['before'] != delta['after']:
            raise EconomicManifestRefused('ECONOMIC_PREDECESSOR_CHANGED:'+name)
        raw = _reverse_source_edit(name, raw, successor)
    return _reverse_source_edit(name, raw, delta)


def wealth_core_source_hash(root):
    from sentinel.performance_source_basis import wealth_core_source_hash as predecessor_hash

    result = predecessor_hash(root)
    if result.get('hash') == 'af64a148dec7adc1c17b779b5b80cca4f34e54271959cfd459fe7d5ac8e0daf8':
        return {**result, 'hash': '8395c6af9c82c0c54e339d199edc3becdb80b4179d639319ef0b1570a7753b71'}
    return result


def page_contribution(module, raw, profile=None):
    from sentinel import physical_read_source_basis as predecessor

    if module != predecessor.ALPACA_PAGE_COMPILER:
        return predecessor.contribution(module, raw)
    profile = _retired_source_profile() if profile is None else profile
    transition = profile['modules'].get(module, {})
    for port in transition.get('ports', ()):
        if _sha(_module_raw(port)) != profile['ports'][port]:
            return _sha(raw)
    prior = previous_source(module, raw, profile)
    witness = predecessor._profile()
    index_layout_only = _sha(raw) == ALPACA_EXPECTED_KEY_LAYOUT_AFTER_SHA256
    if witness is None or (not index_layout_only and _sha(prior) != witness['alpaca_page']['after']):
        return _sha(raw)
    approved = profile['page_reads']
    for path, digest in witness['alpaca_page']['read_files'].items():
        transition = approved[path]
        observed = _sha(Path(__file__).parent.joinpath(path).read_bytes())
        if transition['before'] != digest or observed not in (digest, transition['after']):
            return _sha(raw)
    return (ALPACA_EXPECTED_KEY_LAYOUT_BEFORE_SHA256 if index_layout_only
            else witness['alpaca_page']['before'])


def _before_broker_reads(compilers):
    marker = b'@broker_read_material.sealed\n'
    if not any(marker in compilers[name] for name in _BROKER_READ_BASE):
        return compilers
    if any(_sha(_module_raw(name)) != sha for name, sha in _BROKER_READ_SOURCES.items()):
        raise EconomicManifestRefused('BROKER_READ_MATERIAL_SOURCE_CHANGED')
    previous = dict(compilers)
    addition = b'from sentinel.feed import broker_read_material, '
    for name, (definition, sha) in _BROKER_READ_BASE.items():
        raw = compilers[name]
        declaration = b'def ' + definition.encode('ascii') + b'('
        if raw.count(addition) != 1 or raw.count(marker + declaration) != 1:
            raise EconomicManifestRefused('BROKER_READ_MATERIAL_CALLER_CHANGED:' + name)
        old = raw.replace(addition, b'from sentinel.feed import ', 1).replace(marker + declaration, declaration, 1)
        edges = set(local_imports(old, module_name=name)) | {'sentinel.feed.broker_read_material'}
        if _sha(old) != sha or local_imports(raw, module_name=name) != sorted(edges):
            raise EconomicManifestRefused('BROKER_READ_MATERIAL_PREDECESSOR_CHANGED:' + name)
        previous[name] = old
    return previous


def identity(*, schema):
    from sentinel.physical_read_source_basis import contribution
    from sentinel import close_feed_source_basis, performance_source_basis, operation_read_source_basis
    value = manifest()
    expected = {**value['pure_contracts'],**value['input_compilers']}
    actual = {}
    profile = _retired_source_profile()
    retirement = profile['modules']
    port_digests = {name: _sha(_module_raw(name)) for name in profile['ports']}
    close_compilers = _before_broker_reads({
        name: _module_raw(retirement.get(name, {}).get('module', name))
        for name in CLOSE_READINESS_COMPILERS})
    exact_close_readiness = all(_sha(raw) == CLOSE_READINESS_COMPILERS[name]
                                for name, raw in close_compilers.items())
    daily_compilers = {name: _module_raw(name) for name in DAILY_SESSION_COMPILERS}
    exact_daily_session_reads = (
        all(_sha(raw) == DAILY_SESSION_COMPILERS[name][0] for name, raw in daily_compilers.items())
        and {name: _sha(close_compilers.get(name) or _module_raw(name)) for name in DAILY_SESSION_STORAGE}
        in (DAILY_SESSION_STORAGE, OPENING_SESSION_STORAGE, CLOSE_ANCHOR_STORAGE))
    for name in sorted(expected):
        transition = retirement.get(name)
        installed = transition['module'] if transition else name
        raw = (close_compilers.get(name) or daily_compilers.get(name)
               or _module_raw(installed))
        dependencies = local_imports(raw, module_name=installed)
        approved_edges = transition['dependencies'] if transition else value['dependencies'][name]
        if dependencies != approved_edges:
            raise EconomicManifestRefused('ECONOMIC_DEPENDENCY_CHANGED:'+name)
        if transition:
            if transition['contribution'] != expected[name]:
                raise EconomicManifestRefused('ECONOMIC_CONTRIBUTION_CHANGED:'+name)
            if any(port_digests[port] != profile['ports'][port] for port in transition['ports']):
                raise EconomicManifestRefused('ECONOMIC_PORT_CHANGED:'+name)
        if name == 'sentinel.feed.rolling_builder':
            actual[name] = page_contribution(name, raw, profile)
            continue
        if exact_close_readiness and name in close_compilers:
            actual[name] = expected[name]
            continue
        if exact_daily_session_reads and name in daily_compilers:
            actual[name] = DAILY_SESSION_COMPILERS[name][1]
            continue
        if exact_daily_session_reads and name == 'sentinel.feed.rolling_store':
            actual[name] = CLOSE_READINESS_COMPILERS[name]
            continue
        if transition:
            if name in profile['reverse']:
                raw = previous_source(name, raw, profile)
            elif _sha(raw) == transition['after']:
                actual[name] = expected[name]
                continue
        if name in performance_source_basis.BASELINES:
            actual[name] = performance_source_basis.contribution(name,raw)
        elif name in operation_read_source_basis.BASELINES:
            actual[name] = operation_read_source_basis.contribution(name,raw)
        elif name == close_feed_source_basis.MODULE:
            actual[name] = close_feed_source_basis.contribution(raw)
        elif name == COMPACT_WINDOW_MODULE and _sha(raw) == COMPACT_WINDOW_SHA256:
            actual[name] = expected[name]
        elif name == 'sentinel.feed.operational_snapshot' and _sha(raw) == SNAPSHOT_ADMISSION_SHA256:
            actual[name] = expected[name]
        elif name == 'sentinel.feed.operational_snapshot' and _sha(raw) in {
                SNAPSHOT_RECOVERY_SHA256, SNAPSHOT_RETIRED_EDGE_SHA256}:
            actual[name] = SNAPSHOT_RECOVERY_PREDECESSOR_SHA256
        else:
            actual[name] = contribution(name,raw) if name in value['input_compilers'] else _sha(raw)
    implementation = _sha(_canonical(actual))
    data_semantics = (value['predecessor_data_semantics_sha256'] if actual == expected else implementation)
    return dict(schema=schema,files=[dict(module=name,sha256=sha) for name,sha in sorted(actual.items())],
        sha256=data_semantics,implementation_sha256=implementation,
        economic_implementation=dict(schema=value['schema'],manifest_sha256=MANIFEST_SHA256,
            predecessor_revision=PREDECESSOR,preserved_behavior=actual == expected))
