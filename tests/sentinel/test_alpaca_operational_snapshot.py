"""Alpaca/Nasdaq GO source through the real snapshot tables and reader."""
from __future__ import annotations

from datetime import date, datetime, timezone
from zoneinfo import ZoneInfo
from contextlib import contextmanager
import json

import pytest

from sentinel.feed import operational_snapshot as op, rolling_builder, rolling_publisher
from sentinel.feed import rolling_store
from sentinel.feed import store
from sentinel.feed.alpaca_source import AlpacaSource
from sentinel.feed.alpaca_transport import ACTION_URL, ASSETS, BAR_URL
from sentinel.feed import openfigi
from sentinel.feed.rolling_contract import PriceWindow, digest
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg  # noqa: F401


class FakeClient:
    def __init__(self, *, window=None, missing=None, action=False):
        self.window = window or PriceWindow.through("2026-09-14")
        self.missing = missing
        self.action = action
        self.calls = []

    def get(self, endpoint, params=None, *, text=False):
        self.calls.append((endpoint, params))
        proof = {"endpoint": endpoint, "observed_at": "2026-09-15T00:00:00+00:00",
                 "sha256": digest([endpoint, params])}
        if endpoint == ASSETS:
            return [{"id": "uuid-" + symbol, "symbol": symbol, "class": "us_equity",
                     "status": "active", "tradable": True, "exchange": "NASDAQ"}
                    for symbol in ("AAA", "BBB")], proof
        raise AssertionError(endpoint)

    def pages(self, endpoint, params, *, key):
        self.calls.append((endpoint, params))
        proof = {"endpoint": endpoint, "params": params,
                 "observed_at": "2026-09-15T00:00:00+00:00",
                 "sha256": digest([endpoint, params])}
        if endpoint == ACTION_URL:
            records = ([{"id": "split", "process_date": "2026-09-01",
                         "ex_date": ("2025-01-01" if self.action == "old_split"
                                     else "2026-05-01"), "symbol": "BBB"}]
                       if self.action in {"old_split", "mid_split"} else
                       [{"id": "div", "process_date": "2026-09-01",
                         "ex_date": "2026-09-01", "symbol": "BBB",
                         "rate": 0.25, "foreign": False}]
                       if self.action == "valid" else
                       [{"id": "div", "process_date": "2026-09-01",
                         "symbol": "BBB"}] if self.action else [])
            yield {"forward_splits" if self.action in {"old_split", "mid_split"}
                   else "cash_dividends": records}, proof
            return
        assert endpoint == BAR_URL and key == "bars"
        lo, hi = params["start"][:10], params["end"][:10]
        rows = {}
        for symbol in params["symbols"].split(","):
            values = []
            for day in self.window.sessions:
                stamp = str(day)
                if not lo <= stamp <= hi or (symbol, stamp) == self.missing:
                    continue
                moment = datetime.combine(day, datetime.min.time(),
                                          tzinfo=ZoneInfo("America/New_York"))
                values.append({"t": moment.astimezone(timezone.utc).isoformat(), "o": 50.0,
                               "c": 51.0, "v": 1000})
            rows[symbol] = values
        yield rows, proof


class FakeClassifier:
    batch_size = 100

    def __init__(self):
        self.calls = []

    def mapping(self, assets):
        self.calls.append(assets)
        return [{'data':[{'ticker':openfigi.job(asset)['idValue'], 'exchCode':'US',
            'marketSector':'Equity', 'securityType':'Common Stock', 'securityType2':'Common Stock',
            'compositeFIGI':'FIGI-'+asset['asset_id'], 'shareClassFIGI':'SHARE-'+asset['asset_id']}]}
            for asset in assets], {'observed_at':'2026-09-15T00:00:00+00:00'}


def test_retained_class_symbols_use_bytewise_order_across_database_locales(monkeypatch):
    """A locale may sort BFAM before BF.B, opposite canonical ticker order."""
    day = "2026-09-14"
    values = {
        symbol: ("part", day, symbol, json.dumps({"date": day, "ticker": symbol}))
        for symbol in ("BF.B", "BFAM")
    }

    @contextmanager
    def locale_cursor(_conn, query, _params, **_kwargs):
        order = ("BF.B", "BFAM") if 'COLLATE "C"' in query else ("BFAM", "BF.B")
        yield iter(values[symbol] for symbol in order)

    monkeypatch.setattr(store, "streaming_cursor", locale_cursor)
    assert [row["ticker"] for row in rolling_builder._alpaca_rows(None, type(
        "Lease", (), {"job_id": "fixture"})())] == ["BF.B", "BFAM"]


def test_current_universe_collapse_refuses_before_publication():
    with pytest.raises(ValueError, match="below 95%"):
        rolling_builder.require_alpaca_population(selected=1000, admitted=949)
    rolling_builder.require_alpaca_population(selected=1000, admitted=950)


def test_deliberate_quarantine_is_separate_from_missing_provider_coverage():
    rolling_builder.require_alpaca_population(selected=1000, admitted=850, deliberate_exclusions=150)
    with pytest.raises(ValueError, match='below 95%'):
        rolling_builder.require_alpaca_population(selected=1000, admitted=800, deliberate_exclusions=150)
    with pytest.raises(ValueError, match='below 500'):
        rolling_builder.require_alpaca_population(selected=1000, admitted=499, deliberate_exclusions=501)
    with pytest.raises(ValueError, match='accounting'):
        rolling_builder.require_alpaca_population(selected=1000, admitted=850, deliberate_exclusions=151)


@pytest.fixture
def alpaca_path(monkeypatch):
    fake = FakeClient()
    fake.classifier = FakeClassifier()
    from sentinel.feed import alpaca_source
    monkeypatch.setattr(alpaca_source, '_today', lambda: date(2026,9,15))
    monkeypatch.setattr(rolling_publisher, "_operational_source",
        lambda window, conn, lease, *, corrections, verify_during_coverage:
            AlpacaSource(window, conn, lease, client=fake, classifier=fake.classifier,
                         verify_during_coverage=verify_during_coverage))
    monkeypatch.setattr(rolling_builder, "MIN_ADMITTED_COMMON_STOCKS", 2)
    monkeypatch.setattr(op, "_now", lambda: datetime(2026, 9, 15, 4, tzinfo=timezone.utc))
    monkeypatch.setattr(op.calendar, "latest_closed_session", lambda now=None: "2026-09-14")
    return fake


def test_alpaca_snapshot_publishes_and_reads_without_sharadar(conn, alpaca_path, monkeypatch):
    from sentinel.core.rolling_inputs import readiness_inputs
    from sentinel.feed import sharadar, snapshot_export
    monkeypatch.setattr(sharadar, "fetch_table", lambda *a, **k: pytest.fail("Sharadar GET"))
    monkeypatch.setattr(snapshot_export, "probe_snapshot", lambda *a, **k: pytest.fail("Sharadar export"))
    job = op.enqueue(conn, strategy_sha256=digest("test-strategy"),
                     dependencies_sha256=digest("test-deps"), budget_seconds=240)
    conn.commit()
    result = op.prepare(conn, job)
    manifest = rolling_store.manifest(conn, result["candidate_id"])
    assert manifest.provider == "ALPACA_OPENFIGI"
    assert manifest.bar_count == 600
    assert readiness_inputs(conn, candidate_id=result["candidate_id"],
                            snapshot_id=result["snapshot_id"]).counts["2026-09-14"] == 2
    # Follow the real producer's retained parts through the shared authority
    # reader used by empty enrollment, paper issuance and daily renewal.
    from sentinel.observation_authority import current_metadata_snapshot_identity
    from sentinel.core.rolling_inputs import SnapshotReferences
    refs = SnapshotReferences(conn, candidate_id=result["candidate_id"],
                              snapshot_id=result["snapshot_id"])
    from sentinel.feed.rolling_contract import canonical_json
    assert current_metadata_snapshot_identity(conn) == {
        "snapshot_date": "2026-09-15", "row_count": 2,
        "sha256": digest(sorted(refs.tickers, key=canonical_json))}
    assert all(call[0] not in ("https://data.nasdaq.com/api/v3/datatables/SHARADAR/SEP",)
               for call in alpaca_path.calls)


def test_published_alpaca_metadata_supports_signed_daily_authority(conn, alpaca_path):
    from sentinel import binding, schema, authority
    from sentinel.standing_observation_authority import require_standing_observation_authority
    from tests.sentinel.test_paper_observation_authority import claims, activate
    from tests.sentinel.test_issue_209_standing_authority import _kwargs

    job = op.enqueue(conn, strategy_sha256=digest("test-strategy"),
                     dependencies_sha256=digest("test-deps"), budget_seconds=240)
    conn.commit()
    op.prepare(conn, job)
    schema.ensure_schema(conn)
    binding.bind(conn, deployment_id="nas-paper-observe", broker="alpaca",
                 broker_account_id="paper-123")
    document = claims(conn)
    activate(conn, document)  # Test-only enrolled root, no real key or broker.
    kwargs = _kwargs(document, now=datetime(2026, 10, 1, tzinfo=timezone.utc))
    kwargs["current_publication_version"] = document["bindings"]["current_corpus"]["data_version"]
    standing = require_standing_observation_authority(conn, **kwargs)
    assert standing.authorization_mode == authority.PAPER_OBSERVATION_ONLY
    assert document["bindings"]["current_metadata_snapshot"]["snapshot_date"] == "2026-09-15"


def test_alpaca_transport_exhaustion_keeps_daily_job_retryable(
        conn, alpaca_path, monkeypatch):
    from sentinel.feed.alpaca_transport import AlpacaTransportUnavailable
    from sentinel.feed import rolling_jobs

    def unavailable(*_a, **_k):
        raise AlpacaTransportUnavailable("provider request exhausted its retry budget")

    monkeypatch.setattr(alpaca_path, "get", unavailable)
    job = op.enqueue(conn, strategy_sha256=digest("test-strategy"),
                     dependencies_sha256=digest("test-deps"), budget_seconds=240)
    conn.commit()
    with pytest.raises(AlpacaTransportUnavailable):
        op.prepare(conn, job)
    state = rolling_jobs.status(conn, job)
    assert state["state"] == "RETRY_WAIT"
    assert state["reason"] == "SOURCE_RETRY"


def test_publication_backup_horizon_precedes_provider_recheck(
        conn, alpaca_path, monkeypatch):
    from sentinel import backup_runtime_authority as backup
    from sentinel.core import rolling_inputs
    from sentinel.feed import rolling_jobs as jobs

    job = op.enqueue(conn, strategy_sha256=digest('test-strategy'),
                     dependencies_sha256=digest('test-deps'), budget_seconds=240)
    conn.commit()
    deadline = jobs.status(conn, job)['deadline']
    original_require = backup.require
    original_readiness = rolling_inputs.readiness_inputs
    original_build = rolling_builder.build
    renewed = [False]
    validation_reads, builds = [], []

    def guard(c, *, operation, **kwargs):
        if operation == 'operational publication preflight' and not renewed[0]:
            raise backup.BackupHorizonExceeded('fixture WAL horizon exhausted')
        return original_require(c, operation=operation, **kwargs)

    def readiness(*args, **kwargs):
        validation_reads.append(True)
        return original_readiness(*args, **kwargs)

    def build(*args, **kwargs):
        builds.append(True)
        return original_build(*args, **kwargs)

    monkeypatch.setattr(backup, 'require', guard)
    monkeypatch.setattr(rolling_inputs, 'readiness_inputs', readiness)
    monkeypatch.setattr(rolling_builder, 'build', build)
    with pytest.raises(backup.BackupHorizonExceeded) as caught:
        op.prepare(conn, job)
    paused = jobs.status(conn, job)
    assert caught.value.resume_job_id == job
    assert paused['state'] == 'RETRY_WAIT' and paused['resume_state'] == 'READY'
    assert paused['owner'] is None and paused['deadline'] == deadline
    assert validation_reads == [True]
    assert sum(endpoint == ASSETS for endpoint, _ in alpaca_path.calls) == 1
    assert sum(endpoint == ACTION_URL for endpoint, _ in alpaca_path.calls) == 1
    price_calls = sum(endpoint == BAR_URL for endpoint, _ in alpaca_path.calls)
    assert price_calls > 0 and builds == [True]
    assert conn.execute('SELECT count(*) FROM sentinel_corpus_publications').fetchone()[0] == 0

    renewed[0] = True
    conn.execute('UPDATE sentinel_snapshot_jobs SET next_retry=clock_timestamp() WHERE job_id=%s', (job,))
    conn.commit()
    result = op.prepare(conn, job)
    assert result['scope'] == 'DATA_ONLY'
    assert jobs.status(conn, job)['deadline'] == deadline
    assert validation_reads == [True, True] and builds == [True]
    assert sum(endpoint == BAR_URL for endpoint, _ in alpaca_path.calls) == price_calls
    assert sum(endpoint == ASSETS for endpoint, _ in alpaca_path.calls) == 2
    assert sum(endpoint == ACTION_URL for endpoint, _ in alpaca_path.calls) == 2


def test_post_validation_provider_change_still_prevents_publication(
        conn, alpaca_path, monkeypatch):
    from sentinel.feed.acquisition_parts import SourceRevision
    original = AlpacaSource.corroborate

    def changed(source):
        count = conn.execute('SELECT count(*) FROM sentinel_operational_snapshot_validations').fetchone()[0]
        assert count == 1, 'operational validation must precede final corroboration'
        alpaca_path.action = True
        return original(source)

    monkeypatch.setattr(AlpacaSource, 'corroborate', changed)
    with pytest.raises(SourceRevision, match='ACTIONS'):
        _publish(conn)
    assert conn.execute('SELECT count(*) FROM sentinel_corpus_publications').fetchone()[0] == 0


def test_alpaca_action_and_missing_bar_remove_only_affected_security(conn, alpaca_path):
    alpaca_path.action = True
    alpaca_path.missing = ("AAA", "2026-09-11")
    job = op.enqueue(conn, strategy_sha256=digest("test-strategy"),
                     dependencies_sha256=digest("test-deps"), budget_seconds=240)
    conn.commit()
    with pytest.raises(ValueError, match="population is below"):
        op.prepare(conn, job)
    assert conn.execute("SELECT COUNT(*) FROM sentinel_corpus_publications").fetchone()[0] == 0


def test_valid_cash_dividend_preserves_stock_and_credits_formation_bar(conn, alpaca_path):
    alpaca_path.action = "valid"
    job = op.enqueue(conn, strategy_sha256=digest("test-strategy"),
                     dependencies_sha256=digest("test-deps"), budget_seconds=240)
    conn.commit()
    result = op.prepare(conn, job)
    bars = [row for row in rolling_store.read_bars(conn, result["candidate_id"])
            if row.ticker == "BBB" and str(row.session) == "2026-09-01"]
    assert len(bars) == 1 and bars[0].dividend_per_share == 0.25
    reference = rolling_store.load_evidence(
        conn, rolling_store.manifest(conn, result["candidate_id"]).reference_sha256)
    assert reference["actions"] == [{"date": "2026-09-01", "action": "dividend",
                                     "ticker": "BBB", "name": None, "value": "0.25",
                                     "contraticker": None, "contraname": None}]


def test_pre_window_split_does_not_remove_current_stock(conn, alpaca_path):
    alpaca_path.action = "old_split"
    job = op.enqueue(conn, strategy_sha256=digest("test-strategy"),
                     dependencies_sha256=digest("test-deps"), budget_seconds=240)
    conn.commit()
    result = op.prepare(conn, job)
    assert rolling_store.manifest(conn, result["candidate_id"]).bar_count == 600


def test_in_window_split_resets_candidate_history(conn, alpaca_path):
    alpaca_path.action = "mid_split"
    job = op.enqueue(conn, strategy_sha256=digest("test-strategy"),
                     dependencies_sha256=digest("test-deps"), budget_seconds=240)
    conn.commit()
    result = op.prepare(conn, job)
    bars = [row for row in rolling_store.read_bars(conn, result["candidate_id"])
            if row.ticker == "BBB"]
    assert bars and all(str(row.session) > "2026-05-01" for row in bars)
    assert len(bars) < 300


def _publish(conn):
    job = op.enqueue(conn, strategy_sha256=digest('test-strategy'),
                     dependencies_sha256=digest('test-deps'), budget_seconds=240)
    conn.commit()
    return op.prepare(conn, job)


def _next_day(fake, monkeypatch):
    fake.window = PriceWindow.through('2026-09-15')
    monkeypatch.setattr(op, '_now', lambda: datetime(2026,9,16,4,tzinfo=timezone.utc))
    monkeypatch.setattr(op.calendar, 'latest_closed_session', lambda now=None: '2026-09-15')


def test_daily_verified_classification_reuse_never_renews_age(conn, alpaca_path, monkeypatch):
    _publish(conn)
    assert len(alpaca_path.classifier.calls) == 1
    _next_day(alpaca_path, monkeypatch)
    _publish(conn)
    assert len(alpaca_path.classifier.calls) == 1
    from sentinel.feed import alpaca_source
    # At seven days the original observation expires, even after publication reuse.
    monkeypatch.setattr(alpaca_source, '_today', lambda: date(2026,9,22))
    alpaca_path.window = PriceWindow.through('2026-09-16')
    monkeypatch.setattr(op, '_now', lambda: datetime(2026,9,17,4,tzinfo=timezone.utc))
    monkeypatch.setattr(op.calendar, 'latest_closed_session', lambda now=None: '2026-09-16')
    _publish(conn)
    assert len(alpaca_path.classifier.calls) == 2


def test_restart_reuses_finished_figi_batches_without_network(conn, alpaca_path):
    from sentinel.feed import rolling_jobs as jobs
    from sentinel.feed.alpaca_transport import AlpacaTransportUnavailable
    job = op.enqueue(conn, strategy_sha256=digest('test-strategy'),
                     dependencies_sha256=digest('test-deps'), budget_seconds=240)
    lease = jobs.claim(conn, job, lease_seconds=60)
    conn.commit()
    classifier = alpaca_path.classifier
    classifier.batch_size = 1
    original = classifier.mapping
    attempts = []
    def interrupted(assets):
        attempts.append(assets[0]['ticker'])
        if len(attempts) == 2:
            raise AlpacaTransportUnavailable('interrupted batch')
        return original(assets)
    classifier.mapping = interrupted
    checkpoint = lambda component,generation,artifact,rows,bytes_: jobs.checkpoint(
        conn,lease,component=component,generation_sha256=digest(generation),
        artifact_sha256=artifact,rows=rows,bytes_=bytes_)
    def source():
        return AlpacaSource(alpaca_path.window,conn,lease,client=alpaca_path,classifier=classifier)
    with pytest.raises(AlpacaTransportUnavailable):
        source().references(checkpoint)
    source().references(checkpoint)
    assert attempts == ['AAA','BBB','BBB']
    assert conn.execute("SELECT COUNT(*) FROM sentinel_snapshot_job_components "
                        "WHERE job_id=%s AND component LIKE 'TICKERS.FIGI.%%'", (job,)).fetchone()[0] == 2


@pytest.mark.parametrize('name', ['TICKERS.FIGI.0','TICKERS.FIGI.100000',
    'TICKERS.FIGI.1/../2','TICKERS.ASSETS.injected'])
def test_checkpoint_name_bounds_are_preserved(name):
    from sentinel.feed import rolling_jobs
    assert not rolling_jobs._COMPONENT.fullmatch(name)


def test_resumed_job_keeps_initial_cache_plan_across_expiry(conn,alpaca_path,monkeypatch):
    from sentinel.feed import rolling_jobs as jobs, alpaca_source
    _publish(conn)
    _next_day(alpaca_path,monkeypatch)
    job = op.enqueue(conn,strategy_sha256=digest('test-strategy'),
                     dependencies_sha256=digest('test-deps'),budget_seconds=240)
    lease = jobs.claim(conn,job,lease_seconds=60)
    conn.commit()
    checkpoint = lambda component,generation,artifact,rows,bytes_: jobs.checkpoint(
        conn,lease,component=component,generation_sha256=digest(generation),
        artifact_sha256=artifact,rows=rows,bytes_=bytes_)
    def source():
        return AlpacaSource(alpaca_path.window,conn,lease,client=alpaca_path,
                            classifier=alpaca_path.classifier)
    source().references(checkpoint)
    assert len(alpaca_path.classifier.calls) == 1
    monkeypatch.setattr(alpaca_source,'_today',lambda:date(2026,9,22))
    source().references(checkpoint)
    assert len(alpaca_path.classifier.calls) == 1


@pytest.mark.parametrize("failure", ["job-error", "malformed-batch"])
def test_figi_classification_failure_never_publishes_partial_universe(
        conn, alpaca_path, monkeypatch, failure):
    from sentinel.feed import rolling_jobs as jobs
    from sentinel.feed.alpaca_transport import AlpacaTransportRefused, AlpacaTransportUnavailable

    original = alpaca_path.classifier.mapping
    def broken(assets):
        responses, proof = original(assets)
        responses[-1] = ({"error": "temporary mapping job failure"} if failure == "job-error"
                         else {"data": []})
        return responses, proof
    monkeypatch.setattr(alpaca_path.classifier, "mapping", broken)
    job = op.enqueue(conn, strategy_sha256=digest("test-strategy"),
                     dependencies_sha256=digest("figi failure qualification"), budget_seconds=240)
    conn.commit()
    expected = AlpacaTransportUnavailable if failure == "job-error" else AlpacaTransportRefused
    with pytest.raises(expected):
        op.prepare(conn, job)
    state = jobs.status(conn, job)
    assert state["state"] == ("RETRY_WAIT" if failure == "job-error" else "REFUSED")
    assert state["owner"] is None
    assert not conn.execute("SELECT 1 FROM sentinel_corpus_publications").fetchall()
    assert not conn.execute("SELECT 1 FROM sentinel_acquisition_bindings WHERE job_id=%s "
                            "AND component LIKE 'TICKERS.FIGI.%%'", (job,)).fetchall()
    conn.rollback()
    if failure == "job-error":
        monkeypatch.setattr(alpaca_path.classifier, "mapping", original)
        conn.execute("UPDATE sentinel_snapshot_jobs SET next_retry=clock_timestamp() WHERE job_id=%s", (job,))
        conn.commit()
        published = op.prepare(conn, job)
        assert jobs.status(conn, job)["deadline"] == state["deadline"]
        assert rolling_store.manifest(conn, published["candidate_id"]).bar_count == 600
        assert sum(url == ASSETS for url, _ in alpaca_path.calls) == 2  # initial capture + corroboration
