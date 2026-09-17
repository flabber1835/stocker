"""Pinned-source A8-A12 witnesses and diagnostic hook; production stays unchanged."""
from datetime import timedelta, date
from types import SimpleNamespace
import asyncio
import sys
from pathlib import Path
import pytest

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT / 'tests' / 'sentinel'))


def test_a8_closed_plan_cancelled_remainder_blocks(monkeypatch):
    import test_automation_runtime as f
    from sentinel import automation_runtime as runtime, paper
    from sentinel.execution import journal
    from sentinel.execution.states import CommandState
    from sentinel.automation.model import CycleState, ExecuteDisposition
    cfg, plan = f.config(), f.plan(target='2')
    ctx = f.context(cfg, state=CycleState.RECONCILING, plan=plan)
    conn, broker, subject = f.FakeConnection(), f.SimulatedBroker(), f.production(cfg)
    f.install_runtime_seams(monkeypatch, subject, conn, ctx, broker)
    monkeypatch.setattr(runtime.schema, 'require_runtime_schema', lambda _: None)
    monkeypatch.setattr(runtime, 'require_observation_integrity', lambda _: None)
    f.install_durable_projection(monkeypatch, plan)
    async def clean(**kwargs):
        return f.reconciliation(await kwargs['broker'].observe())
    monkeypatch.setattr(paper, 'recover_automated_paper_cycle', clean)
    monkeypatch.setattr(journal, 'in_flight_commands', lambda *_: ())
    monkeypatch.setattr(journal, 'latest_plan', lambda _: plan)
    monkeypatch.setattr(journal, 'load_commands', lambda *a, **k: (f.command(plan.plan_id, state=CommandState.CANCELLED),))
    monkeypatch.setattr(runtime, '_now_utc', lambda: ctx.cycle.execution_close_at + timedelta(days=1))
    result = asyncio.run(subject.recover(ctx))
    assert result.disposition is ExecuteDisposition.BLOCKED
    assert result.failure_code == 'TERMINAL_COMMAND_REFUSAL'


def test_a8_later_sessions_remain_blocked(monkeypatch):
    import test_automation_runtime as f
    from sentinel.automation import store, integrity
    from sentinel.automation.model import CycleState, TickAction
    from sentinel.automation_resilience import RecoveryAutomationService
    cfg, conn = f.config(), f.FakeConnection()
    ctx = f.context(cfg, state=CycleState.BLOCKED, plan=f.plan())
    monkeypatch.setattr(store, 'load_control', lambda _: f.control(cfg))
    monkeypatch.setattr(store, 'acquire_lease', lambda *a, **k: ctx.permit)
    monkeypatch.setattr(store, 'oldest_nonterminal_other_generation_cycle', lambda *a, **k: None)
    monkeypatch.setattr(store, 'blocked_cycle_for_generation', lambda *a, **k: ctx.cycle)
    monkeypatch.setattr(integrity, 'validate_cycle_lineage', lambda *a: None)
    async def action(*a, **k): pytest.fail('later callback unexpectedly reached')
    svc = RecoveryAutomationService(config=cfg, holder_id='worker-a', refresh=action, prepare=action, recover=action, execute=action)
    for days in (1,5,30):
        result = asyncio.run(svc.tick(conn, now=f.NOW + timedelta(days=days)))
        assert result.action is TickAction.BLOCKED
        assert 'operator deactivate/reactivate' in result.reason


def test_a9_current_rename_is_refused_as_history_change():
    from dataclasses import replace
    from sentinel.core.rolling_continuity import _same_reference, RollingContinuityRefused
    from stock_strategy_shared.wealth_core.feed import SecurityMeta
    meta = SecurityMeta(security_id='1', permaticker='1', ticker='OLD', category='Domestic Common Stock', first_session='2020-01-02')
    old = SimpleNamespace(current_metadata=lambda: ({'1':meta}, {'1':'Technology'}), actions=[])
    new = SimpleNamespace(current_metadata=lambda: ({'1':replace(meta,ticker='NEW')}, {'1':'Technology'}), actions=[])
    with pytest.raises(RollingContinuityRefused,match='HISTORICAL_REFERENCE_CHANGED: 1'):
        _same_reference(old,new,'2026-09-14')


def test_a10_rounded_uniform_benchmark_rebase_is_refused(monkeypatch):
    from decimal import Decimal
    from sentinel.core.rolling_continuity import _overlap, RollingContinuityRefused
    from sentinel.feed import rolling_store
    from sentinel.feed.rolling_contract import CanonicalBenchmark
    from stock_strategy_shared.wealth_core.feed import VendorBar
    def benchmark(day, spy):
        return CanonicalBenchmark(session=date.fromisoformat(day),spy_total_return=float(spy),bil_open_signal=100.,bil_close_signal=100.,bil_close_adjusted=100.,bil_close_unadjusted=100.)
    data={'old':[benchmark('2026-09-10',10),benchmark('2026-09-11',11)],'new':[benchmark('2026-09-10',9.9837),benchmark('2026-09-11',10.9821)]}
    for before,after in ((Decimal('10'),Decimal('9.9837')),(Decimal('11'),Decimal('10.9821'))):
        assert after-Decimal('.00005') <= before*Decimal('.99837') <= after+Decimal('.00005')
    def bars(**kwargs):
        for day in ('2026-09-10','2026-09-11'):
            yield VendorBar(session=day,security_id='1',ticker='AAA',raw_close=100.,raw_open=100.,volume=100.,signal_close=100.)
    def reader(candidate):return SimpleNamespace(candidate_id=candidate,bars=bars,manifest=SimpleNamespace(window=SimpleNamespace(start=date(2026,9,10))))
    monkeypatch.setattr(rolling_store,'read_benchmarks',lambda conn,candidate:iter(data[candidate]))
    refs=SimpleNamespace(resolver=SimpleNamespace(resolve=lambda *a:'1'))
    with pytest.raises(RollingContinuityRefused,match='NONUNIFORM_BENCHMARK_REBASE: spy_total_return'):
        _overlap(None,reader('old'),reader('new'),refs,'2026-09-11')


def test_a11_real_statement_timeout_has_no_recovery_mapping():
    import psycopg
    from sentinel.automation_runtime import classify_dependency_failure
    from tests.support.postgres import _EphemeralPostgres
    pg=_EphemeralPostgres(); pg.start()
    try:
        with psycopg.connect(pg.sync_dsn) as conn:
            conn.execute("SET statement_timeout='25ms'")
            with pytest.raises(psycopg.errors.QueryCanceled) as caught:
                conn.execute('SELECT pg_sleep(0.2)')
            assert caught.value.sqlstate=='57014'
            assert classify_dependency_failure(caught.value) is None
            conn.rollback()
            assert conn.execute('SELECT 1').fetchone()==(1,)
    finally:
        pg.stop()


def test_a12_execution_reference_reads_repeat_full_verification(monkeypatch):
    from sentinel.execution import feed_inputs
    from sentinel.core import rolling_inputs
    from sentinel.feed import rolling_store
    calls=[]
    monkeypatch.setattr(feed_inputs.snapshots,'_bound',lambda *a:{'candidate_id':'sealed','snapshot_id':'same'})
    monkeypatch.setattr(rolling_store,'verify_content',lambda *a:calls.append(a[1]))
    monkeypatch.setattr(rolling_inputs,'SnapshotReferences',lambda *a,**k:object())
    for _ in range(3):feed_inputs.references(object(),object())
    assert calls==['sealed','sealed','sealed']


def pytest_configure(config):
    """Trace only server query cancellations in this disposable audit process.
    Parameters are never printed. Forked callback children inherit the hook.
    """
    import os, traceback, psycopg
    original=psycopg.Cursor.execute
    def execute(self,query,params=None,**kwargs):
        try:
            return original(self,query,params,**kwargs)
        except psycopg.errors.QueryCanceled:
            print('AUDIT_SQL_TIMEOUT pid='+str(os.getpid())+' query='+str(query),file=sys.stderr,flush=True)
            traceback.print_stack(file=sys.stderr)
            raise
    psycopg.Cursor.execute=execute
