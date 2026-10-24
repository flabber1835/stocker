"""All-hour owner/scope checks; never execute the manual process scenario."""
import ast
from datetime import datetime, timezone
import inspect
import importlib
import json

import pytest

from tools import current_session_qualification as owner


def test_exact_manual_owner_is_registered_without_becoming_an_installation_gate():
    registered, digest = owner.read_registry()
    assert registered == owner.EXPECTED and len(digest) == 64
    assert registered['authority_effect'] == 'NONE'
    assert registered['installation_gate'] is False
    assert registered['live_money_qualified'] is False
    assert registered['opening_timing_qualified'] is False
    assert registered['expected_scenarios'] == 1


@pytest.mark.parametrize('change', [
    {'owner': 'other'}, {'selector': 'tests/sentinel/test_other.py::test_other'},
    {'authority_effect': 'LIVE'}, {'installation_gate': True},
    {'expected_scenarios': True}, {'native_broker_calls': False}, {'unexpected': 'field'},
])
def test_manual_registry_cannot_change_identity_scope_or_authority(tmp_path, change):
    path = tmp_path / 'owner.json'
    path.write_text(json.dumps(owner.EXPECTED | change))
    with pytest.raises(owner.SessionQualificationRefused, match='EXACT_MANUAL_OWNER'):
        owner.read_registry(path)


def test_manual_registry_rejects_duplicate_fields(tmp_path):
    path = tmp_path / 'owner.json'
    path.write_text('{"owner":"a","owner":"b"}')
    with pytest.raises(owner.SessionQualificationRefused, match='DUPLICATE_OWNER'):
        owner.read_registry(path)


def test_real_calendar_eligibility_does_not_require_skipping_an_all_hour_test():
    before = owner.session_status(datetime(2026, 10, 24, 16, tzinfo=timezone.utc))
    after = owner.session_status(datetime(2026, 10, 26, 14, tzinfo=timezone.utc))
    assert before['result'] == 'ELIGIBLE_PREOPEN_SESSION'
    assert before['original_execute_at'] == '2026-10-26T13:31:00+00:00'
    assert after['result'] == 'BLOCKED_CURRENT_SESSION'
    with pytest.raises(owner.SessionQualificationRefused, match='AWARE_ACTUAL'):
        owner.session_status(datetime(2026, 10, 24))


def junit(tmp_path, *, case=owner.CASE, classname='tools.current_session_service_recovery', status=''):
    path = tmp_path / 'scenario.xml'
    path.write_text(f'<testsuite><testcase name="{case}" classname="{classname}">{status}</testcase></testsuite>')
    return path


def test_manual_junit_requires_the_single_exact_scenario(tmp_path):
    assert len(owner.require_junit(junit(tmp_path))) == 64


@pytest.mark.parametrize('change', [
    {'case': 'test_wrong'}, {'classname': 'tests.sentinel.test_current_service_recovery'},
    {'status': '<skipped/>'}, {'status': '<failure/>'}, {'status': '<error/>'},
])
def test_manual_junit_cannot_turn_other_or_nonpassing_evidence_into_a_pass(tmp_path, change):
    with pytest.raises(owner.SessionQualificationRefused, match='EXACT_PASSING_MANUAL'):
        owner.require_junit(junit(tmp_path, **change))


def test_manual_junit_cannot_hide_a_second_case(tmp_path):
    path = junit(tmp_path)
    path.write_text(path.read_text().replace('</testsuite>', '<testcase name="extra"/></testsuite>'))
    with pytest.raises(owner.SessionQualificationRefused, match='EXACT_PASSING_MANUAL'):
        owner.require_junit(path)


def test_blocked_actual_session_refuses_before_evidence_or_private_host(tmp_path, monkeypatch):
    monkeypatch.setattr(owner, 'read_registry', lambda: (owner.EXPECTED, 'a' * 64))
    monkeypatch.setattr(owner, 'session_status', lambda _now: {'result': 'BLOCKED_CURRENT_SESSION'})
    monkeypatch.setattr(owner, 'require_private_host', lambda _env: pytest.fail('private host must remain untouched'))
    output = tmp_path / 'must-not-exist'
    with pytest.raises(owner.SessionQualificationRefused, match='CURRENT_PREOPEN_SESSION_UNAVAILABLE'):
        owner.run(output)
    assert not output.exists()


def test_private_context_and_provider_credentials_are_not_optional():
    with pytest.raises(owner.SessionQualificationRefused, match='OWNED_PRIVATE_POSTGRES'):
        owner.require_private_host({})
    with pytest.raises(owner.SessionQualificationRefused, match='PROVIDER_CREDENTIAL'):
        owner.require_private_host({'ALPACA_API_KEY': 'must-not-be-used'})


def test_manual_runner_refuses_production_physical_identity_before_connecting():
    with pytest.raises(owner.SessionQualificationRefused, match='PRODUCTION_DATABASE_FORBIDDEN'):
        owner.require_private_host({'SENTINEL_PRIVATE_PG16_URL': 'not-used',
            'SENTINEL_PRIVATE_PG16_SYSTEM_ID': '7691913275518591014',
            'SENTINEL_PRIVATE_QUALIFICATION_TOKEN': 'not-used'})


def test_manual_scenario_retains_real_guard_and_has_no_skip_or_all_hour_collection():
    scenario = owner.ROOT / owner.MODULE
    source = scenario.read_text()
    tree = ast.parse(source)
    functions = [node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name.startswith('test_')]
    assert [node.name for node in functions] == [owner.CASE]
    assert 'CURRENT_PREOPEN_SESSION_UNAVAILABLE' in source
    assert 'pytest.skip(' not in source and 'pytest.mark.skip' not in source
    ordinary = (owner.ROOT / 'tests/sentinel/test_current_service_recovery.py').read_text()
    assert owner.CASE not in ordinary
    assert 'pytest.skip(' not in ordinary and 'pytest.mark.skip' not in ordinary
    assert not owner.MODULE.startswith('tests/')


def test_manual_module_and_explicit_fixtures_import_without_running_the_scenario():
    module = importlib.import_module('tools.current_session_service_recovery')
    assert callable(getattr(module, owner.CASE))
    assert callable(module.current) and callable(module.conn) and callable(module.cluster)
    assert callable(module.isolated_source_cache)


def test_original_actual_session_guard_falsifier_still_prevents_the_first_mutation(tmp_path, monkeypatch):
    class ReachedMutation(Exception):
        pass
    monkeypatch.setattr(owner, 'read_registry', lambda: (owner.EXPECTED, 'a' * 64))
    monkeypatch.setattr(owner, 'session_status', lambda _now: {'result': 'BLOCKED_CURRENT_SESSION'})
    def first_mutation(_self, *_args, **_kwargs):
        raise ReachedMutation
    monkeypatch.setattr(type(tmp_path), 'mkdir', first_mutation)
    with pytest.raises(owner.SessionQualificationRefused, match='CURRENT_PREOPEN_SESSION_UNAVAILABLE'):
        owner.run(tmp_path / 'new')
    source = inspect.getsource(owner.run)
    needle = "require(status['result'] == 'ELIGIBLE_PREOPEN_SESSION', 'CURRENT_PREOPEN_SESSION_UNAVAILABLE')"
    assert needle in source
    broken = source.replace(needle, 'require(True, "removed guard")', 1)
    namespace = {}
    exec(compile(broken, '<manual-session-guard-mutant>', 'exec'), vars(owner), namespace)
    # Keep the real branch boundary out of this small pure mutation check.
    monkeypatch.setattr(owner.sys, 'platform', 'linux')
    with pytest.raises(ReachedMutation):
        namespace['run'](tmp_path / 'new')
