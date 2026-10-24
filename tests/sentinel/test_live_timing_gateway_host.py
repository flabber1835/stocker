"""Offline handoff falsifiers. No Docker, provider or retained campaign access."""
from datetime import datetime, timedelta, timezone
import hashlib
import inspect
import json
from types import SimpleNamespace

import pytest

from tools import live_timing_gateway_host as handoff


def report():
    return {'schema': 'sentinel.real-clock-timing-report/1', 'mode': 'gateway',
        'campaign_id': handoff.CAMPAIGN, 'campaign_sha256': 'sealed-generated-subject',
        'result': 'PASS', 'gateway_qualified': True, 'original_execute_at': handoff.EXECUTE.isoformat(),
        'book_preserved': True, 'native_broker_calls': 0, 'authority_effect': 'NONE',
        'live_money_qualified': False, 'production_opening_qualified': False,
        'first_post_seconds': 120, 'complete_basket_seconds': 300, 'orders': 14, 'legs': 14}


def test_actual_original_session_interval_and_boundaries():
    assert handoff.eligibility(datetime(2026, 10, 24, 17, tzinfo=timezone.utc)) == 'BLOCKED_MARKET_SESSION'
    assert handoff.eligibility(handoff.EXECUTE - timedelta(seconds=601)) == 'BLOCKED_MARKET_SESSION'
    assert handoff.eligibility(handoff.EXECUTE - timedelta(seconds=600)) == 'ELIGIBLE_REAL_SESSION'
    assert handoff.eligibility(handoff.EXECUTE + timedelta(seconds=539)) == 'ELIGIBLE_REAL_SESSION'
    assert handoff.eligibility(handoff.EXECUTE + timedelta(seconds=540)) == 'BLOCKED_MARKET_SESSION'
    with pytest.raises(handoff.HandoffRefused, match='AWARE_ACTUAL'):
        handoff.eligibility(datetime(2026, 10, 26, 13, 31))


def test_wrong_launcher_hash_is_rejected_before_any_code_executes(tmp_path, monkeypatch):
    marker = tmp_path / 'must-not-exist'
    launcher = tmp_path / 'launcher.py'
    launcher.write_text(f'open({str(marker)!r}, "w").write("executed")')
    monkeypatch.setattr(handoff, 'LAUNCHER', launcher)
    with pytest.raises(handoff.HandoffRefused, match='ORIGINAL_HOST_LAUNCHER_CHANGED'):
        handoff.load_reviewed_host()
    assert not marker.exists()


def retained_fixture(tmp_path, monkeypatch):
    values = {'host-request.json': {'campaign_id': handoff.CAMPAIGN,
        'host_launcher_sha256': handoff.LAUNCHER_SHA},
        'postgres.json': {'container_id': handoff.PG_ID, 'system_identifier': handoff.SYSTEM_ID},
        'evidence/campaign/campaign.json': {'campaign_id': handoff.CAMPAIGN,
            'private_system_id': handoff.SYSTEM_ID, 'source_frontier': '2026-10-23'},
        'evidence/campaign/prepare-report.json': {'result': 'PREPARED'}}
    pins = {}
    for name, value in values.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        raw = json.dumps(value).encode()
        path.write_bytes(raw)
        pins[name] = hashlib.sha256(raw).hexdigest()
    value = {'file_sha256': pins['evidence/campaign/campaign.json']}
    raw = json.dumps(value).encode()
    (tmp_path / 'campaign-seal.json').write_bytes(raw)
    pins['campaign-seal.json'] = hashlib.sha256(raw).hexdigest()
    monkeypatch.setattr(handoff, 'OPERATION', tmp_path)
    monkeypatch.setattr(handoff, 'PINNED', pins)
    return pins


def test_evidence_drift_refuses_before_loading_or_touching_docker(tmp_path, monkeypatch):
    retained_fixture(tmp_path, monkeypatch)
    (tmp_path / 'host-request.json').write_bytes(b'{}')
    monkeypatch.setattr(handoff, 'load_reviewed_host', lambda: pytest.fail('must refuse before loading'))
    with pytest.raises(handoff.HandoffRefused, match='ORIGINAL_HANDOFF_EVIDENCE_CHANGED'):
        handoff.preflight()


@pytest.mark.parametrize('claimed', ['gateway-claim.json', 'gateway-report.json', 'original-execute-clock.json'])
def test_consumed_inner_namespace_cannot_be_reinvoked(tmp_path, monkeypatch, claimed):
    retained_fixture(tmp_path, monkeypatch)
    (tmp_path / 'evidence/campaign' / claimed).write_bytes(b'{}')
    with pytest.raises(handoff.HandoffRefused, match='ORIGINAL_GATEWAY_ALREADY_CONSUMED'):
        handoff.retained_inputs()


def test_consumed_host_claim_cannot_be_reinvoked(tmp_path, monkeypatch):
    retained_fixture(tmp_path, monkeypatch)
    (tmp_path / 'gateway-host-claim.json').write_bytes(b'{}')
    with pytest.raises(handoff.HandoffRefused, match='HOST_GATEWAY_ALREADY_CLAIMED'):
        handoff.retained_inputs()


def test_original_timing_limits_accept_exact_edges_only():
    handoff.require_gateway_report(report(), {'campaign_sha256': 'sealed-generated-subject'})


@pytest.mark.parametrize(('field', 'value'), [
    ('first_post_seconds', 120.000001), ('first_post_seconds', True),
    ('first_post_seconds', float('nan')), ('first_post_seconds', -1),
    ('complete_basket_seconds', 300.000001), ('complete_basket_seconds', float('inf')),
    ('complete_basket_seconds', 119), ('campaign_id', 'different'),
    ('campaign_sha256', 'different'), ('original_execute_at', '2026-10-26T13:32:00+00:00'),
    ('gateway_qualified', False), ('book_preserved', False), ('orders', 0), ('legs', True),
    ('native_broker_calls', 1), ('native_broker_calls', False), ('native_broker_calls', 0.0),
    ('live_money_qualified', True), ('production_opening_qualified', True),
])
def test_success_word_cannot_override_failed_native_scope_or_timing(field, value):
    evidence = report()
    evidence[field] = value
    with pytest.raises(handoff.HandoffRefused):
        handoff.require_gateway_report(evidence, {'campaign_sha256': 'sealed-generated-subject'})


def test_frozen_gateway_command_has_no_new_source_or_clock_override():
    host = SimpleNamespace(PRODUCTION_SYSTEM_ID='production-physical-id', IMAGE='exact-image',
                           RUNTIME_COMMIT='original-commit')
    args = handoff.gateway_arguments(host, {'campaign_sha256': 'original-seal'})
    assert args[:3] == ['-B', '/qualification/tools/live_timing_qualification.py', 'gateway']
    assert args[args.index('--expected-system-id') + 1] == handoff.SYSTEM_ID
    assert args[args.index('--campaign-sha256') + 1] == 'original-seal'
    assert args[args.index('--database') + 1].endswith('opening_latency_' + handoff.CAMPAIGN)
    assert not any('debug' in value.lower() or 'override' in value.lower() for value in args)


def fake_preflight(monkeypatch, summary=None):
    events = []
    summary = summary or {'enabled': False, 'killed': True, 'generation': 1,
                          'commands': 0, 'cycles': 0, 'plans': 0}
    def command(args):
        events.append(('command', args))
        return json.dumps(summary)
    host = SimpleNamespace(image_facts=lambda: {'runtime': 'exact'},
        profile=lambda: events.append('profile'),
        check_bundle=lambda *_: events.append('bundle'),
        pg_system=lambda *_: handoff.SYSTEM_ID, command=command)
    request = {'images': {'runtime': 'exact'}, 'bundle': {'original': 'sha'}}
    monkeypatch.setattr(handoff, 'retained_inputs', lambda: (request, {}, {}))
    monkeypatch.setattr(handoff, 'load_reviewed_host', lambda: host)
    return host, events


def test_check_only_reads_owned_private_metadata_and_selects(monkeypatch):
    _host, events = fake_preflight(monkeypatch)
    result = handoff.check()
    assert result['read_only'] is True and result['gateway_consumed'] is False
    assert result['authority_effect'] == 'NONE'
    commands = [item[1] for item in events if isinstance(item, tuple)]
    assert len(commands) == 1
    assert commands[0][:3] == ['docker', 'exec', handoff.PG_ID]
    assert commands[0][-1] == handoff.SUMMARY_SQL
    assert commands[0][-1].startswith('SELECT ')


@pytest.mark.parametrize('field', ['enabled', 'killed', 'generation', 'commands', 'cycles', 'plans'])
def test_nonfresh_or_unfenced_private_database_refuses(monkeypatch, field):
    summary = {'enabled': False, 'killed': True, 'generation': 1, 'commands': 0, 'cycles': 0, 'plans': 0}
    summary[field] = not summary[field] if type(summary[field]) is bool else summary[field] + 1
    fake_preflight(monkeypatch, summary)
    with pytest.raises(handoff.HandoffRefused, match='UNCONSUMED_FENCED_PRIVATE_NAMESPACE'):
        handoff.preflight()


def test_actual_session_guard_falsifier_prevents_claim_or_container_creation(monkeypatch):
    class ReachedMutation(Exception):
        pass
    class Saturday(datetime):
        @classmethod
        def now(cls, _tz):
            return cls(2026, 10, 24, 17, tzinfo=timezone.utc)
    def claimed(*_args):
        raise ReachedMutation
    host = SimpleNamespace(write_new=claimed)
    monkeypatch.setattr(handoff, 'preflight', lambda: (host, {}, {}, {}))
    monkeypatch.setattr(handoff, 'datetime', Saturday)
    with pytest.raises(handoff.HandoffRefused, match='ACTUAL_ELIGIBLE_MARKET_SESSION_REQUIRED'):
        handoff.run()
    source = inspect.getsource(handoff.run)
    needle = "require(eligibility(datetime.now(timezone.utc)) == 'ELIGIBLE_REAL_SESSION',"
    assert needle in source
    broken = source.replace(needle, 'require(True,', 1)
    namespace = {}
    exec(compile(broken, 'private-handoff-clock-guard-mutant', 'exec'), vars(handoff), namespace)
    with pytest.raises(ReachedMutation):
        namespace['run']()


def test_error_output_does_not_disclose_arbitrary_exception_payload(monkeypatch, capsys):
    def broken():
        raise ValueError('secret-do-not-echo')
    monkeypatch.setattr(handoff, 'check', broken)
    assert handoff.main(['check']) == 1
    raw = capsys.readouterr().out
    assert 'secret-do-not-echo' not in raw
    assert json.loads(raw)['failure_code'] == 'HANDOFF_OPERATION_REFUSED'
