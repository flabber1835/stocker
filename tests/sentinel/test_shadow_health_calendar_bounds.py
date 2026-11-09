"""Signed health boundaries match XNYS without rebuilding it in readers."""
from datetime import datetime, timedelta, timezone
import inspect
import json
import subprocess
import sys

import pytest

from sentinel import shadow_health_projection as health
from sentinel.feed import calendar


def projection_for(session):
    return health.Projection(schema_id=health.SCHEMA, config_sha256='a'*64,
        inventory_sha256='b'*64, session=session, record_sha256='c'*64,
        runtime_authority_sha256='d'*64, **health._calendar_bounds(session))


def original_eligibility(session, instant):
    latest=calendar.latest_closed_session(instant)
    if session==latest:
        return dict(service_health='HEALTHY_ATTESTED',target_session=latest)
    if calendar.next_session(session)==latest:
        opened,_closed=calendar.session_window(calendar.next_session(latest))
        if instant<opened.astimezone(timezone.utc):
            return dict(service_health='HEALTHY_WAITING',target_session=latest)
    raise ValueError('original causal boundary')


@pytest.mark.parametrize('session,next_session,end',[
    ('2026-03-06','2026-03-09','2026-03-10T13:30:00+00:00'),
    ('2026-04-02','2026-04-06','2026-04-07T13:30:00+00:00'),
    ('2026-11-27','2026-11-30','2026-12-01T14:30:00+00:00'),
])
def test_bounds_preserve_original_calendar_eligibility(session,next_session,end):
    projection=projection_for(session)
    assert projection.waiting_session==next_session
    assert projection.valid_until==end
    begin,current,finish=map(datetime.fromisoformat,(
        projection.valid_from,projection.current_until,projection.valid_until))
    micro=timedelta(microseconds=1)
    for instant in (begin-micro,begin,begin+micro,current-micro,current,
                    current+micro,finish-micro,finish,finish+micro):
        try:
            expected=original_eligibility(session,instant)
        except ValueError:
            with pytest.raises(ValueError,match='causal'):
                health._temporal_health(projection,instant)
        else:
            assert health._temporal_health(projection,instant)==expected


@pytest.mark.parametrize('change',[
    {'valid_from':'2026-11-27T18:00:00'},
    {'valid_from':'2026-11-27T18:00:00-08:00'},
    {'current_until':'2026-11-27T17:00:00+00:00'},
    {'valid_until':'2026-11-30T20:00:00+00:00'},
    {'waiting_session':'2026-11-27'},
    {'calendar_identity':'unattributed calendar'},
    {'schema_id':'sentinel.shadow-health-projection/1'},
])
def test_invalid_or_legacy_intervals_refuse(change):
    raw=projection_for('2026-11-27').model_dump()
    with pytest.raises(ValueError):
        health.Projection.model_validate(dict(raw,**change))


def test_naive_reader_clock_refuses():
    with pytest.raises(ValueError,match='timezone'):
        health._temporal_health(projection_for('2026-11-27'),datetime(2026,11,28))


def test_cold_reader_does_not_load_heavy_calendar_modules():
    projection=projection_for('2026-11-27')
    script='''import json,sys
from datetime import datetime
from sentinel.shadow_health_projection import Projection,_temporal_health
p=Projection.model_validate(json.loads(sys.argv[1]))
r=_temporal_health(p,datetime.fromisoformat(p.valid_from))
print(json.dumps(dict(result=r,heavy=[name for name in
 ('pandas','numpy','exchange_calendars') if name in sys.modules])))
'''
    result=subprocess.run([sys.executable,'-c',script,
        json.dumps(projection.model_dump())],capture_output=True,text=True,timeout=10)
    assert result.returncode==0,result.stderr
    value=json.loads(result.stdout)
    assert value['heavy']==[]
    assert value['result']==dict(service_health='HEALTHY_ATTESTED',target_session='2026-11-27')


def _assert_future_refused(function,projection):
    before=datetime.fromisoformat(projection.valid_from)-timedelta(microseconds=1)
    try:
        function(projection,before)
    except ValueError:
        return
    raise AssertionError('a future projection was accepted')


def test_lower_time_fence_has_a_failing_falsifier():
    projection=projection_for('2026-11-27')
    _assert_future_refused(health._temporal_health,projection)
    source=inspect.getsource(health._temporal_health)
    weakened=source.replace('if instant < begin or instant >= end:',
        'if instant >= end:')
    assert weakened!=source
    namespace=dict(vars(health))
    exec(weakened,namespace)
    with pytest.raises(AssertionError,match='future projection'):
        _assert_future_refused(namespace['_temporal_health'],projection)
