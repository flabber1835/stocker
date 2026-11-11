"""Exact compiler refactors preserve economics without widening old witnesses."""
from copy import deepcopy
import hashlib
import importlib
import inspect
import json
from pathlib import Path
import textwrap

import pytest

from sentinel import economic_manifest as economic, operation_read_source_basis as basis
from sentinel.feed.rolling_contract import digest
from sentinel.strategy import production_strategy

BASE = '277160861e2353d8ad93d15da8e2615ebdb11c18'
FIXTURE = Path(__file__).resolve().parents[1]/'support/operation-read-277-sources.json'
FIXTURE_SHA = '3d7fd186d316c3285cde43af4735cb389c66fe72196ce749a89e0acc14e640c0'
STRATEGY = 'caab7a1872fe4ec178aec659716a4bc70c0cd5ea79a88e33ffacd2ae0c7cf095'
SEMANTICS = '38c750bd9bb244bc71600aaeba8c4aad22d2095747f4199e9ac4e0bd433425cb'


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def baseline():
    raw=FIXTURE.read_bytes()
    assert sha(raw)==FIXTURE_SHA
    value=json.loads(raw)
    assert value['schema']=='sentinel.operation-read-baseline/1' and value['revision']==BASE
    assert set(value['modules'])==set(basis.BASELINES)
    for module,record in value['modules'].items():
        assert sha(record['source'].encode())==record['sha256']==basis.BASELINES[module]
    return value


def current(module):
    return Path(importlib.import_module(module).__file__).read_bytes()


def reconstruct(module, raw):
    """Reverse only the exact reviewed read-elision/routing source edits."""
    if module=='sentinel.execution.reconcile':
        change=(b'        elif _safe_non_book_action(verb):\n'
                b'            # These rows remain source/cash evidence, but supply no scalar or\n'
                b'            # material event here and do not need an equity mapping.\n'
                b'            continue\n')
        assert raw.count(change)==1
        raw=raw.replace(change,b'')
    else:
        assert module=='sentinel.execution.feed_actions'
        changes=(
            (b'from sentinel.feed.normalized_layout import query_router\n',
             b'from sentinel.feed.normalized_layout import candidate_query\n',1),
            (b'    query = query_router(conn)\n',b'',1),
            (b'query("',b'candidate_query(conn, "',3),
        )
        for old,new,count in changes:
            assert raw.count(old)==count
            raw=raw.replace(old,new)
    record=baseline()['modules'][module]
    assert raw==record['source'].encode()
    assert sha(raw)==record['sha256']
    return raw


@pytest.mark.parametrize('module',sorted(basis.BASELINES))
def test_full_reviewed_compiler_reconstructs_actual_independent_predecessor(module):
    raw=current(module)
    reconstruct(module,raw)
    assert sha(raw)==basis.CANDIDATES[module]!=basis.BASELINES[module]
    assert basis.contribution(module,raw)==basis.BASELINES[module]


def test_manifest_changes_only_its_reader_pin_and_all_old_witness_bytes_stay_exact():
    original=baseline()
    canonical=lambda value:json.dumps(value,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    profile=economic.manifest()
    assert {key:sha(canonical(value)) for key,value in profile.items() if key!='module_sha256'}==original['manifest']['fields_sha256']
    assert sha(economic.MANIFEST.read_bytes())==economic.MANIFEST_SHA256
    assert economic.MANIFEST_SHA256!=original['manifest']['sha256']
    assert set(basis.BASELINES)<=set(profile['input_compilers'])
    assert not set(basis.BASELINES)&set(profile['pure_contracts'])
    root=Path(economic.__file__).parents[1]
    for path,expected in original['legacy_files'].items():
        assert sha((root/path).read_bytes())==expected,path


def test_complete_strategy_and_all_original_economic_contributions_remain_exact():
    value=economic.identity(schema='operation-owned-action-source-qualification')
    profile=economic.manifest()
    assert value['sha256']==SEMANTICS
    assert value['implementation_sha256']==profile['implementation_sha256']
    assert value['economic_implementation']['preserved_behavior'] is True
    assert {item['module']:item['sha256'] for item in value['files']}=={
        **profile['pure_contracts'],**profile['input_compilers']}
    assert digest(production_strategy()[1])==STRATEGY


@pytest.mark.parametrize('module',sorted(basis.BASELINES))
def test_unknown_neighbor_keeps_actual_identity_and_breaks_economic_equivalence(module,monkeypatch):
    changed=current(module)+b'\n# unknown neighboring compiler edit\n'
    assert basis.contribution(module,changed)==sha(changed), 'unknown compiler kept old economic identity'
    with pytest.raises(AssertionError):reconstruct(module,changed)
    read=economic._module_raw
    monkeypatch.setattr(economic,'_module_raw',lambda name:changed if name==module else read(name))
    value=economic.identity(schema='unknown-operation-read-neighbor')
    assert value['sha256']==value['implementation_sha256']!=SEMANTICS, 'unknown compiler kept old economic identity'
    assert value['economic_implementation']['preserved_behavior'] is False
    assert digest(production_strategy()[1])!=STRATEGY


@pytest.mark.parametrize('module,old,new',[
    ('sentinel.execution.reconcile',b'if effective <= start or effective > end:',b'if effective < start or effective > end:'),
    ('sentinel.execution.feed_actions',b'AND split_ratio<>1 ',b'AND split_ratio=1 '),
])
def test_domain_or_window_mutation_cannot_inherit_read_refactor_identity(module,old,new,monkeypatch):
    raw=current(module);assert raw.count(old)==1
    changed=raw.replace(old,new)
    assert basis.contribution(module,changed)==sha(changed)
    with pytest.raises(AssertionError):reconstruct(module,changed)
    read=economic._module_raw
    monkeypatch.setattr(economic,'_module_raw',lambda name:changed if name==module else read(name))
    assert digest(production_strategy()[1])!=STRATEGY


def test_no_other_module_gains_mapping():
    raw=current('sentinel.execution.feed_actions')
    assert basis.contribution('sentinel.core.unreviewed',raw)==sha(raw)


@pytest.mark.parametrize('module',sorted(basis.BASELINES))
def test_unknown_dependencies_still_refuse_before_a_contribution_can_be_used(module,monkeypatch):
    read=economic._module_raw
    changed=current(module)+b'\nimport sentinel.feed.unreviewed_action_input\n'
    monkeypatch.setattr(economic,'_module_raw',lambda name:changed if name==module else read(name))
    with pytest.raises(economic.EconomicManifestRefused,match='ECONOMIC_DEPENDENCY_CHANGED'):
        economic.identity(schema='unknown-operation-read-dependency')


def test_unsealed_pair_never_preserves_original_strategy(monkeypatch):
    monkeypatch.setattr(basis,'PROFILE_SHA256','0'*64)
    assert digest(production_strategy()[1])!=STRATEGY


def test_missing_or_tampered_profile_refuses(monkeypatch,tmp_path):
    path=tmp_path/'missing.json';monkeypatch.setattr(basis,'PROFILE',path)
    with pytest.raises(FileNotFoundError):basis._profile()
    original=Path(basis.__file__).with_name('operation-read-source-transition.json').read_bytes()
    path.write_bytes(original+b' ')
    with pytest.raises(ValueError,match='WITNESS_CHANGED'):basis._profile()


@pytest.mark.parametrize('change',['schema','authority','revision','checker','missing','extra','before','after','member-shape'])
def test_changed_profile_contract_refuses_even_with_replaced_outer_pin(change,monkeypatch,tmp_path):
    value=json.loads(basis.PROFILE.read_bytes());module=next(iter(basis.BASELINES))
    if change=='schema':value['schema']='foreign/1'
    elif change=='authority':value['authority_effect']='BROKER'
    elif change=='revision':value['base_revision']='a'*40
    elif change=='checker':value['module_sha256']='a'*64
    elif change=='missing':value['compilers'].pop(module)
    elif change=='extra':value['compilers']['sentinel.core.unreviewed']=deepcopy(value['compilers'][module])
    elif change=='before':value['compilers'][module]['before']='a'*64
    elif change=='after':value['compilers'][module]['after']='b'*64
    else:value['compilers'][module]['extra']=True
    raw=json.dumps(value).encode();path=tmp_path/'changed.json';path.write_bytes(raw)
    monkeypatch.setattr(basis,'PROFILE',path);monkeypatch.setattr(basis,'PROFILE_SHA256',sha(raw))
    with pytest.raises(ValueError,match='OPERATION_READ_SOURCE_'):basis._profile()


def test_duplicate_profile_keys_refuse_even_with_replaced_outer_pin(monkeypatch,tmp_path):
    raw=basis.PROFILE.read_bytes();key=b'"authority_effect": "NONE",'
    assert raw.count(key)==1
    raw=raw.replace(key,key+b' "authority_effect": "NONE",')
    path=tmp_path/'duplicate.json';path.write_bytes(raw)
    monkeypatch.setattr(basis,'PROFILE',path);monkeypatch.setattr(basis,'PROFILE_SHA256',sha(raw))
    with pytest.raises(ValueError,match='DUPLICATE_KEY'):basis._profile()


def test_removed_exact_byte_guard_is_detected(monkeypatch):
    code=textwrap.dedent(inspect.getsource(basis.contribution))
    guard="actual == value['compilers'][module]['after']";assert code.count(guard)==1
    namespace={}
    exec(compile(code.replace(guard,'True'),'<removed-operation-read-byte-guard>','exec'),vars(basis),namespace)
    monkeypatch.setattr(basis,'contribution',namespace['contribution'])
    with pytest.raises(AssertionError,match='unknown compiler kept old economic identity'):
        test_unknown_neighbor_keeps_actual_identity_and_breaks_economic_equivalence('sentinel.execution.feed_actions',monkeypatch)


def test_removed_identity_dispatch_is_detected(monkeypatch):
    code=textwrap.dedent(inspect.getsource(economic.identity))
    guard='elif name in operation_read_source_basis.BASELINES:';assert code.count(guard)==1
    namespace={}
    exec(compile(code.replace(guard,'elif False:'),'<removed-operation-read-dispatch>','exec'),vars(economic),namespace)
    monkeypatch.setattr(economic,'identity',namespace['identity'])
    with pytest.raises(AssertionError):
        test_complete_strategy_and_all_original_economic_contributions_remain_exact()
