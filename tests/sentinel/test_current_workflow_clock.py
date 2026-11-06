"""Private market/observation clock phases; real PostgreSQL clocks stay real."""
from datetime import datetime, timedelta, timezone
import inspect

import pytest

from tests.support import current_workflow_clock as module


@pytest.mark.parametrize('offset', [-3600, 3600])
def test_observation_clock_advances_without_rewinding_business_time(monkeypatch, offset):
    wall = [datetime(2026, 10, 26, 17, tzinfo=timezone.utc)]
    class Wall(datetime):
        @classmethod
        def now(cls, tz=None):
            return wall[0].astimezone(tz) if tz else wall[0].replace(tzinfo=None)
    monkeypatch.setattr(module, 'RealDateTime', Wall)
    business = wall[0]+timedelta(seconds=offset)
    clock = module.BusinessClock(business)
    wall[0] += timedelta(seconds=10)
    assert clock.now() == business
    clock.follow_wall()
    start = max(business, wall[0])
    assert clock.now() == start
    wall[0] += timedelta(seconds=7)
    assert clock.now() == start+timedelta(seconds=7)
    assert clock.datetime.now(timezone.utc) == clock.now()
    assert clock.datetime.now() == clock.now().replace(tzinfo=None)


def test_rewinding_the_future_business_clock_has_a_falsifier(monkeypatch):
    source = inspect.getsource(module.BusinessClock.follow_wall)
    import textwrap
    source = textwrap.dedent(source).replace(
        'max(timedelta(0), self.instant-RealDateTime.now(timezone.utc))', 'timedelta(0)')
    namespace = dict(module.__dict__)
    exec(compile(source, 'private-clock-rewind-falsifier', 'exec'), namespace)
    monkeypatch.setattr(module.BusinessClock, 'follow_wall', namespace['follow_wall'])
    with pytest.raises(AssertionError):
        test_observation_clock_advances_without_rewinding_business_time(monkeypatch, 3600)


@pytest.mark.parametrize('parts,decision,effective', [
    ((2026, 11, 6, 13, 0), '2026-11-05', '2026-11-06'),
    ((2026, 11, 6, 14, 30), '2026-11-06', '2026-11-09'),
    ((2026, 11, 6, 20, 52), '2026-11-06', '2026-11-09'),
    ((2026, 11, 6, 21, 6), '2026-11-06', '2026-11-09'),
    ((2026, 11, 7, 16, 0), '2026-11-06', '2026-11-09'),
    ((2026, 11, 9, 20, 52), '2026-11-09', '2026-11-10'),
])
def test_private_market_scenario_keeps_future_open_and_coherent_source_after_close(
        monkeypatch, parts, decision, effective):
    from sentinel.feed import calendar
    wall = [datetime(*parts, tzinfo=timezone.utc)]
    class Wall(datetime):
        @classmethod
        def now(cls, tz=None):
            return wall[0].astimezone(tz) if tz else wall[0].replace(tzinfo=None)
    monkeypatch.setattr(module, 'RealDateTime', Wall)
    clock, source = module.prospective_clock(monkeypatch)
    opened,_ = calendar.session_window(effective)
    assert opened > wall[0]
    assert source == decision == calendar.latest_closed_session(clock.now())
    assert clock.now() == opened-timedelta(minutes=5)
    clock.instant = opened+timedelta(seconds=1)
    wall[0] += timedelta(minutes=20)
    clock.follow_wall()
    assert calendar.latest_closed_session(clock.now()) == source
    assert clock.now() >= opened+timedelta(seconds=1)


def test_selecting_a_past_open_breaks_the_close_boundary_oracle(monkeypatch):
    import textwrap
    source = textwrap.dedent(inspect.getsource(module.prospective_clock))
    guard = ('    if opened <= wall:\n'
             '        decision = effective\n'
             '        effective = calendar.next_session(decision)\n'
             '        opened,_ = calendar.session_window(effective)\n')
    assert source.count(guard) == 1
    namespace = {}
    exec(compile(source.replace(guard, ''), 'past-private-opening', 'exec'),
         module.__dict__, namespace)
    monkeypatch.setattr(module, 'prospective_clock', namespace['prospective_clock'])
    with pytest.raises(AssertionError):
        test_private_market_scenario_keeps_future_open_and_coherent_source_after_close(
            monkeypatch, (2026, 11, 6, 20, 52), '2026-11-06', '2026-11-09')


def test_private_collector_receives_parent_market_clock_without_changing_wall_deadlines(monkeypatch):
    from sentinel.feed import calendar
    from sentinel.panel import projection_service, sources
    from tests.support import current_workflow_run as run
    import time
    offset = timedelta(days=2)
    observed = {}
    monotonic = time.monotonic
    def collect(*args):
        observed.update(market=calendar._dt.datetime.now(timezone.utc),
                        wall=projection_service.datetime.now(timezone.utc),
                        observation=sources.datetime.now(timezone.utc), args=args)
        assert time.monotonic is monotonic
        return {'outcome': 'fixture clock observed'}
    monkeypatch.setattr(projection_service, 'collect_result', collect)
    answer = run._current_operational_collection('isolated', 'owner', 'state', 'instance',
        'private-roots', 'private-reference', 'a'*64, offset, False)
    assert answer == {'outcome': 'fixture clock observed'}
    assert abs((observed['market']-observed['wall']-offset).total_seconds()) < 1
    assert abs((observed['observation']-observed['wall']).total_seconds()) < 1
    assert observed['args'] == ('isolated', 'owner', 'state', 'instance', False)


def test_omitting_the_private_collector_clock_breaks_its_handoff_oracle(monkeypatch):
    import textwrap
    from tests.support import current_workflow_run as run
    source = textwrap.dedent(inspect.getsource(run._current_operational_collection))
    guard = '        private_clock.install(inputs)\n'
    assert source.count(guard) == 1
    namespace = {}
    exec(compile(source.replace(guard, ''), 'missing-private-collector-clock', 'exec'),
         run.__dict__, namespace)
    monkeypatch.setattr(run, '_current_operational_collection', namespace['_current_operational_collection'])
    with pytest.raises(AssertionError):
        test_private_collector_receives_parent_market_clock_without_changing_wall_deadlines(monkeypatch)


def test_private_market_time_does_not_stamp_financial_observations(monkeypatch):
    from sentinel.panel import sources, read_projection, verification_service
    clock = module.BusinessClock(datetime.now(timezone.utc)+timedelta(days=2))
    clock.install(monkeypatch)
    for observed in (sources, read_projection, verification_service):
        assert abs((observed.datetime.now(timezone.utc)-datetime.now(timezone.utc)).total_seconds()) < 1


def test_injecting_market_time_into_observations_breaks_the_clock_domain_oracle(monkeypatch):
    import textwrap
    source = textwrap.dedent(inspect.getsource(module.BusinessClock.install))
    boundary = "        'sentinel.execution.alpaca', 'sentinel.execution.fill_notifications',\n"
    assert source.count(boundary) == 1
    namespace = {}
    exec(compile(source.replace(boundary, boundary+"        'sentinel.panel.sources',\n"),
                 'future-financial-observation', 'exec'), module.__dict__, namespace)
    monkeypatch.setattr(module.BusinessClock, 'install', namespace['install'])
    with pytest.raises(AssertionError):
        test_private_market_time_does_not_stamp_financial_observations(monkeypatch)
