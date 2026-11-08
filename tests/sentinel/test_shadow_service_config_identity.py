"""Exact moved definitions and legacy aliases, independently pinned to29ff."""
import ast
from dataclasses import asdict
from decimal import Decimal
import hashlib
import importlib
import json
from pathlib import Path
import pickle

import pytest

from sentinel import shadow_service_config as config
from sentinel import shadow_exit_codes as codes
from sentinel.feed.observation_timing import POLICY


# Derived from exact29ff5f6592a46e89f13ed5d8416503071dc74ccf, allowing
# only shadow_runtime.SHADOW_PUBLICATION_TIMING_POLICY -> canonical POLICY.
ORIGINAL={
    '_OBSERVATION_ID':'d0ababc5602e448d25d54a4bee760d199d678d74068e776c3a2ab0c1e0a2c707',
    '_SHA256':'4362ec044bf50516be5f082fd5a34228d1ef5c9918665b9d1ffdc4bf1955d2e4',
    '_BROKER_AUTHORITY_ENV':'70174fa915aae62edf70bcfa6e4e97ef624d88c13ffee6f99e0474f02706df40',
    'ShadowServiceRefused':'d669f3b42a70cbc5b18d4911bda3cfd73c013a95ebd6f404fe06daa9665d7b0d',
    'ShadowServiceRetry':'7e174a1c6711a53a333a3ebdfbcef3835d83b3024d799e727593d5e3c0e31834',
    'ShadowServiceWaiting':'3085705abcf7d0bbf3807f1111643dc2d34fb8132c4e60a149ab00d27fafc168',
    'ShadowServiceConfig':'e2fd95a704d1d8c9a31b8c8284d6bde642cd8f9358841e8f90198192dea11402',
}
EXIT={'EXIT_REFUSED':2,'EXIT_WAITING':10,'EXIT_RETRY':11,
      'EXIT_AVAILABILITY':12,'EXIT_DEPENDENCY_UNAVAILABLE':13}


def _canonical(node):
    if isinstance(node,ast.AST):
        return {'kind':type(node).__name__,'fields':{key:_canonical(value)
            for key,value in ast.iter_fields(node) if key!='type_params' or value}}
    if isinstance(node,list):return [_canonical(value) for value in node]
    return node


def _definitions(text):
    result={}
    for node in ast.parse(text).body:
        names=([node.name] if isinstance(node,ast.ClassDef) else
            [target.id for target in node.targets if isinstance(target,ast.Name)]
            if isinstance(node,ast.Assign) else [])
        for name in names:result[name]=node
    return result


def _assert_original(text):
    definitions=_definitions(text)
    actual={name:hashlib.sha256(json.dumps(_canonical(definitions[name]),
        sort_keys=True,separators=(',',':')).encode()).hexdigest() for name in ORIGINAL}
    assert actual==ORIGINAL,'canonical config/error/env validation changed'


def test_config_errors_and_env_guards_are_exact_original_ast():
    _assert_original(Path(config.__file__).read_text())


def test_removed_config_guard_is_detected():
    source=Path(config.__file__).read_text()
    broken=source.replace('if leaked:','if False:',1)
    assert broken!=source
    with pytest.raises(AssertionError,match='validation changed'):_assert_original(broken)


@pytest.mark.parametrize('module',['sentinel.shadow_service','sentinel.shadow_recovery'])
def test_old_config_and_exception_aliases_are_same_objects(module):
    old=importlib.import_module(module)
    for name in ('ShadowServiceConfig','ShadowServiceRefused','ShadowServiceRetry','ShadowServiceWaiting'):
        assert getattr(old,name) is getattr(config,name)
        assert pickle.loads(('c'+module+'\n'+name+'\n.').encode()) is getattr(config,name)


def test_service_private_constants_remain_aliases_not_duplicate_definitions():
    from sentinel import shadow_service
    definitions=_definitions(Path(shadow_service.__file__).read_text())
    assert not set(definitions)&set(ORIGINAL)
    for name in ('_OBSERVATION_ID','_SHA256','_BROKER_AUTHORITY_ENV'):
        assert getattr(shadow_service,name) is getattr(config,name)


def _assert_exit_codes(text):
    definitions=_definitions(text)
    assert {name:ast.literal_eval(definitions[name].value) for name in EXIT}==EXIT, \
        'canonical exit codes changed'
    assert all(isinstance(definitions[name].value,ast.Constant) for name in EXIT)


def test_exit_codes_are_original_literals_and_reexported():
    from sentinel import shadow_worker,shadow_supervisor
    _assert_exit_codes(Path(codes.__file__).read_text())
    for module in (shadow_worker,shadow_supervisor):
        assert not set(_definitions(Path(module.__file__).read_text()))&set(EXIT)
        assert {name:getattr(module,name) for name in EXIT}==EXIT


def test_exit_code_change_is_detected():
    source=Path(codes.__file__).read_text()
    broken=source.replace('EXIT_REFUSED = 2','EXIT_REFUSED = 0')
    assert broken!=source
    with pytest.raises(AssertionError,match='exit codes changed'):_assert_exit_codes(broken)


def test_policy_is_imported_from_unchanged_canonical_timing_module():
    from sentinel import shadow_runtime
    assert config.POLICY is POLICY is shadow_runtime.SHADOW_PUBLICATION_TIMING_POLICY
    tree=ast.parse(Path(config.__file__).read_text())
    assert any(isinstance(node,ast.ImportFrom) and node.module=='sentinel.feed.observation_timing'
        and any(alias.name=='POLICY' for alias in node.names) for node in tree.body)
    assert not any(isinstance(node,ast.Constant) and isinstance(node.value,str)
        and node.value==POLICY for node in ast.walk(tree))


def test_config_dataclass_payload_retains_exact_fields_and_decimal():
    env={key:'a'*64 for key in ('SENTINEL_VALIDATED_SOURCE_IDENTITY_SHA256',
        'SENTINEL_VALIDATED_SHADOW_CONFIG_SHA256','SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256',
        'SENTINEL_REVIEWED_VALIDATION_BUNDLE_SHA256')}
    env.update(SENTINEL_SHADOW_OBSERVATION_ENABLED='true',
        SENTINEL_REVIEWED_DEPLOYMENT_MODE='shadow',SENTINEL_DATABASE_URL='private-placeholder')
    value=config.ShadowServiceConfig.from_env(env)
    assert pickle.loads(pickle.dumps(value))==value
    assert asdict(value)==dict(database_url='private-placeholder',
        observation_id='primary',starting_cash=Decimal(50000),publication_timing_policy=POLICY,
        poll_seconds=300,operational_source_only=False)
