"""Current economic boundary, independently witnessed from the exact predecessor."""
from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import json
from pathlib import Path

import pytest

from sentinel import economic_manifest as economic

ROOT = Path(__file__).resolve().parents[2]
WITNESS = ROOT / 'tests/support/architecture-b2-functions.json'
WITNESS_SHA256 = '80b2c608ff35d7fe80c1d9eefd02a768f891ab5c3bccd277a1b2b547c48f6af2'
PREDECESSOR_STRATEGY_SHA256 = 'caab7a1872fe4ec178aec659716a4bc70c0cd5ea79a88e33ffacd2ae0c7cf095'
PREDECESSOR_DATA_SEMANTICS_SHA256 = '38c750bd9bb244bc71600aaeba8c4aad22d2095747f4199e9ac4e0bd433425cb'
IDENTITY_WITNESS = ROOT / 'tests/support/architecture-b2-economic-identity.json'
IDENTITY_WITNESS_SHA256 = '5547702880b5c41578c4fc312bebf38dab768222d3f5b8041481b324c1f15ebe'
INITIALIZERS = frozenset({'sentinel','sentinel.breadth','sentinel.controller','sentinel.core',
    'sentinel.execution','sentinel.feed','sentinel.feed.source_authority','sentinel.regime',
    'stock_strategy_shared','stock_strategy_shared.wealth_core'})
B2_INITIALIZERS_SHA256 = '59626f519a727449e7a1ec6ca3415168b4272b5607fe709b3c2d37457a32f9f9'
MOVES = {
    'sentinel/core/window_features.py': ('sentinel.core.window_material', ('Signal','WindowFeatures','protected','install')),
    'sentinel/core/rolling_reader.py': ('sentinel.core.input_domains', ('_vendor','_defensive')),
    'sentinel/core/production.py': ('sentinel.core.feature_warmup', ('warm_session_state','_warm_median5')),
    'sentinel/shadow_runtime.py': ('sentinel.core.formation_identity', (
        'ShadowRuntimeRefused','_starting_cash','_canonical_json','_canonical_sha256','_decimal_text',
        '_stream_sha256','_warmup_input_identity')),
    'sentinel/shadow_observation.py': ('sentinel.core.price_identity', (
        'ShadowObservationRefused','_positive_decimal','_decimal_text','_finite_decimal',
        '_optional_decimal_text','_exact_price_ratio','_signal_price_identity')),
    'sentinel/strategy.py': ('sentinel.core.strategy_profiles', ('controller_for_identity',)),
    'sentinel/feed/rolling_builder.py': ('sentinel.feed.canonical_transforms', ('benchmarks',)),
}


def witness():
    raw = WITNESS.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == WITNESS_SHA256
    value = json.loads(raw)
    assert value['revision'] == economic.PREDECESSOR
    return value


def predecessor_identity():
    """Plain exact-b2 Git reconstruction, independently matched to its image.

    These old contributions are historical input records; actual candidate
    closure tests below continue to read all current files without substitution.
    """
    raw = IDENTITY_WITNESS.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == IDENTITY_WITNESS_SHA256
    value = json.loads(raw)
    assert value['schema'] == 'sentinel.predecessor-economic-identity/1'
    assert value['revision'] == economic.PREDECESSOR
    assert value['runtime_image'] == 'sha256:213e53efe9849a53a5b61966af6f252aa31ea697416d40712603098a0c8e7002'
    semantics = value['data_semantics']
    canonical = lambda material: json.dumps(material, sort_keys=True,
        separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')
    assert len(semantics['files']) == 116
    assert hashlib.sha256(canonical({key:semantics[key] for key in ('schema','files')})).hexdigest() == (
        semantics['sha256']) == PREDECESSOR_DATA_SEMANTICS_SHA256
    contributions = {record['module']:record['sha256'] for record in semantics['files']}
    definitions = witness()['files']
    for path in MOVES:
        name = path.removesuffix('.py').replace('/', '.')
        assert contributions[name] == definitions[path]['source_sha256']
    assert value['strategy']['data_semantics_source_sha256'] == semantics['sha256']
    assert hashlib.sha256(canonical(value['strategy'])).hexdigest() == (
        value['strategy_sha256']) == PREDECESSOR_STRATEGY_SHA256
    return value


def tree(source):
    return ast.dump(ast.parse(source), include_attributes=False)


def moved_equal(old, current):
    assert tree(old) == tree(current)


@pytest.mark.parametrize('path', MOVES)
def test_extracted_definitions_match_independent_predecessor(path):
    record = witness()['files'][path]
    name = path.removesuffix('.py').replace('/', '.')
    assert economic.manifest()['predecessor_files'][name] == record['source_sha256']
    module_name, definitions = MOVES[path]
    module = importlib.import_module(module_name)
    for definition in definitions:
        moved_equal(record['definitions'][definition], inspect.getsource(getattr(module,definition)))


def test_existing_exception_and_helper_imports_are_exact_aliases():
    from sentinel import shadow_runtime, shadow_observation
    from sentinel.core import formation_identity, price_identity, window_features, window_material, production, feature_warmup
    assert shadow_runtime.ShadowRuntimeRefused is formation_identity.ShadowRuntimeRefused
    assert shadow_observation.ShadowObservationRefused is price_identity.ShadowObservationRefused
    assert window_features.install is window_material.install
    assert production.warm_session_state is feature_warmup.warm_session_state


def test_extraction_witness_detects_changed_price_mapping():
    old = witness()['files']['sentinel/core/rolling_reader.py']['definitions']['_vendor']
    assert 'row.close_unadjusted' in old
    with pytest.raises(AssertionError):
        moved_equal(old, old.replace('row.close_unadjusted','row.close_signal'))


def test_provider_canonical_mappings_preserve_original_price_domains():
    from sentinel.feed import canonical_transforms
    record = witness()['files']['sentinel/feed/rolling_builder.py']['definitions']
    def call_in(source):
        calls = [node for node in ast.walk(ast.parse(source)) if isinstance(node,ast.Call)
                 and isinstance(node.func,ast.Name) and node.func.id == 'CanonicalBar']
        assert len(calls) == 1
        return calls[0]
    prior = call_in(record['_build'])
    current = call_in(inspect.getsource(canonical_transforms.sharadar_bar))
    assert ast.dump(prior,include_attributes=False) == ast.dump(current,include_attributes=False)
    prior = call_in(record['build_alpaca'])
    current = call_in(inspect.getsource(canonical_transforms.alpaca_bar))
    old_fields = {item.arg:ast.unparse(item.value) for item in prior.keywords}
    new_fields = {item.arg:ast.unparse(item.value) for item in current.keywords}
    for field in ('session','ticker','close_signal','close_unadjusted','open_unadjusted','volume'):
        assert old_fields[field] == new_fields[field]
    assert old_fields['security_id'] == "selected[row['ticker']]['asset_id']"
    assert new_fields['security_id'] == 'asset_id'
    assert old_fields['split_ratio'] == "float(splits.get((row['ticker'], row['date']), '1'))"
    assert new_fields['split_ratio'] == 'float(split_ratio)'
    assert old_fields['dividend_per_share'] == "float(dividends.get((row['ticker'], row['date']), '0'))"
    assert new_fields['dividend_per_share'] == 'float(dividend_per_share)'


class _CompilerNames(ast.NodeTransformer):
    """Only extraction parameter plumbing; no expression/guard is discarded."""
    def visit_Attribute(self, node):
        spelling = ast.unparse(node)
        replacement = {'refs.manifest':'manifest', 'refs.resolver.resolve':'resolve_identity',
                       'publication.version':'publication_version'}.get(spelling)
        if replacement:
            return ast.copy_location(ast.Name(id=replacement,ctx=ast.Load()),node)
        return self.generic_visit(node)

    def visit_Name(self, node):
        return ast.copy_location(ast.Name(id='metadata' if node.id == 'meta' else node.id,ctx=node.ctx),node)


def compiler_body(source, *, prior):
    function = ast.parse(source).body[0]
    body = function.body
    if prior:
        result = []
        for node in body:
            if isinstance(node,(ast.Import,ast.ImportFrom)):
                continue
            if isinstance(node,ast.Expr) and isinstance(node.value,ast.Constant) and isinstance(node.value.value,str):
                continue
            # These are storage/parameter plumbing, preserved by the actual SQL adapter test.
            if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id in {
                    'session','meta','columns','query'} for t in node.targets):
                continue
            if isinstance(node,ast.Assign) and ast.unparse(node.value) == 'refs.current_metadata(session=session)':
                continue
            if isinstance(node,ast.With):
                assert len(node.body) == 2 and isinstance(node.body[0],ast.Assign)
                assert ast.unparse(node.body[0].targets[0]) == 'rows'
                result.extend(node.body[1:])
            else:
                result.append(node)
        body = result
    else:
        body = [n for n in body if not isinstance(n,(ast.Import,ast.ImportFrom))
                and not (isinstance(n,ast.Expr) and isinstance(n.value,ast.Constant)
                         and isinstance(n.value.value,str))]
    module = ast.Module(body=body,type_ignores=[])
    return ast.dump(_CompilerNames().visit(module),include_attributes=False)


def test_window_compiler_preserves_complete_old_interpretation():
    from sentinel.core import window_material
    old = witness()['files']['sentinel/core/window_features.py']['definitions']['load']
    current = inspect.getsource(window_material.compile_rows)
    assert compiler_body(old,prior=True) == compiler_body(current,prior=False)
    with pytest.raises(AssertionError):
        assert compiler_body(old,prior=True) == compiler_body(
            current.replace('series.append(_vendor(row), indices[day], published_signal=True)',
                            'series.append(_vendor(row), indices[day], published_signal=False)'),prior=False)


def test_cached_formation_formulas_preserve_exact_predecessor_body():
    from sentinel.core import formation_features
    class RouteOnly(ast.NodeTransformer):
        def visit_Call(self,node):
            node = self.generic_visit(node)
            if isinstance(node.func,ast.Name) and node.func.id == 'candidate_query':
                assert len(node.args) == 2 and ast.unparse(node.args[0]) == 'self.conn'
                return node.args[1]
            return node
    records = witness()['files']['sentinel/core/formation_features.py']['definitions']
    for name in ('_value','_Ring','FormationFeatures'):
        expected = ast.dump(ast.parse(records[name]),include_attributes=False)
        current = ast.parse(inspect.getsource(getattr(formation_features,name)))
        assert ast.dump(RouteOnly().visit(current),include_attributes=False) == expected
    broken = inspect.getsource(formation_features.FormationFeatures).replace('index=299','index=298')
    with pytest.raises(AssertionError):
        assert ast.dump(RouteOnly().visit(ast.parse(broken)),include_attributes=False) == ast.dump(
            ast.parse(records['FormationFeatures']),include_attributes=False)


def test_sql_adapter_uses_the_shared_compiler_and_preserves_order():
    from sentinel.core import window_features
    source = inspect.getsource(window_features.load)
    assert 'ORDER BY security_id COLLATE "C",session' in source
    assert 'return compile_rows(' in source
    assert 'CanonicalBar.model_validate(dict(zip(columns, row)))' in source
    assert 'series.append' not in source


def test_current_exact_economic_implementation_keeps_original_book_identity():
    result = economic.identity(schema='qualification-economic-boundary')
    profile = economic.manifest()
    assert result['sha256'] == predecessor_identity()['data_semantics']['sha256']
    assert result['implementation_sha256'] == profile['implementation_sha256']
    assert result['economic_implementation']['preserved_behavior'] is True
    assert set(profile['pure_contracts']) != set(profile['input_compilers'])
    for name in ('sentinel.feed.retention','sentinel.feed.publisher_pipeline',
                 'sentinel.feed.normalized_layout','sentinel.feed.generation_admission',
                 'sentinel.shadow_runtime','sentinel.shadow_observation','sentinel.rolling_daily'):
        assert name not in profile['pure_contracts'] and name not in profile['input_compilers']


def test_complete_current_production_strategy_matches_exact_predecessor():
    from sentinel.strategy import production_strategy
    predecessor = predecessor_identity()
    _, current = production_strategy()
    assert current == predecessor['strategy']
    canonical = json.dumps(current, sort_keys=True, separators=(',', ':'),
                           ensure_ascii=True, allow_nan=False).encode('ascii')
    assert hashlib.sha256(canonical).hexdigest() == PREDECESSOR_STRATEGY_SHA256
    assert current['data_semantics_source_sha256'] == PREDECESSOR_DATA_SEMANTICS_SHA256


def test_complete_strategy_hash_in_nested_source_domain_is_detected(monkeypatch):
    original = economic.identity
    def wrong_domain(*, schema):
        return {**original(schema=schema), 'sha256': PREDECESSOR_STRATEGY_SHA256}
    monkeypatch.setattr(economic, 'identity', wrong_domain)
    with pytest.raises(AssertionError):
        test_complete_current_production_strategy_matches_exact_predecessor()


def test_unknown_economic_edit_gets_actual_identity(monkeypatch):
    read = economic._module_raw
    target = 'sentinel.core.input_domains'
    monkeypatch.setattr(economic,'_module_raw',lambda name: read(name)+b'\n# unknown economic neighboring edit\n'
                        if name == target else read(name))
    result = economic.identity(schema='qualification-economic-boundary')
    assert result['sha256'] == result['implementation_sha256'] != PREDECESSOR_DATA_SEMANTICS_SHA256
    assert result['economic_implementation']['preserved_behavior'] is False


def test_unknown_dependency_is_refused_even_if_economic_bytes_are_supplied(monkeypatch):
    read = economic._module_raw
    monkeypatch.setattr(economic,'_module_raw',lambda name: read(name)+b'\nimport sentinel.feed.store\n'
                        if name == 'sentinel.core.input_domains' else read(name))
    with pytest.raises(economic.EconomicManifestRefused,match='ECONOMIC_DEPENDENCY_CHANGED'):
        economic.identity(schema='qualification-economic-boundary')


@pytest.mark.parametrize('target,old,new',[
    ('sentinel.core.formation_features',b'index=299',b'index=298'),
    ('sentinel.feed.symbol_lineage',b'bisect.bisect_right(arrivals, edge.date)',b'bisect.bisect_left(arrivals, edge.date)'),
    ('sentinel.feed.alpaca_identity',b'value.security_id != sid',b'value.security_id == sid'),
    ('sentinel.feed.tickers_authority',b'_MASK_256 = (1 << 256) - 1',b'_MASK_256 = (1 << 128) - 1'),
    ('sentinel.feed.read_contract',b'p.close_signal,p.close_unadjusted',b'p.close_unadjusted,p.close_signal'),
    ('sentinel.feed.publication_visibility',b'AND NOT {retired_predicate(alias)}',b'OR NOT {retired_predicate(alias)}'),
    ('sentinel.feed._publication_impl',b'ORDER BY rp.version DESC LIMIT 1',b'ORDER BY rp.version ASC LIMIT 1'),
    ('sentinel.feed',b'_publication_visibility.install()',b'pass'),
])
def test_concrete_economic_dependencies_cannot_change_without_new_identity(monkeypatch,target,old,new):
    read = economic._module_raw
    raw = read(target)
    assert raw.count(old) == 1
    monkeypatch.setattr(economic,'_module_raw',lambda name:raw.replace(old,new) if name==target else read(name))
    result = economic.identity(schema='qualification-economic-boundary')
    assert result['sha256'] == result['implementation_sha256'] != PREDECESSOR_DATA_SEMANTICS_SHA256
    assert result['economic_implementation']['preserved_behavior'] is False


@pytest.mark.parametrize('addition',[
    b'\nfrom . import unknown_economic_source\n',
    b'\nfrom .unknown_economic_source import transform\n',
    b'\n__import__("sentinel.core.window_material")\n',
    b'\nimportlib.import_module("sentinel.core.window_material")\n',
    b'\nfrom importlib import import_module as dynamic\ndynamic("sentinel.core.window_material")\n',
])
def test_unknown_relative_and_dynamic_dependency_edges_refuse(monkeypatch,addition):
    read = economic._module_raw
    monkeypatch.setattr(economic,'_module_raw',lambda name:read(name)+addition
                        if name=='sentinel.core.input_domains' else read(name))
    with pytest.raises(economic.EconomicManifestRefused,match='ECONOMIC_(DEPENDENCY_CHANGED|DYNAMIC_IMPORT_UNSUPPORTED)'):
        economic.identity(schema='qualification-economic-boundary')


def test_relative_package_imports_are_resolved_with_the_actual_declaring_context():
    assert economic.local_imports(b'from . import calendar\n',module_name='sentinel.feed.example') == [
        'sentinel','sentinel.feed','sentinel.feed.calendar']
    assert economic.local_imports(b'from .dates import SourceAuthorityRefused\n',
        module_name='sentinel.feed.source_authority') == [
            'sentinel','sentinel.feed','sentinel.feed.source_authority.dates']


def test_implicit_initializers_bind_independent_unchanged_b2_source_bytes():
    profile = economic.manifest()
    baseline = {name:profile['predecessor_files'][name] for name in sorted(INITIALIZERS)}
    encoded = json.dumps(baseline,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode('ascii')
    assert hashlib.sha256(encoded).hexdigest() == B2_INITIALIZERS_SHA256
    for name in INITIALIZERS:
        assert profile['input_compilers'][name] == baseline[name]
        assert hashlib.sha256(economic._module_raw(name)).hexdigest() == baseline[name]


def test_every_contributor_binds_its_actual_implicit_initializers():
    profile = economic.manifest()
    closure = set(profile['pure_contracts']) | set(profile['input_compilers'])
    observed = set()
    for name in closure:
        pieces = name.split('.')
        for size in range(1,len(pieces)):
            parent = '.'.join(pieces[:size])
            module = importlib.import_module(parent)
            assert Path(module.__file__).name == '__init__.py'
            assert parent in closure and parent in profile['dependencies'][name]
            observed.add(parent)
    assert observed == INITIALIZERS
    assert 'sentinel.feed.publication_visibility' in profile['dependencies']['sentinel.feed']
    assert profile['operational_ports']['sentinel.execution.recovered_order_policy'] == 'EXECUTION_ONLY'


def test_shared_root_from_import_resolves_its_actual_child_and_initializers():
    assert economic.local_imports(b'from stock_strategy_shared import split_reconciliation\n',
        module_name='sentinel.core.example') == [
            'sentinel','sentinel.core','stock_strategy_shared','stock_strategy_shared.split_reconciliation']


def test_known_package_attribute_and_unknown_child_do_not_share_an_edge():
    assert economic.local_imports(b'from sentinel.breadth import Holding\n',
        module_name='sentinel.core.example') == ['sentinel','sentinel.breadth','sentinel.core']
    assert economic.local_imports(b'from sentinel.core import unknown_economic_source\n',
        module_name='sentinel.core.example') == [
            'sentinel','sentinel.core','sentinel.core.unknown_economic_source']


def test_all_local_edges_have_explicit_economic_or_reviewed_port_ownership():
    profile = economic.manifest()
    closure = set(profile['pure_contracts']) | set(profile['input_compilers'])
    ports = profile['operational_ports']
    assert not closure & set(ports)
    for name,edges in profile['dependencies'].items():
        assert edges == economic.local_imports(economic._module_raw(name),module_name=name)
        assert {edge for edge in edges if edge.startswith('sentinel.')} <= closure | set(ports)


def test_missing_port_classification_refuses_even_with_supplied_manifest_digest(tmp_path,monkeypatch):
    value = json.loads(economic.MANIFEST.read_bytes())
    del value['operational_ports']['sentinel.feed.normalized_layout']
    raw = json.dumps(value,sort_keys=True).encode()
    changed = tmp_path/'unclassified.json'
    changed.write_bytes(raw)
    monkeypatch.setattr(economic,'MANIFEST',changed)
    monkeypatch.setattr(economic,'MANIFEST_SHA256',hashlib.sha256(raw).hexdigest())
    with pytest.raises(economic.EconomicManifestRefused,match='DEPENDENCY_UNCLASSIFIED'):
        economic.manifest()


def test_bounded_parse_reuse_keeps_current_path_resolution_outside_cache(monkeypatch,tmp_path):
    economic._syntax.cache_clear()
    raw = b'from . import new_contract\n'
    fake = tmp_path/'sentinel'
    (fake/'core').mkdir(parents=True)
    monkeypatch.setattr(economic,'__file__',str(fake/'economic_manifest.py'))
    assert economic.local_imports(raw,module_name='sentinel.core.example') == ['sentinel.core.new_contract']
    (fake/'core/new_contract.py').write_text('VALUE = 1\n')
    assert economic.local_imports(raw,module_name='sentinel.core.example') == ['sentinel.core.new_contract']
    assert economic._syntax.cache_info().hits == 1
    (fake/'core/__init__.py').write_text('"""New executable package initializer."""\n')
    assert economic.local_imports(raw,module_name='sentinel.core.example') == [
        'sentinel.core','sentinel.core.new_contract']
    assert economic._syntax.cache_info().hits == 2
    assert economic._syntax.cache_info().maxsize == 128


def test_operational_sources_are_not_read_as_economic_contributors(monkeypatch):
    read = economic._module_raw
    def audited(name):
        assert name not in {'sentinel.feed.retention','sentinel.feed.publisher_pipeline','sentinel.rolling_runtime'}
        return read(name)
    monkeypatch.setattr(economic,'_module_raw',audited)
    assert economic.identity(schema='qualification-economic-boundary')['sha256'] == PREDECESSOR_DATA_SEMANTICS_SHA256


def assert_pure_dependencies(raw, *, module_name=None):
    blocked = {'os','subprocess','socket','requests','psycopg','httpx'}
    for node in ast.walk(ast.parse(raw)):
        names = ([a.name for a in node.names] if isinstance(node,ast.Import)
                 else [node.module] if isinstance(node,ast.ImportFrom) else [])
        assert all(name and name.split('.')[0] not in blocked for name in names)
    local = economic.local_imports(raw,module_name=module_name)
    assert not any(name.startswith(('sentinel.execution.','sentinel.panel.'))
                   or name in {'sentinel.feed.store','sentinel.feed.publication','sentinel.shadow_runtime',
                               'sentinel.shadow_observation','sentinel.core.production'} for name in local)


def test_pure_economic_contracts_cannot_import_operational_owners():
    profile = economic.manifest()
    closure = set(profile['pure_contracts']) | set(profile['input_compilers'])
    for name in profile['pure_contracts']:
        assert_pure_dependencies(economic._module_raw(name),module_name=name)
        assert {dep for dep in profile['dependencies'][name] if dep.startswith('sentinel.')} <= closure
    with pytest.raises(AssertionError):
        assert_pure_dependencies(b'import sentinel.feed.store\n')


def test_unknown_manifest_bytes_and_changed_reader_are_refused(tmp_path, monkeypatch):
    original = economic.MANIFEST.read_bytes()
    changed = tmp_path/'changed.json'
    changed.write_bytes(original+b' ')
    monkeypatch.setattr(economic,'MANIFEST',changed)
    with pytest.raises(economic.EconomicManifestRefused,match='NOT_AUTHENTICATED'):
        economic.manifest()
    changed.write_bytes(original)
    original_path = economic.__file__
    reader = tmp_path/'economic_manifest.py'
    reader.write_bytes(Path(original_path).read_bytes()+b'\n# unexpected neighboring reader edit\n')
    monkeypatch.setattr(economic,'__file__',str(reader))
    with pytest.raises(economic.EconomicManifestRefused,match='READER_CHANGED'):
        economic.manifest()
