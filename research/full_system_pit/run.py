"""Daily historical system experiment. Every transition uses the growing SQL corpus.

Run only in the staged research runtime. Failure evidence is a result; it never
becomes a performance-equivalence PASS or deployment certification.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import ExitStack
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import json
import itertools
import os
from pathlib import Path
import shutil
import sys
import time
import traceback
from unittest.mock import patch

from . import authority as a, broker
from .compare import Comparison, equal
from .evidence import Evidence, digest, plain, require, verify
from .provider import Provider
from .stage import source_manifest, sha


def sql_warmup(conn, day, *, known_feed_security_ids=()):
    """The first forty closes, when a full SPY tail does not exist yet.

    All rows are loaded from an actual pinned publication. No assets can be
    eligible during this prefix. The ordinary production loader takes over on
    close 41; its readiness, identity and dated-tail checks remain intact.
    """
    from sentinel.core import loader, production
    from sentinel.core.session import PublishedSession, DefensiveBar, FeedAnchor
    from sentinel.core.terminal import load_terminal_events
    from sentinel.feed import publication, universe
    publication.assert_operationally_coherent(conn, frontier=day,
        extra_security_ids=tuple(known_feed_security_ids))
    pub = publication.require_current(conn)
    window = loader.load_window(conn, start=day, end=day)
    meta = loader.load_meta(conn, as_of=day)
    visible = publication.visible_predicate("r", sep_retirements=False)
    spy = conn.execute("SELECT session,closeadj FROM sentinel_spy_total_return r WHERE session<=%s AND "
                       + visible + " ORDER BY session", (day,)).fetchall()
    if not 1 <= len(spy) <= 40 or str(spy[-1][0]) != day:
        raise ValueError("short-tail bootstrap called outside its prefix")
    defensive = conn.execute("SELECT session,security_id,ticker,open_signal,close_signal,close_adjusted,close_unadjusted "
        "FROM sentinel_defensive_bars r WHERE session<=%s AND " + visible + " ORDER BY session DESC LIMIT 2", (day,)).fetchall()
    resolver = universe.load_resolver(conn)
    terminals = load_terminal_events(conn, start=day, end=day, resolve_with_reason=resolver.resolve_with_reason)
    require("warmup_terminal_resolution", [], list(terminals.unresolved))
    require("warmup_terminal_conservation", True, terminals.conservation_holds())
    bars = window.bars_by_session[day]
    anchors = {bar.security_id: FeedAnchor(bar.security_id, bar.ticker, "SID:"+bar.security_id, 1.)
               for bar in bars if bar.security_id not in known_feed_security_ids}
    return PublishedSession(day, pub.version, bars, meta, loader.load_sectors(conn, as_of=day),
        [float(p) for _, p in spy], [str(s) for s, _ in spy], [str(s) for s, _ in spy],
        terminals.events, anchors,
        defensive_bar=DefensiveBar(*[str(v) if i<3 else v for i,v in enumerate(defensive[0])]),
        defensive_previous_bar=DefensiveBar(*[str(v) if i<3 else v for i,v in enumerate(defensive[1])]) if len(defensive)>1 else None,
        signal_basis_anchors=production.load_signal_basis_anchors(conn, session=day,
            security_ids=known_feed_security_ids))


def corpus_check(conn, provider, day):
    """Independent current-key economics and causal SQL frontier audit."""
    from sentinel.feed import publication
    expected = {r["sid"]:dict(r) for r in provider.db.execute("SELECT * FROM obs WHERE day=?", (day,))}
    actual = conn.execute("SELECT security_id,ticker,open_unadjusted,close_unadjusted,volume,"
        + publication.effective_split_ratio("b") + ",dividend_per_share,close_signal FROM sentinel_bars b "
        "WHERE session=%s AND " + publication.visible_predicate("b") + " ORDER BY security_id", (day,)).fetchall()
    expected = {sid:r for sid,r in expected.items() if r["raw"] is not None and r["raw"]>0}
    require("full_universe_key_coverage", sorted(expected), sorted(str(r[0]) for r in actual))
    for sid,ticker,op,raw,volume,split,dividend,signal in actual:
        e = expected[str(sid)]
        require("corpus_ticker:"+str(sid), e["ticker"], ticker)
        for name,wanted,got in (("raw_open",e["op"],op),("raw_close",e["raw"],raw),
            ("raw_volume",e["raw_volume"],volume),("split",e["split"],split),
            ("dividend",e["dividend"],dividend),
            ("signal",e["signal"]*provider.factors.get(str(sid),1.) if e["signal"] else None,signal)):
            equal("corpus:"+str(sid)+":"+name, wanted, got, money=name in {"raw_volume"})
    frontier = str(conn.execute("SELECT MAX(session) FROM sentinel_bars").fetchone()[0])
    require("corpus_causal_frontier", day, frontier)
    return dict(rows=len(actual), rows_sha256=digest(actual), frontier=frontier,
                publication=publication.require_current(conn).version)


def broker_accounting(snapshot):
    expected = Decimal(snapshot["initial_cash"])
    expected += sum(map(Decimal, snapshot["cash_movements"]), Decimal(0))
    for fill in snapshot["fills"]:
        expected -= Decimal(str(fill["sign"]))*Decimal(fill["quantity"])*Decimal(fill["price"])
    require("broker_double_entry_cash", expected, Decimal(snapshot["account"]["cash"]))
    equity = expected + sum((Decimal(q)*Decimal(snapshot["prices"][s]) for s,q in snapshot["positions"].items()), Decimal(0))
    require("broker_marked_equity", equity, Decimal(snapshot["account"]["equity"]))
    keys=[r["client_order_id"] for r in snapshot["orders"].values()]
    require("one_order_per_client_key",len(keys),len(set(keys)))
    require("cash_long_only",True,expected>=0)
    require("positions_long_only",True,all(Decimal(q)>=0 for q in snapshot["positions"].values()))


def published_cash_factors(published):
    from sentinel.shadow_observation import _strategy_prices
    if published.session==a.WARMUP and published.defensive_previous_bar is None:
        return None
    prices=_strategy_prices(published.defensive_bar,session=published.session,
                            previous_value=published.defensive_previous_bar)
    opened=Decimal(prices["bil_open_adjusted"])
    closed=Decimal(prices["bil_close_adjusted"])
    previous=Decimal(prices["bil_previous_close_adjusted"])
    return float(opened/previous),float(closed/opened)


def market_window(day):
    from sentinel.feed.calendar import session_window
    opened,closed=session_window(day)
    return opened.astimezone(timezone.utc),closed.astimezone(timezone.utc)


def final_corpus_check(conn,provider):
    from sentinel.feed import publication,store
    expected=provider.db.execute("SELECT * FROM obs WHERE raw>0 ORDER BY day,sid")
    sql="SELECT session,security_id,ticker,open_unadjusted,close_unadjusted,volume,"+publication.effective_split_ratio("b")+",dividend_per_share,close_signal FROM sentinel_bars b WHERE "+publication.visible_predicate("b")+" ORDER BY session,security_id"
    count=0
    with store.streaming_cursor(conn,sql,()) as actual:
        for wanted,got in itertools.zip_longest(expected,actual):
            if wanted is None or got is None:
                raise ValueError("final corpus length differs")
            require("final_corpus_key",(wanted["day"],wanted["sid"],wanted["ticker"]),(str(got[0]),str(got[1]),got[2]))
            for name,value in zip(("op","raw","raw_volume","split","dividend","signal"),got[3:]):
                equal("final_corpus:"+wanted["day"]+":"+wanted["sid"]+":"+name,wanted[name],value,money=name=="raw_volume")
            count+=1
    return dict(rows=count,status="PASS_COMPLETE_CANONICAL_ECONOMICS")


class Experiment:
    def __init__(self, args, evidence):
        self.args, self.evidence = args, evidence
        self.at = datetime.fromisoformat(a.WARMUP+"T00:00:00+00:00")
        self.day = a.WARMUP
        self.comparison = Comparison(args.reference)
        self.cluster = self.manager = None
        self.stack = ExitStack()
        self.completed = 0
        self.started = time.monotonic()
        self.open_audit = None
        self.command_economics={}
        self.command_history_hashes={}

    def event(self, phase, payload):
        return self.evidence.event(at=self.at, session=self.day, phase=phase, payload=payload)

    def boundary(self, phase, **kwargs):
        return self.evidence.boundary(phase, at=self.at, session=self.day, **kwargs)

    def provider_receipt(self, receipt):
        if "export" in receipt:
            receipt["retained_export"] = self.evidence.file(self.provider.exports / (receipt["export"]+".zip"))
        self.event("sharadar_response", receipt)

    def connection(self):
        from sentinel.feed import store
        return store.connect(self.cluster.dsn, statement_timeout_ms=120000)

    def start(self):
        from tests.internal_state.physical import PhysicalCluster
        from research.sharadar_replay.runtime import simulated_runtime
        from tests.internal_state.runtime import environment, startup
        from sentinel import binding, schema
        from sentinel.feed import store
        from sentinel.execution import alpaca
        from sentinel.paper.preparation import _default_paper_strategy
        with self.boundary("startup") as result:
            self.provider = Provider(self.args.truth, self.args.output / "exports", observe=self.provider_receipt)
            require("truth_source", a.DATASET_SHA256, self.provider.identity["dataset_sha256"])
            self.cluster = PhysicalCluster().start()
            self.stack.enter_context(self.cluster.runtime())
            self.stack.enter_context(simulated_runtime(self.provider, commit=a.BASE))
            self.manager, self.service = broker.manager(self.at.isoformat())
            self.cfg, self.identity = _default_paper_strategy()
            require("selected_champion", a.STRATEGY, self.cfg.strategy_id)
            env_path = self.cluster.root / "simulation.env"
            environment(env_path, self.cluster.root)
            startup(env_path)
            with self.connection() as conn:
                schema.ensure_schema(conn)
                store.migrate_schema(conn)
                binding.bind(conn, deployment_id="full-system-pit-research", broker="alpaca",
                    broker_account_id="SIM-ALPACA-1", notes="owner-authorized historical simulation")
                conn.execute("UPDATE sentinel_account_binding SET established_at=%s,updated_at=%s WHERE id=1",
                    (self.at-timedelta(days=1),self.at-timedelta(days=1)))
                conn.commit()
                alpaca.database_incarnation(conn)
            result.update(strategy=self.identity, cluster=self.cluster.checkpoints["provisioned"],
                          provider_identity=self.provider.identity)

    async def execute(self, conn):
        from sentinel import binding
        from sentinel.execution import executor, journal, reconcile, broker_cash
        adapter = broker.adapter(self.service)
        plan, bound = journal.latest_plan(conn), binding.require(conn)
        with journal.writer_lock(conn,recovery_only=True):
            cash_state=await broker_cash.ingest_account_cash(conn,broker_adapter=adapter,broker="alpaca",
                account_id="SIM-ALPACA-1",through=self.at)
            conn.commit()
        if plan is None:
            return dict(no_prior_plan=True,cash_activity=plain(cash_state))
        symbols = dict(conn.execute("SELECT DISTINCT ON (security_id) security_id,ticker FROM sentinel_bars "
            "WHERE session<=%s ORDER BY security_id,session DESC", (self.day,)).fetchall())
        symbols["SENTINEL:BIL"] = "BIL"
        instruments = {sid:await adapter.resolve_instrument(security_id=sid,symbol=symbols[sid])
                       for sid in plan.target_basket}
        result = await executor.execute_session(broker=adapter, conn=conn, deployment=bound.identity,
            plan=plan, instruments=instruments, today=date.fromisoformat(self.day), settle_cycles=2)
        self.event("executor_result",plain(result))
        require("executor_refusals",{},dict(result.refused))
        require("executor_degraded",False,result.runtime_state.value in {"BROKER_DEGRADED","RECONCILING"})
        with journal.writer_lock(conn, recovery_only=True):
            reconciled = await reconcile.reconcile(broker=adapter,conn=conn,binding=bound,deployment=bound.identity)
        from tests.internal_state import oracles
        from tests.internal_state.runtime import command_dict
        commands=[command_dict(c) for c in journal.load_commands(conn,bound.identity)]
        histories={c["client_key"]:plain(journal.command_history(conn,c["client_key"])) for c in commands}
        oracles.journal_contract(commands,histories,self.service.snapshot(),self.command_economics)
        for command in commands:
            key=command["client_key"]
            receipt=dict(command=command,history=histories[key])
            commitment=digest(receipt)
            if self.command_history_hashes.get(key)!=commitment:
                self.event("command_history",receipt)
                self.command_history_hashes[key]=commitment
        return dict(execution=plain(result),reconciliation=plain(reconciled),cash_activity=plain(cash_state))

    def decide(self, conn, day, raw):
        from sentinel import binding
        from sentinel.authority import RolloutMode, RolloutState
        from sentinel.core.decision import build_execution_plan
        from sentinel.core.session import SessionState
        from sentinel.feed import publication, calendar
        from sentinel.paper.preparation import _load_marks_and_tickers
        adapter = broker.adapter(self.service)
        account, observation = asyncio.run(adapter.account_snapshot()), asyncio.run(adapter.observe())
        with publication.pinned(conn, commit=False) as pub:
            state = SessionState.from_dict(raw)
            marks,tickers = _load_marks_and_tickers(conn,state,day)
            result = build_execution_plan(state,binding.require(conn),pub,account,observation,marks,tickers,
                date.fromisoformat(day),date.fromisoformat(calendar.next_session(day)),
                rollout_state=RolloutState(RolloutMode.CONTROLLER,1,"historical-simulation-only"))
        self.event("execution_plan", result.plan.to_dict())
        return result.plan

    def advance(self, conn, day, prior):
        from sentinel.core import production
        from stock_strategy_shared.wealth_core import adapter
        from sentinel.core.session import SessionState
        from tools.median5_equivalence import opening_estimate
        loader = sql_warmup if self.completed < 40 else production.load_published_session
        original = adapter._resolved_open_equity
        observations = []
        def observed(state,bars,ledger):
            value = original(state,bars,ledger)
            observations.append(opening_estimate(state,bars,ledger,SessionState.from_dict(prior)))
            return value
        def load(conn, day, **kw):
            published = loader(conn, day, **kw)
            self.event("published_inputs", published)
            self.cash_audit=published_cash_factors(published)
            return published
        with patch.object(adapter,"_resolved_open_equity",observed):
            result = production.advance_and_persist(conn,day,prior,load_published=load,
                controller_config=self.cfg,strategy_identity=self.identity,commit_pin=False)
        require("one_opening_boundary",1,len(observations))
        self.open_audit = observations[0]
        return result

    def day_step(self, day):
        from sentinel.core import catchup
        from sentinel.core.session import SessionState
        from sentinel.controller.machine import Controller
        from sentinel.feed import calendar, ingest, readiness
        opened, closed = market_window(day)
        self.day, self.at = day, opened+timedelta(minutes=1)
        market = [dict(r) for r in self.provider.db.execute("SELECT * FROM obs WHERE day=?",(day,))]
        cash = self.provider.db.execute("SELECT * FROM reference WHERE day=?",(day,)).fetchone()
        bil_open,bil_close = self.provider.cash_levels[day]
        market.append(dict(sid="SENTINEL:BIL",ticker="BIL",op=bil_open,raw=bil_close,raw_volume=1e9,split=1.,dividend=0.))
        with self.boundary("market_open") as result:
            self.service.market(self.at.isoformat(),opened.isoformat(),market,opened=True)
            with self.connection() as conn:
                result.update(asyncio.run(self.execute(conn)))
            result["wire"] = self.service.drain()
            snapshot = self.service.snapshot()
            broker_accounting(snapshot)
            result["broker"] = snapshot
        self.at = closed+timedelta(hours=1)
        self.provider.advance(self.at)
        self.service.market(self.at.isoformat(),opened.isoformat(),market,opened=False)
        with self.connection() as conn:
            with self.boundary("ingestion") as result:
                if self.completed == 0:
                    progress = ingest.seed(conn,date_from=a.WARMUP,date_to=day)
                else:
                    progress = ingest.daily(conn,today=day)
                result["progress"] = plain(progress)
            with self.boundary("corpus_publication") as result:
                result.update(corpus_check(conn,self.provider,day))
            with self.boundary("readiness") as result:
                report = readiness.check_readiness(conn,today=self.at.isoformat())
                result["report"] = plain(report)
                if self.completed >= 126:
                    require("production_readiness",[],[plain(c) for c in report.failures])
                else:
                    result["phase"] = "WARMUP_NO_ELIGIBLE_PORTFOLIO"
            with self.boundary("strategy_and_plan") as result:
                prior = catchup.resume_state(conn)
                if prior is None:
                    require("fresh_state_only_at_start",0,self.completed)
                    prior = SessionState.fresh(starting_cash=100000.,controller=Controller(self.cfg),
                        strategy_identity=self.identity).to_dict()
                outcome = catchup.catch_up(conn,through=day,missed=[day],state=prior,
                    advance_state=self.advance,decide=lambda d,s:self.decide(conn,d,s))
                raw = catchup.resume_state(conn)
                require("durable_restart_commitment",outcome.state,raw)
                state = SessionState.from_dict(raw)
                result.update(state_sha256=state.state_hash, state={k:v for k,v in raw.items() if k!="feed"},
                    feed_sha256=digest(raw["feed"]),feed_securities=len(raw["feed"]["series"]),wire=self.service.drain())
                if self.completed < 126:
                    require("warmup_no_positions",{},state.wealth_core["episodes"])
                if self.completed % 63 == 0:
                    result["restart_state"] = self.evidence.object(raw)
            with self.boundary("independent_comparison") as result:
                if self.cash_audit is not None:
                    equal("published_cash_gap",cash["gap"],self.cash_audit[0])
                    equal("published_cash_intraday",cash["intraday"],self.cash_audit[1])
                result.update(self.comparison.observe(day,state,self.open_audit[0],self.cash_audit))
                result["published_cash_factors"]=self.cash_audit
                result["opening_carried_marks"] = self.open_audit[1]
                snapshot = self.service.snapshot()
                broker_accounting(snapshot)
                result["broker_nav"] = float(snapshot["account"]["equity"])/100000.
        self.completed += 1
        if self.completed % 63 == 0:
            with self.boundary("postgres_restart") as result:
                self.cluster.stop_server()
                self.cluster._start_server()
                with self.connection() as conn:
                    require("postgres_restart_state",raw,catchup.resume_state(conn))
                result["state_sha256"] = state.state_hash
        elapsed = time.monotonic()-self.started
        print(json.dumps(dict(phase="daily_complete",session=day,completed=self.completed,
            total=a.OBSERVATIONS,seconds=elapsed,estimated_remaining_seconds=elapsed/self.completed*(a.OBSERVATIONS-self.completed))),flush=True)

    def run(self):
        self.start()
        sessions = self.provider.identity["sessions"]
        for day in sessions:
            if day > self.args.through:
                break
            self.day_step(day)
        if self.args.through == a.END:
            self.recovery_check()
            with self.boundary("final_corpus") as result:
                with self.connection() as conn:
                    result.update(final_corpus_check(conn,self.provider))
            with self.boundary("final_equivalence") as result:
                required={"market_open:complete","ingestion:complete","corpus_publication:complete",
                    "readiness:complete","strategy_and_plan:complete","independent_comparison:complete",
                    "sharadar_response","published_inputs","execution_plan"}
                for day in sessions:
                    require("instrumentation_coverage:"+day,[],sorted(required-set(self.evidence.phases.get(day,()))))
                result.update(self.comparison.finish())
            return dict(status="PASS_FULL_SYSTEM_HISTORICAL_REPLAY",**result)
        return dict(status="PASS_PREFIX_ONLY",sessions=self.completed,through=self.day,
                    full_equivalence_confirmed=False)

    def recovery_check(self):
        from sentinel import binding
        from sentinel.core import catchup
        from sentinel.execution import alpaca,journal,reconcile
        with self.boundary("populated_backup_restore") as result:
            with self.connection() as conn:
                before=catchup.resume_state(conn)
                incarnation=alpaca.database_incarnation(conn)
                plan=journal.latest_plan(conn).to_dict()
            external=self.service.snapshot()
            checkpoint=self.cluster.checkpoint("historical_complete")
            result["checkpoint"]=checkpoint
            result["backup_manifest"]=self.evidence.file(checkpoint["base"]/"backup_manifest")
            self.cluster.restore("historical_complete")
            with self.connection() as conn:
                require("physical_restore_state",before,catchup.resume_state(conn))
                require("physical_restore_plan",plan,journal.latest_plan(conn).to_dict())
                bound=binding.require(conn)
                reason=alpaca.execution_increase_fence_reason(conn=conn,deployment=bound.identity,today=date.fromisoformat(self.day))
                require("restore_takeover_fence",True,"incarnation/timeline changed" in reason)
                with journal.writer_lock(conn,recovery_only=True):
                    result["reconciliation"]=plain(asyncio.run(reconcile.reconcile(
                        broker=broker.adapter(self.service),conn=conn,binding=bound,deployment=bound.identity)))
                result["prior_incarnation"]=plain(incarnation)
                result["restored_incarnation"]=plain(alpaca.database_incarnation(conn))
                result["fence"]=reason
            require("restore_preserves_broker",external,self.service.snapshot())
            result["wire"]=self.service.drain()

    def close(self):
        if self.cluster and (self.cluster.root / "postgres.log").exists():
            shutil.copyfile(self.cluster.root / "postgres.log",self.args.output / "postgres.log")
        self.stack.close()
        if self.manager:
            self.manager.shutdown()
        if self.cluster:
            self.cluster.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--truth",type=Path,required=True)
    parser.add_argument("--reference",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--through",default=a.END)
    args = parser.parse_args()
    runtime = Path(__file__).resolve().parents[2]
    manifest = json.loads((runtime / "REPLAY_RUNTIME.json").read_text())
    require("runtime_bytes",manifest["files"],source_manifest(runtime))
    require("harness_bytes",manifest["harness_files"],
            {p.name:sha(p) for p in sorted(Path(__file__).parent.glob("*.py"))})
    if args.through < a.WARMUP or args.through > a.END:
        raise ValueError("requested range outside authority")
    identity = dict(runtime=manifest,reference_commit=a.REFERENCE_COMMIT,reference_run=a.REFERENCE_RUN,
        through=args.through, dataset_sha256=a.DATASET_SHA256, production_certification=False,
        simulated_services=["Sharadar","Alpaca","market clock"],
        service_clock="real PostgreSQL/WAL time", harness_commit=os.environ.get("GITHUB_SHA"))
    evidence = Evidence(args.output,identity)
    experiment = Experiment(args,evidence)
    status = 0
    try:
        result = experiment.run()
    except BaseException as exc:
        if not (args.output/"FIRST_FAILURE.json").exists():
            evidence.write("FIRST_FAILURE.json",dict(session=experiment.day,phase="driver",
                error_type=type(exc).__name__,error=str(exc),traceback=traceback.format_exc()))
        result = dict(status="FAIL_FULL_SYSTEM_HISTORICAL_REPLAY",error_type=type(exc).__name__,error=str(exc),
            completed=experiment.completed,through=experiment.day,full_equivalence_confirmed=False)
        status = 1
    finally:
        experiment.close()
        evidence.close()
    result["evidence_verification"] = verify(args.output)
    evidence.write("RESULT.json",result)
    print(json.dumps(result,sort_keys=True),flush=True)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
