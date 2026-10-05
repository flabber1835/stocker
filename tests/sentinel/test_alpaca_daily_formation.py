"""Typed provider inputs through canonical formation and durable continuation."""
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path

import pytest

from sentinel import schema, shadow_runtime
from sentinel import rolling_initialization as init, rolling_daily as daily
from sentinel.core import formation_preview, window_features
from sentinel.feed import calendar, operational_snapshot as op, rolling_publisher, rolling_builder
from sentinel.feed.alpaca_source import AlpacaSource, _bounds
from sentinel.feed.alpaca_transport import ASSETS, ACTION_URL, BAR_URL
from sentinel.feed.rolling_contract import CurrentFormationWindow, PriceWindow, digest
from sentinel.strategy import production_strategy
from tests.sentinel.test_alpaca_operational_snapshot import FakeClassifier
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg  # noqa: F401

OBS = 'alpaca-provider-continuation'


class Prices:
    def __init__(self):
        self.window = CurrentFormationWindow.through('2026-09-14')
        self.origin = str(self.window.start)
        self.split = None
        self.unsupported = False
        self.admitted_subject = None

    def get(self, endpoint, params):
        assert endpoint == ASSETS
        return [{'id':f'uuid-{i:02}', 'symbol':f'T{i:02}', 'name':f'Company {i}',
            'class':'us_equity','status':'active','tradable':True,'exchange':'NASDAQ'}
            for i in range(25)], {'observed_at':'2026-09-15T00:00:00+00:00'}

    def pages(self, endpoint, params, *, key):
        proof = {'observed_at':'2026-09-15T00:00:00+00:00'}
        if endpoint == ACTION_URL:
            records = []
            if self.split:
                symbol, day = self.split
                records = [{'id':'split', 'symbol':symbol,'process_date':day,
                    'ex_date':day,'old_rate':1,'new_rate':2}]
            yield {'spin_offs' if self.unsupported else 'forward_splits':records}, proof
            return
        assert endpoint == BAR_URL
        lo, hi = params['start'][:10], params['end'][:10]
        index = {day:i for i,day in enumerate(calendar.sessions_in_range(self.origin,str(self.window.end)))}
        result = {}
        for symbol in params['symbols'].split(','):
            rows = []
            for day in map(str,self.window.sessions):
                if not lo <= day <= hi:
                    continue
                price = 100 + index[day]*.2 + (int(symbol[1:])*.03 if symbol.startswith('T') else 0)
                event = self.split and symbol == self.split[0] and not self.unsupported
                if event and (day >= self.split[1] or params['adjustment'] == 'split'):
                    price /= 2
                stamp = datetime.fromisoformat(_bounds(day,day)[0]).astimezone(timezone.utc).isoformat()
                rows.append({'t':stamp,'o':price,'c':price,'v':1_000_000})
            result[symbol] = rows
        yield result, proof


@pytest.fixture
def provider(conn,monkeypatch):
    schema.ensure_schema(conn)
    prices = Prices()
    classifier = FakeClassifier()
    monkeypatch.setattr(rolling_publisher,'_operational_source',
        lambda window,conn,lease,**kw:AlpacaSource(window,conn,lease,client=prices,
            classifier=classifier,verify_during_coverage=kw['verify_during_coverage']))
    monkeypatch.setattr(rolling_builder,'MIN_ADMITTED_COMMON_STOCKS', 20)
    monkeypatch.setattr(calendar,'latest_closed_session',lambda now=None:str(prices.window.end))
    def now():
        return datetime.fromisoformat(str(prices.window.end)).replace(tzinfo=timezone.utc)+timedelta(days=1,hours=4)
    monkeypatch.setattr(op,'_now',now)
    monkeypatch.setattr(init,'_now',lambda conn:now())
    from sentinel.feed import alpaca_source
    monkeypatch.setattr(alpaca_source,'_today',lambda:now().date())
    def publish():
        _, strategy = production_strategy()
        job = op.enqueue(conn,strategy_sha256=digest(strategy),dependencies_sha256=digest('provider daily fixture'))
        conn.commit()
        binding = op.prepare(conn,job)
        with op.pinned(conn) as (pub,_):
            subject = shadow_runtime._data_publication_subject_sha256(pub,pub.window_end)
        prices.admitted_subject = prices.admitted_subject or subject
        monkeypatch.setattr(shadow_runtime,'_validated_runtime_identity',lambda **kw:{
            'schema':'test-reviewed-runtime/1','validated_data_publication_sha256':prices.admitted_subject})
        return binding
    return prices,publish


def test_full_formation_chain_and_frontier_match_unchanged_loader(conn,provider,monkeypatch, capfd):
    from sentinel.core.formation_inputs import FormationInputs
    prices,publish = provider
    binding = publish()
    controller,strategy = production_strategy()
    with op.pinned(conn) as (pub,_):
        cached = FormationInputs(conn,binding,pub)
        actual = formation_preview.run(cached,capital=50_000,strategy=strategy,data_version=pub.version)
        uncached = FormationInputs(conn,binding,pub)
        uncached.features.load = lambda **kw:window_features.load(conn,refs=uncached.refs,publication=pub,**kw)
        expected = formation_preview.run(uncached,capital=50_000,strategy=strategy,data_version=pub.version)
    assert actual[0].to_dict() == expected[0].to_dict()
    assert actual[1:] == expected[1:]
    assert cached.features.rows_read == 426*25
    root = Path(os.environ.get('SENTINEL_REPO_ROOT') or Path(__file__).resolve().parents[2])
    monkeypatch.syspath_prepend(str(root/'scripts'))
    import sentinel_go_feed_progress
    events = sentinel_go_feed_progress.collect(capfd.readouterr().err)
    formation = [event for event in events if event['stage'] == 'historical_formation']
    assert [event['sessions'] for event in formation] == list(range(127)) * 2
    assert formation[126]['status'] == formation[-1]['status'] == 'completed'


def test_old_alpaca_normalization_requires_fresh_acquisition(conn, provider, monkeypatch):
    from sentinel.feed import rolling_go_inputs
    from sentinel.core import rolling_inputs

    prices, publish = provider
    current = rolling_builder.ALPACA_NORMALIZATION
    old = 'sentinel.alpaca-openfigi-dividend-current-window/1'
    assert current != old
    monkeypatch.setattr(rolling_builder, 'ALPACA_NORMALIZATION', old)
    monkeypatch.setattr(rolling_inputs, 'ALPACA_NORMALIZATION', old)
    publish()
    monkeypatch.setattr(rolling_builder, 'ALPACA_NORMALIZATION', current)
    monkeypatch.setattr(rolling_inputs, 'ALPACA_NORMALIZATION', current)

    def acquire_again(*_a, **_k):
        raise ConnectionError('fresh acquisition required')

    monkeypatch.setattr(op, 'enqueue', acquire_again)
    with pytest.raises(ConnectionError, match='fresh acquisition required'):
        rolling_go_inputs.prepare(conn, target_session=str(prices.window.end))
    assert conn.execute("SELECT COUNT(*) FROM sentinel_corpus_publications").fetchone()[0] == 1


def test_held_split_daily_restart_and_repeat_change_shares_once(conn,provider):
    prices,publish = provider
    publish()
    before = init.initialize(conn,observation_id=OBS,starting_cash=50_000)
    key,episode = next(iter(before.state.wealth_core['episodes'].items()))
    day = calendar.next_session(before.state.last_processed_session)
    prices.window = PriceWindow.through(day)
    prices.split = (episode['ticker'],day)
    publish()
    result = daily.advance(conn,observation_id=OBS,starting_cash=50_000)
    current = result.state.wealth_core['episodes'][key]
    assert current['current_shares'] == episode['current_shares']*2
    assert not any(p['security_id'] == episode['security_id'] for p in result.state.pending)
    conn.commit()
    assert daily.resume(conn,observation_id=OBS,starting_cash=50_000).state.state_hash == result.state.state_hash
    assert not daily.advance(conn,observation_id=OBS,starting_cash=50_000).appended


def test_unsupported_held_event_refuses_without_mutating_book(conn,provider):
    prices,publish = provider
    publish()
    before = init.initialize(conn,observation_id=OBS,starting_cash=50_000)
    episode = next(iter(before.state.wealth_core['episodes'].values()))
    day = calendar.next_session(before.state.last_processed_session)
    prices.window = PriceWindow.through(day)
    prices.split,prices.unsupported = (episode['ticker'],day),True
    publish()
    from sentinel.core.rolling_reader import RollingReaderRefused
    with pytest.raises((ValueError,RollingReaderRefused),match='ANCHOR'):
        daily.advance(conn,observation_id=OBS,starting_cash=50_000)
    conn.rollback()
    from sentinel import rolling_daily_checkpoint
    _,_,restored = rolling_daily_checkpoint.load(conn,init._context(OBS,50_000))
    assert restored.state.state_hash == before.state.state_hash


def test_operational_shadow_worker_publishes_next_day_recovers_and_never_replays(
        conn, provider, monkeypatch, capsys):
    from decimal import Decimal
    from sentinel import shadow_worker, shadow_service, shadow_recovery, rolling_runtime
    from sentinel.feed import ingest, rolling_store, rolling_jobs
    from sentinel.feed.alpaca_transport import AlpacaTransportUnavailable

    prices, publish = provider
    publish()
    config = shadow_service.ShadowServiceConfig(
        conn.info.dsn, OBS, Decimal(50000), shadow_runtime.SHADOW_PUBLICATION_TIMING_POLICY, 5, True)
    monkeypatch.setattr(shadow_worker.ShadowServiceConfig, "from_env", lambda: config)
    actual_advance = shadow_recovery.advance_once
    monkeypatch.setattr(shadow_worker, "advance_once",
                        lambda value: actual_advance(value, now=init._now(conn)))
    monkeypatch.setattr(ingest, "daily", lambda *_a, **_k: pytest.fail("legacy Sharadar daily reached"))
    assert shadow_worker.main() == 0
    first = rolling_runtime.status(conn, observation_id=OBS, starting_cash=50000)
    assert first.shadow_verdict == "SHADOW_GO" and first.verification == "VERIFIED"
    assert first.state.wealth_core["episodes"]
    conn.rollback()

    prices.window = PriceWindow.through(calendar.next_session(first.session))
    original_pages = prices.pages
    def interrupted(*_a, **_k):
        raise AlpacaTransportUnavailable("daily source temporarily unavailable")
    monkeypatch.setattr(prices, "pages", interrupted)
    assert shadow_worker.main() == shadow_worker.EXIT_AVAILABILITY
    assert "AVAILABILITY:" in capsys.readouterr().err
    assert conn.execute("SELECT count(*) FROM sentinel_corpus_publications").fetchone()[0] == 1
    job = str(conn.execute("SELECT job_id FROM sentinel_snapshot_jobs ORDER BY created_at DESC LIMIT 1").fetchone()[0])
    assert rolling_jobs.status(conn, job)["state"] == "RETRY_WAIT"
    conn.rollback()

    monkeypatch.setattr(prices, "pages", original_pages)
    conn.execute("UPDATE sentinel_snapshot_jobs SET next_retry=clock_timestamp() WHERE job_id=%s", (job,))
    conn.commit()
    assert shadow_worker.main() == 0
    second = rolling_runtime.status(conn, observation_id=OBS, starting_cash=50000)
    assert second.session == str(prices.window.end) and second.verification == "VERIFIED"
    assert second.state.state_hash != first.state.state_hash
    binding = op.require_alpaca_openfigi(conn, op._current(conn))
    assert len(rolling_store.manifest(conn, binding["candidate_id"]).window.sessions) == 300
    conn.rollback()
    before = conn.execute("SELECT count(*) FROM sentinel_corpus_publications").fetchone()[0]
    conn.rollback()
    monkeypatch.setattr(prices, "pages", lambda *_a, **_k: pytest.fail("same-session data downloaded twice"))
    assert shadow_worker.main() == 0
    restored = rolling_runtime.status(conn, observation_id=OBS, starting_cash=50000)
    assert restored.state.state_hash == second.state.state_hash and not restored.appended
    assert conn.execute("SELECT count(*) FROM sentinel_corpus_publications").fetchone()[0] == before
    for table in ("sentinel_execution_plans", "sentinel_commands", "sentinel_fills"):
        assert conn.execute("SELECT count(*) FROM " + table).fetchone()[0] == 0
