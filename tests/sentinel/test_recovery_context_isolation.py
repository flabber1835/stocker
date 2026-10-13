"""Admitted source upgrades recover without overwriting the requested target."""
from datetime import timedelta

import psycopg
import pytest

from sentinel import rolling_recovery as recovery,rolling_runtime as runtime
from sentinel import rolling_checkpoint as origin,rolling_daily_checkpoint as daily
from sentinel import rolling_initialization as initial,runtime_admission as admission,shadow_runtime
from sentinel.feed import calendar,operational_snapshot as snapshots,rolling_go_inputs as inputs
from sentinel.feed.rolling_contract import PriceWindow,digest
from tests.sentinel.test_rolling_retained_runtime_activation import (
    conn,pg,executable,_start,OBS)  # noqa: F401
from tests.sentinel.test_alpaca_daily_formation import provider  # noqa: F401


@pytest.fixture
def ready(provider):
    return provider[1]()


@pytest.mark.parametrize('executable',['economic'],indirect=True)
@pytest.mark.parametrize('dated_input',[False,True])
def test_admitted_target_survives_preflight_and_restart(
        conn,ready,executable,provider,monkeypatch,dated_input):
    first=_start(conn,executable)
    original=origin.read(conn).model_dump(by_alias=True)
    records=dict(conn.execute('SELECT cursor_name,state FROM sentinel_processed_sessions').fetchall())
    conn.rollback()
    _,current,manifest=executable
    admitted=admission.admit(conn,context=current,manifest=manifest)
    assert isinstance(admitted,admission.EconomicAdmission) and admitted.authority_effect=='NONE'
    assert digest(current['strategy'])!=digest(original['strategy_identity'])
    monkeypatch.setattr(shadow_runtime,'_validated_runtime_identity',lambda **kw:current['runtime'])
    monkeypatch.setattr(shadow_runtime,'_strategy',lambda:(current['controller'],current['strategy']))
    monkeypatch.setattr(inputs,'production_strategy',lambda:(current['controller'],current['strategy']))
    from sentinel import strategy
    monkeypatch.setattr(strategy,'production_strategy',lambda:(current['controller'],current['strategy']))
    from tests.sentinel import test_alpaca_daily_formation as provider_fixture
    monkeypatch.setattr(provider_fixture,'production_strategy',lambda:(current['controller'],current['strategy']))
    missing=calendar.next_session(first.session)
    prices,publish=provider
    prices.window=PriceWindow.through(missing)
    if dated_input:
        publish()
        monkeypatch.setattr(shadow_runtime,'_validated_runtime_identity',lambda **kw:current['runtime'])
    opened,_=calendar.session_window(calendar.next_session(missing))
    monkeypatch.setattr(initial,'_now',lambda c:opened+timedelta(minutes=20))
    conn.rollback()
    result=recovery.advance_one(conn,through=missing,observation_id=OBS,starting_cash=50000)
    assert result.session==missing and result.verification_scope=='ROLLING_RECONSTRUCTION_ONLY'
    assert result.state.strategy_identity==current['strategy']
    checkpoint=daily.read(conn)
    assert checkpoint.input_value['strategy_transition']['prior_state_sha256']==first.state.state_hash
    assert origin.read(conn).model_dump(by_alias=True)==original
    preserved=dict(conn.execute('SELECT cursor_name,state FROM sentinel_processed_sessions').fetchall())
    assert all(preserved[key]==value for key,value in records.items())
    conn.rollback()
    with snapshots.pinned(conn) as (pub,binding):
        from sentinel.feed import rolling_jobs
        assert rolling_jobs.status(conn,binding['job_id'])['request']['strategy_sha256']==digest(current['strategy'])
        if not dated_input:
            assert pub.evidence['operational_recovery']['historical_availability_claim'] is False
            assert pub.evidence['operational_recovery']['broker_authority'] is False
    monkeypatch.setattr(initial,'initialize',lambda *a,**kw:pytest.fail('book reformed'))
    with psycopg.connect(conn.info.dsn) as restarted:
        repeated=recovery.advance_one(restarted,through=missing,observation_id=OBS,starting_cash=50000)
    assert repeated.state.state_hash==result.state.state_hash and not repeated.appended
    assert repeated.runtime_authority_sha256==result.runtime_authority_sha256
    assert origin.read(conn).model_dump(by_alias=True)==original
    assert conn.execute('SELECT COUNT(*) FROM sentinel_commands').fetchone()[0]==0
    conn.rollback()
