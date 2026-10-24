"""Migrated contract families cannot regain implicit legacy substitutions."""
from pathlib import Path
import json
from types import SimpleNamespace

import pytest

from sentinel import identity, schema
from sentinel.feed import coherence, store
from tests.sentinel import conftest as legacy


FAMILY = json.loads((Path(__file__).with_name('current-contract-modules.json')).read_text())


def test_current_family_is_explicit_existing_and_outside_legacy_registry():
    assert FAMILY['schema'] == 'sentinel.current-contract-test-family/1'
    names = FAMILY['modules']
    assert len(names) == len(set(names)) and names
    assert all(Path(__file__).with_name(name).is_file() for name in names)
    assert not {name[:-3] for name in names} & legacy._LEGACY_COMPATIBILITY_MODULES


@pytest.mark.parametrize('name', FAMILY['modules'])
def test_migrated_module_keeps_all_real_contract_boundaries(name, monkeypatch):
    before = (identity.require_feed_producer_identity, store.require_feed_schema,
              coherence.assert_tickers_metadata, coherence.assert_seed_history,
              schema.require_runtime_schema)
    request = SimpleNamespace(module=SimpleNamespace(__name__=name[:-3]),
                              node=SimpleNamespace(name='test_current_guard'))
    legacy._runtime_schema_test_double_compat.__wrapped__(request, monkeypatch)
    assert before == (identity.require_feed_producer_identity, store.require_feed_schema,
                      coherence.assert_tickers_metadata, coherence.assert_seed_history,
                      schema.require_runtime_schema)


def test_reintroducing_a_legacy_opt_in_is_detected(monkeypatch):
    name = FAMILY['modules'][0][:-3]
    monkeypatch.setattr(legacy, '_LEGACY_COMPATIBILITY_MODULES',
                        legacy._LEGACY_COMPATIBILITY_MODULES | {name})
    with pytest.raises(AssertionError):
        test_current_family_is_explicit_existing_and_outside_legacy_registry()
