"""Reviewed SQL traversal changes never hide changed economic compiler bytes."""
import hashlib
import ast
import importlib
import inspect
import json
from pathlib import Path

import pytest

from sentinel import physical_read_source_basis as basis
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


def unchanged_compiler_body(module, raw):
    old=ast.parse(predecessor_sources()[module]);new=ast.parse(raw)
    if module=='sentinel.feed.rolling_store':
        original=next(n for n in old.body if isinstance(n,ast.FunctionDef) and n.name=='_rows')
        stream=next(n for n in new.body if isinstance(n,ast.FunctionDef) and n.name=='_stream_rows')
        # The SQL, parameters, C collation, row projection and checkpoints in
        # the physical leaf are the exact old ordered stream, without its route.
        offset=next(i for i,n in enumerate(original.body) if isinstance(n,ast.With))
        current_offset=next(i for i,n in enumerate(stream.body) if isinstance(n,ast.With))
        dump=lambda nodes:ast.dump(ast.Module(body=nodes,type_ignores=[]),include_attributes=False)
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
    ('sentinel.feed.action_history',b'session<%s',b'session<=%s')])
def test_compiler_arithmetic_and_sql_edits_fail_mechanical_proof(module,old,new):
    raw=Path(importlib.import_module(module).__file__).read_bytes()
    assert old in raw
    with pytest.raises(AssertionError):unchanged_compiler_body(module,raw.replace(old,new,1))


@pytest.mark.parametrize('module', sorted(basis.BASELINES))
def test_exact_current_compiler_preserves_original_contribution_and_unknown_bytes_do_not(module):
    raw=Path(importlib.import_module(module).__file__).read_bytes()
    assert basis.contribution(module,raw)==basis.BASELINES[module]
    changed=raw+b'\n# unknown compiler bytes\n'
    assert basis.contribution(module,changed)==hashlib.sha256(changed).hexdigest()


def test_other_modules_never_gain_physical_mapping():
    raw=b'unknown compiler'
    assert basis.contribution('sentinel.core.input_domains',raw)==hashlib.sha256(raw).hexdigest()


def test_unsealed_mapping_cannot_retain_the_original_strategy(monkeypatch):
    assert digest(production_strategy()[1])=='caab7a1872fe4ec178aec659716a4bc70c0cd5ea79a88e33ffacd2ae0c7cf095'
    monkeypatch.setattr(basis,'PROFILE_SHA256','0'*64)
    assert digest(production_strategy()[1])!='caab7a1872fe4ec178aec659716a4bc70c0cd5ea79a88e33ffacd2ae0c7cf095'


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
