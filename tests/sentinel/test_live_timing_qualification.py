"""Original-clock, campaign/isolation and truthful qualification falsifiers.

These fast contract tests do not claim gateway or native market qualification.
The actual campaign must run separately in the named exact-image resources.
"""
from contextlib import nullcontext
from datetime import datetime, timedelta, timezone
import inspect
from types import SimpleNamespace

import pytest

from tools import live_timing_qualification as timing

UTC = timezone.utc
EXECUTE = datetime(2026, 10, 26, 13, 31, tzinfo=UTC)
CAMPAIGN = 'a' * 32


def clock(*, delay=0, sampled=1000):
    values = [sampled]
    result = timing.OriginalExecuteClock(EXECUTE, now=EXECUTE + timedelta(seconds=delay),
                                         monotonic=lambda: values[0])
    return result, values


def test_original_execute_clock_includes_late_entry_and_all_prepare_time():
    gate, sampled = clock(delay=35)
    assert gate.elapsed() == 35
    sampled[0] += 86  # PREPARE has not submitted an order: original total 121.
    with pytest.raises(timing.TimingRefused, match='FIRST_POST'):
        gate.check()


def test_preparation_deadline_falsifier_rejects_reset_to_callback_entry():
    source = inspect.getsource(timing.OriginalExecuteClock)
    assert 'self.started = sampled - delay' in source
    broken = source.replace('self.started = sampled - delay', 'self.started = sampled')
    namespace = {}
    exec(compile(broken, 'private-original-clock-reset-mutant', 'exec'), vars(timing), namespace)
    sampled = [1000]
    gate = namespace['OriginalExecuteClock'](EXECUTE, now=EXECUTE + timedelta(seconds=35),
                                             monotonic=lambda: sampled[0])
    sampled[0] += 86
    # The same concrete observation incorrectly succeeds when the origin is
    # reset. This is the failure that the ordinary regression above detects.
    assert gate.check() == 86
    assert gate.elapsed() != 121


def test_deadline_edges_are_inclusive_and_completion_includes_terminal_work():
    gate, sampled = clock()
    sampled[0] += 120
    assert gate.check(120) == 120
    sampled[0] += 180
    assert gate.check(120, complete=True) == 300
    sampled[0] += .0001  # Durable final transition is still inside this clock.
    with pytest.raises(timing.TimingRefused, match='COMPLETE_BASKET'):
        gate.check(120, complete=True)


@pytest.mark.parametrize('first', [None, 120.001, -1, float('nan'), float('inf'), True, '1'])
def test_incomplete_or_late_first_post_cannot_complete(first):
    gate, sampled = clock()
    sampled[0] += 150
    with pytest.raises(timing.TimingRefused, match='FIRST_POST'):
        gate.check(first, complete=True)


def test_first_post_cannot_be_after_current_elapsed_time():
    gate, sampled = clock()
    sampled[0] += 20
    with pytest.raises(timing.TimingRefused, match='FIRST_POST'):
        gate.check(21)


def test_future_due_time_and_regressed_monotonic_clock_refuse():
    with pytest.raises(timing.TimingRefused, match='NOT_YET_DUE'):
        timing.OriginalExecuteClock(EXECUTE, now=EXECUTE - timedelta(seconds=1), monotonic=lambda: 1)
    gate, sampled = clock()
    sampled[0] -= 1
    with pytest.raises(timing.TimingRefused, match='REGRESSED'):
        gate.elapsed()


@pytest.mark.parametrize('value', [float('nan'), float('inf')])
def test_nonfinite_monotonic_sample_refuses(value):
    with pytest.raises(timing.TimingRefused, match='INVALID'):
        timing.OriginalExecuteClock(EXECUTE, now=EXECUTE, monotonic=lambda: value)


def test_market_assessment_preserves_real_saturday_and_monday_calendars():
    from sentinel.automation.model import AutomationConfig
    config = AutomationConfig()
    saturday, schedule = timing.market_status('2026-10-23', config,
        now=datetime(2026, 10, 24, 16, tzinfo=UTC))
    assert saturday['status'] == 'BLOCKED_MARKET_SESSION'
    assert schedule.execute_at == EXECUTE
    assert saturday['actual_source_frontier'] == '2026-10-23'
    armed, _ = timing.market_status('2026-10-23', config, now=EXECUTE - timedelta(minutes=9))
    assert armed['status'] == 'ELIGIBLE_REAL_SESSION'
    open_status, _ = timing.market_status('2026-10-23', config, now=EXECUTE)
    assert open_status['status'] == 'ELIGIBLE_REAL_SESSION'
    expired, _ = timing.market_status('2026-10-23', config, now=EXECUTE + timedelta(seconds=540))
    assert expired['status'] == 'BLOCKED_MARKET_SESSION'
    stale_source, _ = timing.market_status('2026-10-22', config, now=EXECUTE)
    assert stale_source['status'] == 'BLOCKED_MARKET_SESSION'


def test_exact_private_database_address_prevents_accidental_connection(monkeypatch):
    import psycopg
    monkeypatch.setattr(psycopg, 'connect', lambda *_args, **_kwargs: pytest.fail('must refuse before connection'))
    args = SimpleNamespace(database='postgresql://postgres@127.0.0.1:5432/sentinel', campaign_id=CAMPAIGN)
    with pytest.raises(timing.TimingRefused, match='EXACT_PRIVATE_LOOPBACK'):
        timing.connect(args)


@pytest.mark.parametrize('database', [
    'postgresql://postgres@localhost:5432/opening_latency_' + CAMPAIGN,
    'postgresql://postgres@127.0.0.1:5432/opening_latency_' + CAMPAIGN + '?options=-c%20foo=bar',
    'postgresql://postgres:secret@127.0.0.1:5432/opening_latency_' + CAMPAIGN,
    'postgresql://postgres@127.0.0.1:5432/opening_latency_' + 'b' * 32,
])
def test_private_address_cannot_alias_retarget_or_supply_options(database):
    with pytest.raises(timing.TimingRefused, match='EXACT_PRIVATE_LOOPBACK'):
        timing.require_database_address(database, CAMPAIGN)


def test_private_database_must_have_a_distinct_physical_identity(monkeypatch):
    import psycopg
    monkeypatch.setattr(psycopg, 'connect', lambda *_args, **_kwargs: pytest.fail('must refuse before connection'))
    args = SimpleNamespace(database='postgresql://postgres@127.0.0.1:5432/opening_latency_' + CAMPAIGN,
        campaign_id=CAMPAIGN, expected_system_id='7691913275518591014', production_system_id='7691913275518591014')
    with pytest.raises(timing.TimingRefused, match='DISTINCT_PHYSICAL'):
        timing.connect(args)


def cgroup(tmp_path, *, cpu='100000 100000', memory=str(timing.MEMORY)):
    (tmp_path / 'cpu.max').write_text(cpu)
    (tmp_path / 'memory.max').write_text(memory)
    return tmp_path


def test_resource_envelope_and_exact_runtime_import_are_mandatory(tmp_path):
    group = cgroup(tmp_path)
    measured = timing.require_environment({}, sentinel_file='/app/sentinel/__init__.py', cgroup=group)
    assert measured == {'cpu_quota': 100000, 'cpu_period': 100000, 'memory_limit_bytes': timing.MEMORY}
    with pytest.raises(timing.TimingRefused, match='EXACT_IMAGE_RUNTIME'):
        timing.require_environment({}, sentinel_file='/qualification/sentinel/__init__.py', cgroup=group)


@pytest.mark.parametrize('cpu,memory', [('max 100000', str(timing.MEMORY)),
    ('200000 100000', str(timing.MEMORY)), ('100000 100000', str(timing.MEMORY * 2)),
    ('100000 100000', 'max')])
def test_resources_cannot_be_loosened(tmp_path, cpu, memory):
    with pytest.raises(timing.TimingRefused, match='RESOURCE_ENVELOPE'):
        timing.require_environment({}, sentinel_file='/app/sentinel/__init__.py',
                                   cgroup=cgroup(tmp_path, cpu=cpu, memory=memory))


@pytest.mark.parametrize('key', ['ALPACA_API_KEY', 'OPENFIGI_API_KEY', 'NDL_API_KEY',
    'REHEARSAL_PRODUCTION_DATABASE_URL', 'SENTINEL_PAPER_DEBUG_WINDOW'])
def test_provider_or_debug_environment_refuses_without_reading_runtime(tmp_path, key):
    with pytest.raises(timing.TimingRefused, match='PROVIDER_CREDENTIAL_OR_DEBUG'):
        timing.require_environment({key: 'forbidden'}, sentinel_file='/app/sentinel/__init__.py',
                                   cgroup=cgroup(tmp_path))


def test_single_use_claim_preserves_original_bytes(tmp_path):
    claim = tmp_path / 'gateway-claim.json'
    timing.write_new(claim, {'campaign': CAMPAIGN, 'original': 1})
    before = claim.read_bytes()
    with pytest.raises(FileExistsError):
        timing.write_new(claim, {'campaign': CAMPAIGN, 'original': 2})
    assert claim.read_bytes() == before


def test_documents_reject_duplicates_and_noncanonical_bytes(tmp_path):
    path = tmp_path / 'manifest.json'
    path.write_text('{"a":1,"a":2}\n')
    with pytest.raises(timing.TimingRefused, match='DUPLICATE'):
        timing.read_object(path)
    path.write_text('{ "a": 1 }\n')
    with pytest.raises(timing.TimingRefused, match='CANONICAL'):
        timing.read_object(path)


def test_scheduler_accepts_exact_current_profile_without_old_lease_tuple(tmp_path):
    from sentinel.automation.model import AutomationConfig
    config = AutomationConfig(lease_seconds=45, heartbeat_seconds=10, control_poll_seconds=10)
    document = {'schema': 'sentinel.attended-scheduler-profile/1',
        'scheduler': config.model_dump(mode='json', exclude_none=True), 'config_sha256': config.fingerprint}
    path = tmp_path / 'scheduler.json'
    timing.write_new(path, document)
    actual, parsed = timing.scheduler_document(path)
    assert actual == document and parsed == config


def test_scheduler_fingerprint_and_ordinary_cutoff_cannot_be_changed(tmp_path):
    from sentinel.automation.model import AutomationConfig
    config = AutomationConfig(maximum_execution_lateness_seconds=600)
    path = tmp_path / 'scheduler.json'
    timing.write_new(path, {'schema': 'sentinel.attended-scheduler-profile/1',
        'scheduler': config.model_dump(mode='json'), 'config_sha256': config.fingerprint})
    with pytest.raises(timing.TimingRefused, match='ORDINARY_OPENING_POLICY'):
        timing.scheduler_document(path)


def test_external_campaign_seal_rejects_any_relabelled_campaign(tmp_path):
    timing.write_new(tmp_path / 'campaign.json', {'schema': timing.SCHEMA, 'campaign_id': CAMPAIGN})
    timing.write_new(tmp_path / 'private-context.json', {'environment': {}})
    args = SimpleNamespace(campaign_dir=tmp_path, campaign_sha256='0' * 64)
    with pytest.raises(timing.TimingRefused, match='EXTERNAL_CAMPAIGN_SEAL'):
        timing.load_campaign(args, {}, {})


def test_generated_source_names_real_426_session_shape_and_coverage_limitations():
    from tests.support.live_timing_campaign import Source
    source = Source('2026-10-23', assets=5200)
    assert source.description['assets'] == 5200
    assert source.description['sessions'] == 426
    assert source.description['bar_count'] == 2_215_200
    assert source.description['last_session'] == '2026-10-23'
    assert 'no native' in source.description['limitations']


@pytest.mark.parametrize('material', [b'x' * (timing.MAX_DOCUMENT_BYTES + 1),
    b'{"value":' + b'[' * (timing.MAX_DOCUMENT_DEPTH + 1) + b'0' + b']' * (timing.MAX_DOCUMENT_DEPTH + 1) + b'}\n'])
def test_documents_are_bounded_before_recursive_json_decode(tmp_path, material):
    path = tmp_path / 'manifest.json'
    path.write_bytes(material)
    with pytest.raises(timing.TimingRefused, match='DOCUMENT_(SIZE|DEPTH)_LIMIT'):
        timing.read_object(path)


@pytest.mark.parametrize('material', [b'{\n', b'{"value": "\xff"}\n', b'[[[})\n'])
def test_malformed_documents_have_typed_refusals(tmp_path, material):
    path = tmp_path / 'manifest.json'
    path.write_bytes(material)
    with pytest.raises(timing.TimingRefused, match='INVALID_JSON'):
        timing.read_object(path)


def test_brackets_and_escaped_quotes_inside_strings_do_not_consume_depth(tmp_path):
    path = tmp_path / 'manifest.json'
    value = {'value': '[' * 100 + '"\\' + ']' * 100}
    timing.write_new(path, value)
    assert timing.read_object(path) == value


def orchestrated(run=timing.run_original_clock, *, entry_delay=0, prepare_seconds=10,
                 execution_seconds=40, commit_seconds=15, first_post=True):
    sampled, events = [1000], []
    provider = SimpleNamespace(started=None, first_order_seconds=None)
    def record(gate):
        events.append(('ORIGIN', provider.started, gate.elapsed()))
    def prepare():
        events.append(('PREPARE', provider.started))
        sampled[0] += prepare_seconds
        return 'durable-plan'
    def execute_recover(plan):
        assert plan == 'durable-plan'
        if first_post:
            provider.first_order_seconds = sampled[0] - provider.started
        events.append(('EXECUTE_AND_RECOVER', provider.started))
        sampled[0] += execution_seconds
        return 'positively-recovered-basket'
    def verify_commit(outcome):
        assert outcome == 'positively-recovered-basket'
        events.append(('DURABLE_SUCCEEDED', provider.started))
        sampled[0] += commit_seconds
        return {'basket': 'verified'}
    result = run(EXECUTE, provider=provider, prepare=prepare, execute_recover=execute_recover,
        verify_commit=verify_commit, record_origin=record,
        now=lambda: EXECUTE + timedelta(seconds=entry_delay), monotonic=lambda: sampled[0])
    return result, events


def test_measured_callbacks_and_terminal_commit_share_original_origin():
    (verified, elapsed), events = orchestrated(entry_delay=5)
    assert verified == {'basket': 'verified'} and elapsed == 70
    assert [event[0] for event in events] == ['ORIGIN', 'PREPARE', 'EXECUTE_AND_RECOVER', 'DURABLE_SUCCEEDED']
    assert all(event[1] == 995 for event in events)
    assert events[0][2] == 5


def test_measured_prepare_and_late_entry_cannot_be_excluded_from_first_post_deadline():
    with pytest.raises(timing.TimingRefused, match='FIRST_POST'):
        orchestrated(entry_delay=35, prepare_seconds=86)


def test_measured_durable_terminal_write_cannot_be_excluded_from_completion_deadline():
    with pytest.raises(timing.TimingRefused, match='COMPLETE_BASKET'):
        orchestrated(prepare_seconds=10, execution_seconds=40, commit_seconds=251)


def test_measured_orchestration_does_not_accept_a_no_order_success():
    with pytest.raises(timing.TimingRefused, match='FIRST_POST'):
        orchestrated(first_post=False)


def test_removed_final_clock_check_is_detected_by_durable_commit_observation():
    source = inspect.getsource(timing.run_original_clock)
    needle = 'elapsed = clock.check(provider.first_order_seconds, complete=True)'
    assert needle in source
    broken = source.replace(needle, 'elapsed = clock.elapsed()')
    namespace = {}
    exec(compile(broken, 'private-removed-terminal-timing-guard', 'exec'), vars(timing), namespace)
    # The same concrete 301-second durable completion is incorrectly accepted
    # by the mutant. The ordinary contract above detects the missing guard.
    (verified, elapsed), _events = orchestrated(namespace['run_original_clock'],
        prepare_seconds=10, execution_seconds=40, commit_seconds=251)
    assert verified == {'basket': 'verified'} and elapsed == 301


def test_nonconsuming_weekend_status_never_writes_claim_or_runs_gateway(tmp_path, monkeypatch):
    from sentinel.automation.model import AutomationConfig
    config = AutomationConfig()
    saturday, actual_timing = timing.market_status('2026-10-23', config,
        now=datetime(2026, 10, 24, 16, tzinfo=UTC))
    assert saturday['status'] == 'BLOCKED_MARKET_SESSION'
    monkeypatch.setattr(timing, 'require_environment', lambda: {})
    monkeypatch.setattr(timing, 'scheduler_document', lambda _path: ({}, config))
    monkeypatch.setattr(timing, 'load_campaign', lambda *_args: ({'source_frontier': '2026-10-23',
        'runtime_identity_sha256': 'private-runtime'}, {'environment': {}}))
    monkeypatch.setattr(timing, '_environment', lambda *_args, **_kwargs: nullcontext())
    monkeypatch.setattr(timing, '_identity', lambda: {'identity_hash': 'private-runtime'})
    monkeypatch.setattr(timing, 'market_status', lambda *_args, **_kwargs: (saturday, actual_timing))
    monkeypatch.setattr(timing, 'write_new', lambda *_args, **_kwargs: pytest.fail('status must not consume or write'))
    monkeypatch.setattr(timing, 'gateway', lambda *_args, **_kwargs: pytest.fail('weekend status cannot execute'))
    argv = ['status', '--campaign-dir', str(tmp_path), '--campaign-id', CAMPAIGN,
        '--database', 'postgresql://postgres@127.0.0.1:5432/opening_latency_' + CAMPAIGN,
        '--expected-system-id', '123456789', '--production-system-id', '7691913275518591014',
        '--runtime-image-digest', 'sha256:' + 'b' * 64, '--commit', 'a' * 40,
        '--scheduler-profile', str(tmp_path / 'scheduler.json'), '--campaign-sha256', 'c' * 64]
    assert timing.main(argv) == 0
    assert timing.main(argv) == 0
    assert list(tmp_path.iterdir()) == []
