"""Reviewed SQL traversal changes never hide changed economic compiler bytes."""
import hashlib
import ast
import importlib
import inspect
import json
from pathlib import Path

import pytest

from tests.support.alpaca_coverage_source import CURRENT_STRATEGY

from sentinel import close_feed_source_basis as close_basis, physical_read_source_basis as basis
from sentinel import economic_manifest
from sentinel.feed.rolling_contract import digest
from sentinel.strategy import production_strategy


def predecessor_sources():
    path=Path(__file__).resolve().parents[1]/'support/physical-read-c84-sources.json'
    raw=path.read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='79b04231e7b4b9f4a5afd6efb1a4c8e31e550f0bd8379b90408a149574830349'
    record=json.loads(raw)
    assert record['revision']==basis.BASE_REVISION
    assert set(record['modules'])==set(basis.BASELINES)
    for name,text in record['modules'].items():
        assert hashlib.sha256(text.encode()).hexdigest()==basis.BASELINES[name]
    return record['modules']


def physical_predecessor(module, raw):
    if (module == 'sentinel.feed.rolling_store'
            and hashlib.sha256(raw).hexdigest() == economic_manifest.DAILY_SESSION_STORAGE[module]):
        changes = (
            (b'from sentinel.feed.normalized_layout import read_table, stream_sessions',
             b'from sentinel.feed.normalized_layout import read_table, stored_sessions'),
            (b'            def read_day(day):\n'
             b'                return _stream_rows(conn, candidate_id, table=table, columns=columns,\n'
             b'                                    order=order, start=day, end=day)\n\n'
             b'            yield from stream_sessions(conn, candidate_id, kind, read_day, start=start, end=end)\n',
             b'            for day in stored_sessions(conn, candidate_id, kind, start=start, end=end):\n'
             b'                rolling_work.checkpoint()\n'
             b'                yield from _stream_rows(conn, candidate_id, table=table, columns=columns,\n'
             b'                                        order=order, start=day, end=day)\n'
             b'            rolling_work.checkpoint()\n'),
        )
        for current, previous in changes:
            assert raw.count(current) == 1
            raw = raw.replace(current, previous, 1)
        assert hashlib.sha256(raw).hexdigest() == economic_manifest.CLOSE_READINESS_COMPILERS[module]
    if (module == 'sentinel.feed.rolling_store'
            and hashlib.sha256(raw).hexdigest() == economic_manifest.CLOSE_READINESS_COMPILERS[module]):
        changes = (
            (b'def staged_readiness_facts(conn, candidate_id: str) -> SnapshotReadiness | None:\n'
             b'    """Collect facts during the owning READY validator\'s complete content check."""\n'
             b'    return _verify_content_uncached(conn, candidate_id, collect_readiness=True).readiness\n\n\n', b''),
            (b'def _verify_content_uncached(conn, candidate_id: str, *, collect_readiness=False)',
             b'def _verify_content_uncached(conn, candidate_id: str)'),
            (b'    if collect_readiness and readiness is None:\n'
             b'        readiness = _ReadinessAccumulator(value)\n', b''),
        )
        for current, previous in changes:
            assert raw.count(current) == 1
            raw = raw.replace(current, previous)
        assert hashlib.sha256(raw).hexdigest() == '068299577befcc49ed3ce8a8a203b46c8c26ec76bb9657779f2e25dd17324fc6'
    return economic_manifest.previous_source(module, raw)


def unchanged_compiler_body(module, raw):
    raw = physical_predecessor(module, raw)
    if module == close_basis.MODULE:
        replacements = (
            (b'import predecessor_prices, query_router', b'import query_router'),
            (b'    coordinates = {}\n', b''),
            (b'        coordinates[day] = [row[0] for row in rows]\n',
             b'        for sid, *_ in rows:\n'
             b'            prior = conn.execute(query("SELECT session,close_signal,close_unadjusted FROM sentinel_snapshot_bars "\n'
             b'                "WHERE candidate_id=%s AND security_id=%s AND session<%s ORDER BY session DESC LIMIT 1"),\n'
             b'                (refs.candidate_id, sid, day)).fetchone()\n'
             b'            if prior:\n'
             b'                item["predecessors"].append([sid, str(prior[0]), *prior[1:]])\n'),
            (b'    for day, prices in predecessor_prices(conn, refs.candidate_id, coordinates, query=query).items():\n'
             b'        material[day]["predecessors"] = prices\n', b''),
        )
        for before, after in replacements:
            assert raw.count(before) == 1
            raw = raw.replace(before, after)
        assert hashlib.sha256(raw).hexdigest() == close_basis.PREDECESSOR_SHA256
    old=ast.parse(predecessor_sources()[module]);new=ast.parse(raw)
    if module=='sentinel.feed.rolling_store':
        dump=lambda nodes:ast.dump(ast.Module(body=nodes,type_ignores=[]),include_attributes=False)
        # Inline only the two exact typed-loop extractions. Both standalone
        # reader guards, every SQL/domain expression and the loop bodies must
        # still be the independent predecessor's actual expressions.
        for reader_name,helper_name,signature,call in (
                ('read_bars','_bar_rows','conn, candidate_id, *, start=None, end=None',
                 '_bar_rows(conn, candidate_id, start=start, end=end)'),
                ('read_benchmarks','_benchmark_rows','conn, candidate_id',
                 '_benchmark_rows(conn, candidate_id)')):
            before=next(n for n in old.body if isinstance(n,ast.FunctionDef) and n.name==reader_name)
            reader=next(n for n in new.body if isinstance(n,ast.FunctionDef) and n.name==reader_name)
            helper=next(n for n in new.body if isinstance(n,ast.FunctionDef) and n.name==helper_name)
            expected_args=ast.parse(f'def extracted({signature}): pass').body[0].args
            assert ast.dump(helper.args)==ast.dump(expected_args)
            assert len(helper.body)==2 and isinstance(helper.body[0],ast.Expr)
            assert isinstance(helper.body[0].value,ast.Constant) and isinstance(helper.body[0].value.value,str)
            assert dump(helper.body[1:])==dump(before.body[-1:])
            assert ast.dump(reader.args)==ast.dump(before.args)
            assert dump(reader.body)==dump(before.body[:-1]+ast.parse('yield from '+call).body)
            reader.body=before.body
            new.body.remove(helper)
        scan=next(n for n in new.body if isinstance(n,ast.FunctionDef) and n.name=='_verify_content_uncached')
        guard=ast.parse('require_payload(conn, candidate_id)').body[0]
        guards=[index for index,node in enumerate(scan.body) if ast.dump(node)==ast.dump(guard)]
        manifest_index=next(index for index,node in enumerate(scan.body)
            if isinstance(node,ast.Assign) and any(isinstance(target,ast.Name) and target.id=='value'
                                                 for target in node.targets))
        assert guards==[manifest_index+1]
        del scan.body[guards[0]]
        loops=[node for node in scan.body if isinstance(node,ast.For)]
        assert len(loops)==2
        for loop,helper_name,reader_name in zip(loops,('_bar_rows','_benchmark_rows'),
                                              ('read_bars','read_benchmarks')):
            assert ast.dump(loop.iter)==ast.dump(ast.parse(f'{helper_name}(conn, candidate_id)').body[0].value)
            loop.iter.func.id=reader_name
        original=next(n for n in old.body if isinstance(n,ast.FunctionDef) and n.name=='_rows')
        stream=next(n for n in new.body if isinstance(n,ast.FunctionDef) and n.name=='_stream_rows')
        # The SQL, parameters, C collation, row projection and checkpoints in
        # the physical leaf are the exact old ordered stream, without its route.
        offset=next(i for i,n in enumerate(original.body) if isinstance(n,ast.With))
        current_offset=next(i for i,n in enumerate(stream.body) if isinstance(n,ast.With))
        assert dump(original.body[offset:])==dump(stream.body[current_offset:])
        for tree in (old,new):
            tree.body=[n for n in tree.body if not isinstance(n,ast.FunctionDef)
                or n.name not in {'_rows','_stream_rows'}]
    else:
        class RoutingOnly(ast.NodeTransformer):
            removed=0
            def visit_ImportFrom(self,node):
                if node.module=='sentinel.feed.normalized_layout':
                    assert [(a.name,a.asname) for a in node.names]==[('query_router',None)]
                    node.names=[ast.alias(name='candidate_query')]
                return node
            def visit_Assign(self,node):
                if ast.dump(node,include_attributes=False)==ast.dump(ast.parse('query = query_router(conn)').body[0],include_attributes=False):
                    self.removed+=1
                    return None
                return self.generic_visit(node)
            def visit_Call(self,node):
                node=self.generic_visit(node)
                if isinstance(node.func,ast.Name) and node.func.id=='query':
                    assert len(node.args)==1 and not node.keywords
                    node.func=ast.Name(id='candidate_query',ctx=ast.Load())
                    node.args.insert(0,ast.Name(id='conn',ctx=ast.Load()))
                return node
        transform=RoutingOnly();new=transform.visit(new)
        assert transform.removed==1
    assert ast.dump(old,include_attributes=False)==ast.dump(new,include_attributes=False)


@pytest.mark.parametrize('module', sorted(basis.BASELINES))
def test_every_nonphysical_compiler_expression_matches_independent_c84_source(module):
    unchanged_compiler_body(module,Path(importlib.import_module(module).__file__).read_bytes())


@pytest.mark.parametrize('module,old,new',[
    ('sentinel.feed.rolling_store',b'hasher.update(encoded)',b'hasher.update(b"wrong")'),
    ('sentinel.feed.rolling_store',b'yield CanonicalBar.model_validate(row)',b'yield row'),
    ('sentinel.feed.rolling_store',b'value = manifest(conn, candidate_id)\n    require_payload(conn, candidate_id)',
     b'value = manifest(conn, candidate_id)'),
    ('sentinel.feed.rolling_store',b'require_payload(conn, candidate_id)\n    manifest(conn, candidate_id)',
     b'pass\n    manifest(conn, candidate_id)'),
    ('sentinel.feed.rolling_store',b'order=order, start=day, end=day)',
     b'order=order, start=day, end=end)'),
    ('sentinel.feed.action_history',b'session=%s AND ticker=ANY(%s)',b'session<=%s AND ticker=ANY(%s)')])
def test_compiler_arithmetic_and_sql_edits_fail_mechanical_proof(module,old,new):
    raw=Path(importlib.import_module(module).__file__).read_bytes()
    assert old in raw
    with pytest.raises(AssertionError):unchanged_compiler_body(module,raw.replace(old,new,1))


@pytest.mark.parametrize('module', sorted(basis.BASELINES))
def test_exact_current_compiler_preserves_original_contribution_and_unknown_bytes_do_not(module):
    raw=Path(importlib.import_module(module).__file__).read_bytes()
    mapper = close_basis.contribution if module == close_basis.MODULE else lambda value: basis.contribution(module, value)
    assert mapper(physical_predecessor(module, raw))==basis.BASELINES[module]
    changed=raw+b'\n# unknown compiler bytes\n'
    assert mapper(changed)==hashlib.sha256(changed).hexdigest()


@pytest.mark.parametrize('name', ['normalized_layout.py', 'read_contract.py'])
def test_unknown_batch_storage_or_sql_cannot_inherit_original_compiler_identity(name, monkeypatch):
    raw = Path(importlib.import_module(close_basis.MODULE).__file__).read_bytes()
    raw = economic_manifest.previous_source(close_basis.MODULE, raw)
    read = Path.read_bytes
    path = close_basis.FEED / name
    monkeypatch.setattr(Path, 'read_bytes',
                        lambda self: read(self) + b'\n# unknown storage edit\n' if self == path else read(self))
    assert close_basis.contribution(raw) == hashlib.sha256(raw).hexdigest()


@pytest.mark.parametrize('name', ['acquisition_part_schema.py', 'acquisition_parts.py', 'store.py'])
def test_alpaca_page_mapping_requires_exact_compiler_and_read_dependencies(name, monkeypatch):
    path = Path(importlib.import_module(basis.ALPACA_PAGE_COMPILER).__file__)
    raw = path.read_bytes()
    assert hashlib.sha256(raw).hexdigest() == 'f65ad0ebe82921cb280b446ac792bbb3079f7fa3021ce155ae365f15b2dc524d'
    new_ddl = (b'ALPACA_EXPECTED_KEYS_DDL = (\n'
               b"    'CREATE TEMP TABLE alpaca_expected_keys(session date,'\n"
               b"    'security_id text COLLATE \"C\",PRIMARY KEY(session,security_id)) ON COMMIT DROP'\n"
               b')\n')
    new_call = b'        cur.execute(ALPACA_EXPECTED_KEYS_DDL)\n'
    old_call = (b'        cur.execute("CREATE TEMP TABLE alpaca_expected_keys("\n'
                b'                    "session date,security_id text,PRIMARY KEY(session,security_id)) ON COMMIT DROP")\n')
    assert raw.count(new_ddl) == raw.count(new_call) == 1
    previous = raw.replace(new_ddl, b'', 1).replace(new_call, old_call, 1)
    assert hashlib.sha256(previous).hexdigest() == '783673e2d2733492c699034414295aa3e528b717eb82507ef03ef7d7fb6db0cd'
    assert economic_manifest.page_contribution(basis.ALPACA_PAGE_COMPILER, raw) == hashlib.sha256(previous).hexdigest()
    unknown = raw.replace(b'security_id text COLLATE "C"', b'security_id text COLLATE "POSIX"', 1)
    assert unknown != raw
    assert economic_manifest.page_contribution(basis.ALPACA_PAGE_COMPILER, unknown) == hashlib.sha256(unknown).hexdigest()

    current_policy = (b'ALPACA_NORMALIZATION_HISTORICAL = (\n'
                      b'    "sentinel.alpaca-openfigi-dividend-current-window/2",\n'
                      b'    "sentinel.alpaca-openfigi-dividend-current-window/3",\n'
                      b')\n'
                      b'ALPACA_NORMALIZATION = "sentinel.alpaca-openfigi-dividend-current-window/4"')
    previous_policy = (b'ALPACA_NORMALIZATION_HISTORICAL = '
                       b'("sentinel.alpaca-openfigi-dividend-current-window/2",)\n'
                       b'ALPACA_NORMALIZATION = "sentinel.alpaca-openfigi-dividend-current-window/3"')
    assert previous.count(current_policy) == 1
    historical = previous.replace(current_policy, previous_policy)
    predecessor = economic_manifest._retired_source_profile()['reverse'][basis.ALPACA_PAGE_COMPILER]['after']
    assert hashlib.sha256(historical).hexdigest() == predecessor
    assert economic_manifest.page_contribution(basis.ALPACA_PAGE_COMPILER, historical) == basis.ALPACA_PAGE_BEFORE

    tampered = historical.replace(b'ORDER BY p.ticker', b'ORDER BY p.ticker DESC', 1)
    assert tampered != historical
    assert economic_manifest.page_contribution(basis.ALPACA_PAGE_COMPILER, tampered) == hashlib.sha256(tampered).hexdigest()

    read = Path.read_bytes
    dependency = path.with_name(name)
    monkeypatch.setattr(Path, 'read_bytes',
                        lambda self: read(self) + b'\n# unknown read change\n' if self == dependency else read(self))
    assert economic_manifest.page_contribution(basis.ALPACA_PAGE_COMPILER, historical) == hashlib.sha256(historical).hexdigest()
    assert economic_manifest.page_contribution(basis.ALPACA_PAGE_COMPILER, raw) == hashlib.sha256(raw).hexdigest()


def test_unknown_alpaca_index_layout_changes_complete_economic_identity(monkeypatch):
    before = economic_manifest.identity(schema='qualification-economic-boundary')
    read = economic_manifest._module_raw
    raw = read(basis.ALPACA_PAGE_COMPILER)
    changed = raw.replace(b'security_id text COLLATE "C"',
                          b'security_id text COLLATE "POSIX"', 1)
    assert changed != raw
    monkeypatch.setattr(economic_manifest, '_module_raw',
                        lambda name: changed if name == basis.ALPACA_PAGE_COMPILER else read(name))
    after = economic_manifest.identity(schema='qualification-economic-boundary')
    contribution = {row['module']: row['sha256'] for row in after['files']}
    assert contribution[basis.ALPACA_PAGE_COMPILER] == hashlib.sha256(changed).hexdigest()
    assert after['sha256'] != before['sha256']


def test_other_modules_never_gain_physical_mapping():
    raw=b'unknown compiler'
    assert basis.contribution('sentinel.core.input_domains',raw)==hashlib.sha256(raw).hexdigest()


def test_unsealed_mapping_cannot_retain_the_current_strategy(monkeypatch):
    current_strategy = CURRENT_STRATEGY
    assert digest(production_strategy()[1]) == current_strategy
    monkeypatch.setattr(basis,'PROFILE_SHA256','0'*64)
    assert digest(production_strategy()[1]) != current_strategy


def test_tampered_physical_witness_refuses(monkeypatch,tmp_path):
    target=tmp_path/'changed.json';target.write_bytes(basis.PROFILE.read_bytes()+b' ')
    monkeypatch.setattr(basis,'PROFILE',target)
    with pytest.raises(ValueError,match='WITNESS_CHANGED'):basis._profile()


def test_removed_complete_byte_guard_has_falsifier(monkeypatch):
    text=inspect.getsource(basis.contribution)
    guard="actual == value['compilers'][module]['after']"
    assert text.count(guard)==1
    space={}
    exec(compile(text.replace(guard,'True'),'physical-source-falsifier','exec'),basis.__dict__,space)
    monkeypatch.setattr(basis,'contribution',space['contribution'])
    with pytest.raises(AssertionError):
        test_exact_current_compiler_preserves_original_contribution_and_unknown_bytes_do_not('sentinel.feed.rolling_store')
