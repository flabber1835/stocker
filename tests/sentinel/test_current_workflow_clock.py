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
