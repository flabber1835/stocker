"""Canonical 252+126 formed startup followed by a separate $50k research account."""
from __future__ import annotations

import argparse
from dataclasses import asdict
from decimal import Decimal as D
import gzip
import hashlib
import json
from pathlib import Path
import time
import traceback
from types import SimpleNamespace

from research.bounded_20y.inputs import sha256
from research.bounded_20y.january import load_supplements
from research.bounded_20y.run import EconomicPath, metadata, vendor, terminals, distributions
from research.economic_replay60.inputs import Classification
from sentinel import formed_economics, formed_origin
from sentinel.core.formation import Formation, FormationPlan
from sentinel.core.kernel import advance_session
from sentinel.core.session import FeedAnchor, PublishedSession, SessionState
from sentinel.core.spinoffs import SpinoffDistribution, LIQUIDATE_CHILD_AT_OPEN
from sentinel.feed.rolling_contract import digest
from sentinel.strategy import production_strategy
from stock_strategy_shared.wealth_core.feed import DecisionMetadataTimelineBuilder, SecurityMeta
from .inputs import Inputs, START, END, TARGETS
from .spinoff_inputs import normalize as normalize_spinoff_inputs


def write(path, value):
    temporary = path.with_suffix(path.suffix+'.tmp')
    if path.suffix == '.gz':
        with gzip.open(temporary, 'wt', encoding='utf8', compresslevel=1) as f:
            json.dump(value, f, separators=(',', ':'), allow_nan=False)
    else:
        temporary.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False)+'\n', encoding='utf8')
    temporary.replace(path)


def assert_unreachable(state):
    held = {e['security_id'] for e in state.wealth_core['episodes'].values()}
    selected = set(state.median5['selected'])
    candidates = state.last_evidence.get('wealth_core', {}).get('candidates', ()) if state.last_evidence else ()
    reached = held | selected | {r['security_id'] for r in candidates
                                  if r.get('momentum') is not None or r.get('score') is not None}
    if reached & TARGETS:
        raise ValueError('research scope proof invalidated by economic reachability')


class FormedAccount(EconomicPath):
    def __init__(self):
        super().__init__('50000')
        # Select only the pure accounting branch. This object has no service,
        # database, origin receipt, publication, or promotion authority.
        self.warmup_input_identity = {'schema': formed_origin.SCHEMA}


def verify_economics(previous, result, state, published):
    """Independent Decimal recomputation from allocations, marks and ledger fees."""
    nav = D(previous['strategy_nav'])
    if previous['last_session'] is None:
        expected = nav
        if result['held_allocation'] is not None or not result['pending_allocation']:
            raise ValueError('first close must only create the pending allocation')
    else:
        new = D(previous['pending_allocation'])
        op, cl = D(result['parent_core_open_equity']), D(result['parent_core_close_equity'])
        bo, bc, bp = (D(result[k]) for k in ('bil_open_adjusted', 'bil_close_adjusted',
                                              'bil_previous_close_adjusted_current_publication'))
        if previous['held_allocation'] is None:
            opens = {b.security_id: D(str(b.raw_open)) for b in published.bars if b.raw_open is not None}
            invested = sum((D(str(e['current_shares']))*opens[e['security_id']]
                            for e in state.wealth_core['episodes'].values()), D(0))
            fees = sum((D(str(e['fees'])) for e in state.ledger['events']
                        if e['session'] == state.last_processed_session
                        and e['event_type'] in {'BUY','SELL'}), D(0))
            factor = 1 + new*((cl+fees)/op-1) + (1-new)*(bc/bo-1)
            factor -= D('.001')*(new*invested/op+1-new)
        else:
            old = D(previous['held_allocation'])
            prior_close = D(previous['parent_core_close_equity'])
            if old == new:
                factor = new*cl/prior_close + (1-new)*bc/bp
            else:
                overnight = 1 + old*(op/prior_close-1) + (1-old)*(bo/bp-1)
                intraday = 1 + new*(cl/op-1) + (1-new)*(bc/bo-1)
                factor = overnight*intraday*(1-D('.001')*abs(new-old))
        expected = nav*factor
    if abs(D(result['strategy_nav'])-expected) > D('0.00000001'):
        raise ValueError('independent funded accounting differs')


def supplements_for(data, path):
    records = load_supplements(path, {}, None)
    terminal = terminals(data.small_rows('terminal-events.csv.gz'))
    spins = distributions(data.small_rows('actions.csv.gz'))
    for row in records.values():
        day, sid = row['effective_session'], row['security_id']
        if row.get('kind') == 'SPINOFF':
            spins[day] = [r for r in spins.get(day, ()) if r.parent_security_id != sid] + [
                SpinoffDistribution(session=day, parent_ticker=row['ticker'], parent_security_id=sid,
                    child_ticker=row['child_ticker'], child_security_id=row['child_security_id'],
                    source_row_id=row['id'], value_evidence=row.get('value_evidence'),
                    child_shares_per_parent=row['child_shares_per_parent'], child_price=row.get('child_price'),
                    cash_in_lieu_price=row.get('cash_in_lieu_price'), policy=LIQUIDATE_CHILD_AT_OPEN)]
        else:
            terminal[day] = [r for r in terminal.get(day, ()) if r.security_id != sid] + terminals([row])[day]
    return records, terminal, spins


def checkpoint(output, packet):
    cursor = packet['state']['last_processed_session'] or 'warmup'
    path = output/f'checkpoint-{cursor}.json.gz'
    value = {**packet, 'packet_sha256': digest(packet)}
    write(path, value)
    pointer = dict(path=path.name, sha256=sha256(path), session=cursor)
    write(output/'latest-checkpoint.json', pointer)
    return pointer


def restore(pointer_path, binding):
    pointer = json.loads(pointer_path.read_text())
    if Path(pointer['path']).name != pointer['path']:
        raise ValueError('checkpoint pointer must name a local file')
    path = pointer_path.parent/pointer['path']
    if sha256(path) != pointer['sha256']:
        raise ValueError('checkpoint bytes changed')
    with gzip.open(path, 'rt', encoding='utf8') as f:
        packet = json.load(f)
    expected = packet.pop('packet_sha256')
    if digest(packet) != expected or packet['binding'] != binding:
        raise ValueError('checkpoint binding changed')
    state = SessionState.from_dict(packet['state'])
    if state.state_hash != packet['state_sha256']:
        raise ValueError('checkpoint state changed')
    return packet, state


def run(args):
    started = time.monotonic()
    args.output.mkdir(parents=True, exist_ok=False)
    def status(kind, **extra):
        value = dict(status=kind, elapsed_seconds=round(time.monotonic()-started, 2), **extra)
        write(args.output/'status.json', value)
        print(json.dumps(value), flush=True)
    status('VERIFYING_INPUTS')
    data = Inputs(args.inputs, args.scope_evidence)
    records, terminal, spins = supplements_for(data, args.supplements)
    certificate = Path(__file__).with_name('scope-certificate.json')
    proof = json.loads((args.scope_evidence/'current-code-reachability.json').read_text())
    if sha256(args.supplements) != proof['supplements_sha256']:
        raise ValueError('supplements differ from scope proof')
    harness = {p.name: sha256(p) for p in sorted(Path(__file__).parent.glob('*.py'))}
    binding = dict(source_certificate_sha256=sha256(certificate), harness=harness,
        capital='50000', start=START, end=END, supplements_sha256=sha256(args.supplements),
        source_status='FAIL', research_permission='CURRENT_CODE_SCOPE_PROVEN',
        identity_domain='RESEARCH_SEP_TAPE_SEC_ISSUER_FF12',
        metadata_policy='HISTORICAL_PIT_V1_WITH_RETAINED_RESEARCH_ASSUMPTIONS',
        limitations=['NOT_PROVIDER_PIT_CERTIFICATION','NO_GO_AUTHORITY','NO_BROKER_OR_NAS_QUALIFICATION'])
    config, identity = production_strategy()
    plan = FormationPlan(end='2006-07-28', capital='50000', strategy=identity, source_sha256=digest(binding))
    if plan.axis != data.axis[:378] or data.axis[378] != START:
        raise ValueError('formation schedule changed')
    write(args.output/'identity.json', dict(binding=binding, plan=plan.model_dump(by_alias=True),
                                           resumed_from=str(args.resume) if args.resume else None))
    cash_rows = list(data.small_rows('cash.csv.gz'))
    cash = {r['session']: r for r in cash_rows}
    if len(cash) != len(cash_rows) or any(d not in cash for d in data.axis):
        raise ValueError('cash schedule incomplete or duplicated')
    account = FormedAccount()
    classification = Classification()
    formation, state, receipt = None, None, None
    meta, sectors = {}, {}
    economics = dict(strategy_nav='50000', last_session=None, pending_allocation=None, held_allocation=None)
    count, measured, chain = 0, 0, digest(binding)
    if args.resume:
        packet, state = restore(args.resume, binding)
        meta = {sid: SecurityMeta(**r) for sid, r in packet['metadata'].items()}
        sectors, economics = packet['sectors'], packet['economics']
        count, measured, chain = packet['count'], packet['measured'], packet['chain']
        receipt = packet['formation_receipt']
        if packet['formation'] is not None:
            formation = Formation.resume(packet['formation'], plan=plan)
            if formation.state.state_hash != state.state_hash:
                raise ValueError('formation and checkpoint state differ')
        if count != 126 and formation is None:
            raise ValueError('checkpoint lost incomplete formation')
        assert_unreachable(state)

    def save():
        if state is None:
            return None
        return checkpoint(args.output, dict(binding=binding, state=state.to_dict(),
            state_sha256=state.state_hash, metadata={sid: asdict(m) for sid,m in meta.items()},
            sectors=sectors, economics=economics, count=count, measured=measured, chain=chain,
            formation=formation.checkpoint() if formation is not None else None,
            formation_receipt=receipt))

    timeline = DecisionMetadataTimelineBuilder(plan.axis[:252]) if state is None else None
    warm_bars = {}
    after = state.last_processed_session if state else None
    # A warmup-only checkpoint has no processed economic cursor.
    if state is not None and after is None:
        after = plan.axis[251]
    status('INPUTS_VERIFIED', research_only=True, source_status='FAIL', resumed_after=after)
    with (args.output/'daily.jsonl').open('x', encoding='utf8') as trace:
        for day, raw in data.sessions(after=after):
            raw, input_adjustments = normalize_spinoff_inputs(raw, spins.get(day, ()))
            rows = [classification.apply(r) for r in raw]
            next_meta, next_sectors = dict(meta), dict(sectors)
            for row in rows:
                next_meta[row['security_id']] = metadata(row)
                next_sectors[row['security_id']] = row['ff12'] or None
            bars = tuple(vendor(r) for r in rows)
            if state is None:
                meta, sectors = next_meta, next_sectors
                timeline.add_snapshot(day, dict(meta))
                warm_bars[day] = bars
                if day == plan.axis[251]:
                    status('BUILDING_WARMUP', session=day, sessions=252)
                    window = SimpleNamespace(sessions=plan.axis[:252], bars_by_session=warm_bars,
                        meta=meta, metadata_timeline=timeline.finish(),
                        median5_spy_closes={s:data.benchmark[s] for s in plan.axis[:252]},
                        median5_terminals={s:{t.security_id for t in terminal.get(s, ())} for s in plan.axis[:252]})
                    formation = Formation(plan, window, data_version=1)
                    state = formation.state
                    assert_unreachable(state)
                    save()
                    del window, timeline, warm_bars
                    status('WARMUP_COMPLETE', session=day, state_sha256=state.state_hash)
                continue
            ix = data.axis.index(day)
            spy_days = data.axis[max(0, ix-253):ix+1]
            published = PublishedSession(day, 1, bars, next_meta, next_sectors,
                spy_closeadj=[data.benchmark[d] for d in spy_days], spy_sessions=spy_days,
                spy_expected_sessions=spy_days, terminal_events=tuple(terminal.get(day, ())),
                spinoff_distributions=tuple(spins.get(day, ())),
                feed_anchors={b.security_id:FeedAnchor(b.security_id,b.ticker,
                    next_meta[b.security_id].issuer_key()[0],1.) for b in bars
                    if b.security_id not in state.feed['series']})
            formation_before = ((formation.state, formation.chain, formation.count)
                                if formation is not None else None)
            try:
                if count < 126:
                    candidate = formation.advance(published)
                    next_economics = economics
                else:
                    candidate = advance_session(state, published, controller_config=config, strategy_identity=identity)
                    gap, intraday = D(cash[day]['gap_factor']), D(cash[day]['intraday_factor'])
                    prices = dict(bil_open_signal=str(gap), bil_close_signal=str(gap*intraday),
                        bil_close_adjusted=str(gap*intraday), bil_close_unadjusted=str(gap*intraday),
                        bil_previous_close_adjusted='1', bil_previous_session=data.axis[ix-1])
                    marks = (formed_economics.opening_marks(candidate,published)
                             if economics['last_session'] is not None and economics['held_allocation'] is None else None)
                    next_economics = account.advance(previous=economics, state=candidate,
                        strategy_prices=prices, formed_startup_marks=marks)
                    verify_economics(economics, next_economics, candidate, published)
                assert_unreachable(candidate)
            except Exception as exc:
                if formation_before is not None:
                    formation.state, formation.chain, formation.count = formation_before
                saved = save()
                write(args.output/'failure.json', dict(session=day, error_type=type(exc).__name__,
                    error=str(exc), traceback=traceback.format_exc(), checkpoint=saved,
                    prior_state_sha256=state.state_hash, holdings=state.wealth_core['episodes']))
                status('REFUSED', session=day, error=str(exc), measured_sessions=measured, formation_sessions=count)
                raise
            state, economics, meta, sectors = candidate, next_economics, next_meta, next_sectors
            if count < 126:
                count += 1
                if count == 126:
                    cp = formation.checkpoint()
                    receipt = {k:v for k,v in cp.items() if k != 'state'}
                    write(args.output/'formation-complete.json', receipt)
                    formation = None
            else:
                measured += 1
            chain = digest(dict(previous=chain, normalized_input=digest(asdict(published)),
                                state=state.state_hash, economics=economics))
            row = dict(session=day, phase='MEASURED' if day >= START else 'FORMATION',
                state_sha256=state.state_hash, chain=chain, holdings=state.wealth_core['episodes'],
                decision=state.last_decision, evidence=state.last_evidence,
                ledger_events=[e for e in state.ledger['events'] if e['session'] == day],
                economics=economics if day >= START else None, spy=data.benchmark[day],
                input_adjustments=input_adjustments)
            trace.write(json.dumps(row, separators=(',', ':'), allow_nan=False)+'\n')
            trace.flush()
            if (count+measured)%20 == 0 or day in (plan.end, START, END):
                status('RUNNING', session=day, formation_sessions=count, measured_sessions=measured,
                       strategy_nav=economics['strategy_nav'], state_sha256=state.state_hash)
            if (count+measured)%50 == 0 or day in (plan.end, START, END):
                save()
            if time.monotonic()-started >= args.seconds:
                save()
                status('STOPPED_RESUMABLE', session=day, formation_sessions=count, measured_sessions=measured)
                return
    saved = save()
    if state is None or state.last_processed_session != END or count != 126 or measured != 5032:
        raise ValueError('incomplete requested replay')
    status('REPLAY_COMPLETE_PENDING_INDEPENDENT_REVIEW', session=END, formation_sessions=count,
           measured_sessions=measured, strategy_nav=economics['strategy_nav'], checkpoint=saved)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--scope-evidence', type=Path, required=True)
    parser.add_argument('--supplements', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--resume', type=Path)
    parser.add_argument('--seconds', type=int, default=21600)
    args = parser.parse_args()
    if not 0 < args.seconds <= 86400:
        parser.error('local research budget must be between 1 and 86400 seconds')
    try:
        run(args)
    except Exception as exc:
        if args.output.exists():
            path = args.output/'status.json'
            current = json.loads(path.read_text()) if path.exists() else {}
            if current.get('status') != 'REFUSED':
                write(path, dict(status='REFUSED', previous_stage=current.get('status'),
                    error_type=type(exc).__name__, error=str(exc)))
            write(args.output/'process-error.json', dict(error_type=type(exc).__name__,
                error=str(exc), traceback=traceback.format_exc()))
        raise
