"""Exact refactor witnesses, authenticated from complete verified-main sources."""
import hashlib
import importlib
import inspect
import json
from pathlib import Path

import pytest

from sentinel import economic_manifest, identity, performance_source_basis as basis


# Independently read with git show c585b7f:<path> | sha256sum before sealing.
BASELINES = {
    'sentinel.core.session': '221a20b69eb3ad0dc877bec7789de608fe85dc6397891b8c9060bbd1f66717e8',
    'sentinel.feed.universe': '48fd9b18b13433c51c0e9e7d9e981e42620e2792ef6b3bcbc3dd233261c1080c',
    'stock_strategy_shared.wealth_core.feed': 'afa9324811921271a139500764aee19b85dec96f9a499d392c12f25f97e6ee32',
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def replace_once(raw, current, previous):
    assert raw.count(current) == 1
    return raw.replace(current, previous, 1)


def predecessor_source(module, raw):
    """Undo only the documented copy/index changes, then authenticate all bytes."""
    if module == 'sentinel.core.session':
        raw = replace_once(raw,
            b'        # Public serialization deep-copies each bounded series below. Borrow\n'
            b'        # retained arrays here so the same history is not copied twice.\n'
            b'        raw["feed"] = _bounded_feed_dict(raw["feed"], protected, _copy_arrays=False)\n',
            b'        raw["feed"] = _bounded_feed_dict(raw["feed"], protected, _copy_arrays=_copy_feed)\n')
    elif module == 'sentinel.feed.universe':
        raw = replace_once(raw, b'        self._by_security: dict[str, list[Listing]] = {}\n', b'')
        raw = replace_once(raw, b'            self._by_security.setdefault(l.permaticker, []).append(l)\n', b'')
        raw = replace_once(raw,
            b'        symbols = {item.ticker.upper() for item in self._by_security.get(security_id, ())\n'
            b'                   if item.covers(session)}\n',
            b'        symbols = {ticker for ticker, listings in self._by_ticker.items()\n'
            b'                   if any(item.permaticker == security_id and item.covers(session)\n'
            b'                          for item in listings)}\n')
    elif module == 'stock_strategy_shared.wealth_core.feed':
        raw = replace_once(raw, b'from functools import cached_property\n', b'')
        raw = replace_once(raw, b'        return self.signal_closes[-length:]\n',
                           b'        return list(self.signal_closes[-length:])\n')
        raw = replace_once(raw,
            b'    eligibility: dict[str, EligibilityResult]\n\n'
            b'    @cached_property\n'
            b'    def signal_windows(self) -> dict[str, list[float]]:\n'
            b'        """Filtered compatibility view; strategy inputs keep positional gaps."""\n'
            b'        return {bar.security_id: [close for close in bar.closes if close is not None]\n'
            b'                for bar in self.security_bars}\n',
            b'    signal_windows: dict[str, list[float]]\n'
            b'    eligibility: dict[str, EligibilityResult]\n')
        raw = replace_once(raw,
            b'                security_bars,\n'
            b'                {b.security_id: EligibilityResult(\n',
            b'                security_bars,\n'
            b'                {b.security_id: [c for c in b.closes if c is not None]\n'
            b'                 for b in security_bars},\n'
            b'                {b.security_id: EligibilityResult(\n')
        raw = replace_once(raw,
            b'        daily = [to_daily_bar(b, self.series[b.security_id]) for b in visible]\n'
            b'        sec_bars: list[SecurityBar] = []\n',
            b'        daily = [to_daily_bar(b, self.series[b.security_id]) for b in visible]\n'
            b'        windows: dict[str, list[float]] = {}\n'
            b'        sec_bars: list[SecurityBar] = []\n')
        raw = replace_once(raw, b'            signal_window = s.signal_window()\n',
            b'            signal_window = s.signal_window()\n'
            b'            w = [c for c in signal_window if c is not None]\n'
            b'            windows[b.security_id] = w\n')
        raw = replace_once(raw, b'                                 security_bars=sec_bars,\n',
            b'                                 security_bars=sec_bars, signal_windows=windows,\n')
    else:
        raise AssertionError(module)
    assert sha(raw) == BASELINES[module]
    return raw


@pytest.mark.parametrize('module', sorted(BASELINES))
def test_complete_predecessor_module_reconstructs_independently_verified_bytes(module):
    raw = Path(importlib.import_module(module).__file__).read_bytes()
    predecessor_source(module, raw)
    with pytest.raises(AssertionError):
        predecessor_source(module, raw + b'\n# neighboring economic edit\n')


@pytest.mark.parametrize('module', sorted(BASELINES))
def test_only_complete_recognized_candidate_bytes_preserve_contribution(module):
    raw = Path(importlib.import_module(module).__file__).read_bytes()
    assert basis.contribution(module, raw) == BASELINES[module]
    changed = raw + b'\n# unreviewed neighboring edit\n'
    assert basis.contribution(module, changed) == sha(changed)


def test_unrecognized_module_never_inherits_known_candidate_contribution():
    raw = Path(importlib.import_module('sentinel.core.session').__file__).read_bytes()
    assert basis.contribution('sentinel.core.unreviewed', raw) == sha(raw)


def test_tampered_profile_bytes_refuse(monkeypatch, tmp_path):
    path = tmp_path / 'profile.json'
    path.write_bytes(basis.PROFILE.read_bytes() + b' ')
    monkeypatch.setattr(basis, 'PROFILE', path)
    with pytest.raises(ValueError, match='WITNESS_CHANGED'):
        basis._profile()


@pytest.mark.parametrize('change', ['schema', 'authority', 'revision', 'checker',
                                   'missing', 'extra', 'before', 'after', 'member-shape'])
def test_profile_contract_refuses_even_if_outer_byte_pin_is_replaced(monkeypatch, tmp_path, change):
    value = json.loads(basis.PROFILE.read_bytes())
    member = value['modules']['sentinel.core.session']
    if change == 'schema':
        value['schema'] = 'foreign/1'
    elif change == 'authority':
        value['authority_effect'] = 'BROKER'
    elif change == 'revision':
        value['base_revision'] = 'a'*40
    elif change == 'checker':
        value['module_sha256'] = 'a'*64
    elif change == 'missing':
        value['modules'].pop('sentinel.feed.universe')
    elif change == 'extra':
        value['modules']['sentinel.core.unreviewed'] = dict(member)
    elif change == 'before':
        member['before'] = 'a'*64
    elif change == 'after':
        member['after'] = 'malformed'
    else:
        member['extra'] = None
    raw = json.dumps(value).encode()
    path = tmp_path / 'profile.json'
    path.write_bytes(raw)
    monkeypatch.setattr(basis, 'PROFILE', path)
    monkeypatch.setattr(basis, 'PROFILE_SHA256', sha(raw))
    with pytest.raises(ValueError, match='PERFORMANCE_SOURCE_'):
        basis._profile()


def test_duplicate_profile_keys_refuse_even_with_matching_byte_pin(monkeypatch, tmp_path):
    raw = basis.PROFILE.read_bytes()
    raw = replace_once(raw, b'"authority_effect": "NONE",',
                       b'"authority_effect": "NONE", "authority_effect": "NONE",')
    path = tmp_path / 'profile.json'
    path.write_bytes(raw)
    monkeypatch.setattr(basis, 'PROFILE', path)
    monkeypatch.setattr(basis, 'PROFILE_SHA256', sha(raw))
    with pytest.raises(ValueError, match='DUPLICATE_KEY'):
        basis._profile()


def test_full_runtime_package_hash_remains_actual_and_unknown_wealth_edits_move_strategy(tmp_path):
    root = tmp_path / 'wealth_core'
    root.mkdir()
    module = 'stock_strategy_shared.wealth_core.feed'
    raw = Path(importlib.import_module(module).__file__).read_bytes()
    (root / 'feed.py').write_bytes(raw)
    (root / 'engine.py').write_bytes(b'unchanged = True\n')
    framed = b'engine.py\0' + sha((root / 'engine.py').read_bytes()).encode() + b'\n'
    actual = sha(framed + b'feed.py\0' + sha(raw).encode() + b'\n')
    previous = sha(framed + b'feed.py\0' + sha(predecessor_source(module, raw)).encode() + b'\n')

    assert identity.source_hash(root)['hash'] == actual != previous
    assert basis.wealth_core_source_hash(root)['hash'] == previous
    (root / 'engine.py').write_bytes(b'unchanged = False\n')
    assert identity.source_hash(root)['hash'] != actual
    assert basis.wealth_core_source_hash(root)['hash'] != previous
    (root / 'feed.py').write_bytes(raw + b'\n# unreviewed feed bytes\n')
    assert basis.wealth_core_source_hash(root) == identity.source_hash(root)


def test_feed_refactor_keeps_all_canonical_golden_outputs_and_seven_hashes():
    from stock_strategy_shared.wealth_core import feed
    from stock_strategy_shared.wealth_core.golden import golden_scenario
    from stock_strategy_shared.wealth_core.run import run_with_hashes

    raw = predecessor_source('stock_strategy_shared.wealth_core.feed',
                             Path(feed.__file__).read_bytes())
    namespace = dict(vars(feed))
    exec(compile(raw, '<verified-main-feed>', 'exec'), namespace)
    scenario = golden_scenario()
    values = []
    for constructor in (namespace['Feed'], feed.Feed):
        result, hashes = run_with_hashes(
            sessions=scenario.sessions, bars_by_session=scenario.bars_by_session,
            meta=scenario.meta, starting_cash=scenario.starting_cash,
            terminal_events=scenario.terminal_events, feed=constructor(scenario.meta))
        values.append((result.to_dict(), hashes.to_dict()))
    assert values[0] == values[1]


def test_new_source_dependencies_still_refuse_before_mapping(monkeypatch):
    original = economic_manifest._module_raw
    monkeypatch.setattr(economic_manifest, '_module_raw', lambda name:
        original(name) + b'\nimport sentinel.feed.store\n'
        if name == 'sentinel.core.session' else original(name))
    with pytest.raises(economic_manifest.EconomicManifestRefused, match='ECONOMIC_DEPENDENCY_CHANGED'):
        economic_manifest.identity(schema='refactor-qualification')


def test_removed_complete_candidate_guard_is_detected(monkeypatch):
    text = inspect.getsource(basis.contribution)
    guard = "actual == record['after']"
    assert text.count(guard) == 1
    namespace = {}
    exec(compile(text.replace(guard, 'True'), '<source-guard-falsifier>', 'exec'),
         basis.__dict__, namespace)
    monkeypatch.setattr(basis, 'contribution', namespace['contribution'])
    with pytest.raises(AssertionError):
        test_only_complete_recognized_candidate_bytes_preserve_contribution('sentinel.core.session')


@pytest.mark.parametrize('guard,change', [
    ("or set(value['modules']) != set(BASELINES)", 'missing'),
    ("or record['before'] != BASELINES[name]", 'before'),
    ("or value['module_sha256'] != _sha(normalized)", 'checker'),
])
def test_removed_witness_contract_guards_are_detected(monkeypatch, tmp_path, guard, change):
    text = inspect.getsource(basis._profile)
    assert text.count(guard) == 1
    namespace = {}
    exec(compile(text.replace(guard, 'or False'), '<witness-contract-falsifier>', 'exec'),
         basis.__dict__, namespace)
    monkeypatch.setattr(basis, '_profile', namespace['_profile'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_profile_contract_refuses_even_if_outer_byte_pin_is_replaced(monkeypatch, tmp_path, change)


def test_removed_witness_byte_pin_is_detected(monkeypatch, tmp_path):
    text = inspect.getsource(basis._profile)
    guard = "PROFILE_SHA256 == '0'*64 or _sha(raw) != PROFILE_SHA256"
    assert text.count(guard) == 1
    namespace = {}
    exec(compile(text.replace(guard, 'False'), '<witness-byte-falsifier>', 'exec'),
         basis.__dict__, namespace)
    monkeypatch.setattr(basis, '_profile', namespace['_profile'])
    with pytest.raises(pytest.fail.Exception, match='DID NOT RAISE'):
        test_tampered_profile_bytes_refuse(monkeypatch, tmp_path)
