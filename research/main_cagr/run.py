"""Local current-main replay with cumulative month-end strategy and SPY metrics."""
from __future__ import annotations

import argparse
import csv
from decimal import Decimal
import importlib.metadata
import hashlib
import json
from pathlib import Path
import platform
import signal
import time
import traceback
from types import SimpleNamespace

from research.bounded_20y.run import EconomicPath
from sentinel import formed_economics, formed_origin
from sentinel.core.formation import Formation, FormationPlan
from sentinel.core.kernel import advance_session
from sentinel.core.session import SessionState
from sentinel.feed.rolling_contract import digest
from sentinel.strategy import production_strategy

from .inputs import BASE, BUNDLE, START, END, actions, axis, packets, sha256, verify
from .metrics import measure
from .runtime import Buffer, WarmupBars, observe_core
from .storage import append, checkpoint, restore, write_json
from .fractional import activate
from . import recovery, spinoff_repair


def source_hash(path):
    raw = path.read_bytes()
    if path.suffix.lower() in ('.py', '.json', '.md', '.csv', '.txt', '.toml', '.lock', '.yml', '.yaml'):
        raw = raw.replace(b'\r\n', b'\n')
    return hashlib.sha256(raw).hexdigest()


def verify_source(root):
    pinned = json.loads(Path(__file__).with_name('production-source.json').read_text())
    if pinned['revision'] != BASE:
        raise ValueError('production revision changed')
    for name, expected in pinned['files'].items():
        if source_hash(root/name) != expected:
            raise ValueError('production source changed: '+name)
    return pinned


def monthly(root, row):
    append(root, 'monthly.jsonl', row)
    columns = ['session', 'strategy_cagr', 'strategy_multiple', 'strategy_maxdd',
               'spy_cagr', 'spy_multiple', 'spy_maxdd']
    path = root/'monthly.csv'
    fresh = not path.exists() or path.stat().st_size == 0
    with path.open('a', encoding='utf8', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, lineterminator='\n')
        if fresh:
            writer.writeheader()
        flat = {'session':row['session']}
        for series in ('strategy', 'spy'):
            flat.update({series+'_'+key:row[series][key] for key in ('cagr', 'multiple', 'maxdd')})
        writer.writerow(flat)


def render(root):
    lines = ['# Fractional Wealth Core — monthly CAGR sanity check', '',
        'Cumulative from 2006-07-31 close. MaxDD is the largest loss from a prior daily-close peak.',
        'Historical modeled strategy; retained research input assumptions apply. Percentages are displayed below; CSV fractions are unscaled.', '',
        'Research fractional-entry profile derived from main, with Sentinel exposure accounting. All otherwise eligible shares are fractionable; fills use historical next-session opens and 10 bps costs per side.',
        'This is modeled performance, not Alpaca-reported fills or an unchanged-main certification.', '',
        '| Month end | Strategy CAGR | Multiple | MaxDD | SPY CAGR | Multiple | MaxDD |',
        '|---|---:|---:|---:|---:|---:|---:|']
    identity = json.loads((root/'identity.json').read_text())
    if identity['binding'].get('prospective_spinoff_repair'):
        lines[5:5] = ['Includes an explicit spin-off cash-in-lieu price/timing assumption; '
                      'see identity.json and recovery.json for its terms and preserved history.', '']
    if identity['binding'].get('prospective_terminal_repairs'):
        lines[5:5] = ['Includes source-backed prospective cash-merger corrections; '
                      'see identity.json and recovery.json for terms and checkpoint lineage.', '']
    path = root/'monthly.jsonl'
    if path.exists():
        for line in path.read_text().splitlines():
            row = json.loads(line)
            cells = [row['session']]
            for name in ('strategy', 'spy'):
                value = row[name]
                cells.extend(['—' if value['cagr'] is None else f"{value['cagr']:.2%}",
                    f"{Decimal(value['multiple']):.4f}×", f"{Decimal(value['maxdd']):.2%}"])
            lines.append('| '+' | '.join(cells)+' |')
    temporary = root/'monthly.md.tmp'
    temporary.write_text('\n'.join(lines)+'\n', encoding='utf8')
    temporary.replace(root/'monthly.md')


def run(args, variant):
    if args.recover_checkpoint and not args.recover_from:
        raise ValueError('selected checkpoint requires --recover-from')
    started = time.monotonic()
    root = args.output.resolve()
    if args.resume:
        if not root.is_dir():
            raise ValueError('resume output missing')
    else:
        root.mkdir(parents=True, exist_ok=False)
    def status(kind, **details):
        value = dict(status=kind, elapsed_seconds=round(time.monotonic()-started, 2), **details)
        write_json(root/'status.json', value)
        print(json.dumps(value), flush=True)

    status('VERIFYING')
    source = verify_source(Path.cwd())
    manifest = verify(args.bundle, args.archive)
    schedule, spins, repair_provenance = actions(args.bundle, args.repair)
    terminal_provenance = []
    if args.prospective_terminal_repair:
        schedule, _, complete_provenance = actions(args.bundle, [*args.repair, *args.prospective_terminal_repair])
        if complete_provenance[:len(repair_provenance)] != repair_provenance:
            raise ValueError('original terminal repair provenance changed')
        terminal_provenance = complete_provenance[len(repair_provenance):]
    spins, spin_repair = spinoff_repair.apply(spins, args.spinoff_repair)
    config, identity = production_strategy()
    identity = {**identity, 'research_fractional_profile':variant['profile'],
                'research_overlay_sha256':digest(variant)}
    days = axis()
    measurement = days[425:]
    if identity.get('startup_policy') != 'CURRENT_WINDOW_FORMATION_V1':
        raise ValueError('selected startup policy changed')
    source_identity = digest(dict(bundle=BUNDLE, repairs=repair_provenance))
    plan = FormationPlan(end=days[424], capital='50000', warmup_sessions=299,
        strategy=identity, source_sha256=source_identity,
        metadata_policy='CURRENT_INFORMATION_INITIALIZATION_V1')
    binding = dict(production=source, harness={p.name:sha256(p) for p in sorted(Path(__file__).parent.glob('*.py'))},
        source_identity=source_identity, bundle=BUNDLE, repairs=repair_provenance, variant=variant,
        strategy=identity, formation_plan=plan.model_dump(mode='json', by_alias=True),
        measurement_start=START, measurement_end=END, starting_cash='50000',
        python=platform.python_version(), packages={name:importlib.metadata.version(name)
            for name in ('numpy', 'pandas', 'pydantic', 'exchange-calendars')})
    if spin_repair:
        binding.update(prospective_spinoff_repair=spin_repair,
            effective_source_identity=digest(dict(predecessor=source_identity, spinoff_repair=spin_repair)))
    if terminal_provenance:
        binding.update(prospective_terminal_repairs=terminal_provenance,
            effective_source_identity=digest(dict(
                predecessor=binding.get('effective_source_identity', source_identity),
                terminal_repairs=terminal_provenance)))
    identity_doc = dict(binding=binding, limitations=manifest['limitations'],
        execution_policy_simulated=False,
        excluded_execution_policy='FRACTIONAL_MARKET_DAY_V1',
        source_status=manifest['source_status'], strict_pit_certified=False,
        mode='FRACTIONAL_CORE_RESEARCH_SANITY')
    if args.recover_from:
        recovery.fork(args.recover_from, root, identity_doc, args.recover_checkpoint)
    elif args.resume:
        if json.loads((root/'identity.json').read_text()) != identity_doc:
            raise ValueError('run identity changed')
    else:
        write_json(root/'identity.json', identity_doc)

    buffer = Buffer(binding.get('effective_source_identity', source_identity))
    iterator = iter(packets(args.bundle, args.archive, manifest, schedule, spins))
    economics = dict(strategy_nav='50000', last_session=None, pending_allocation=None, held_allocation=None)
    account = EconomicPath(50000)
    account.warmup_input_identity = {'schema':formed_origin.SCHEMA}
    metrics, totals = {}, {}
    measured, formation, state, cursor = 0, None, None, None
    stopped = False
    def stop(*_):
        nonlocal stopped
        stopped = True
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    def save():
        if state is None:
            return
        restored = SessionState.from_dict(state.to_dict())
        if restored.state_hash != state.state_hash:
            raise ValueError('canonical restart changed state')
        checkpoint(root, dict(binding=digest(binding), cursor=cursor,
            state=state.to_dict(), state_sha256=state.state_hash,
            formation=formation.checkpoint() if formation and not formation.complete else None,
            economics=economics, metrics=metrics, measured=measured, counters=totals))
        render(root)

    if args.resume or args.recover_from:
        saved, state = restore(root, binding)
        cursor, measured = saved['cursor'], saved['measured']
        economics, metrics, totals = saved['economics'], saved['metrics'], saved['counters']
        formation = Formation.resume(saved['formation'], plan=plan) if saved['formation'] else None
        for packet in iterator:
            buffer.append(packet)
            if packet.day == cursor:
                break
        else:
            raise ValueError('checkpoint outside source')
        status('RESUMED', session=cursor, measured_sessions=measured)
    else:
        for packet in iterator:
            buffer.append(packet)
            if len(buffer.axis) == 299:
                window = SimpleNamespace(sessions=plan.axis[:299], bars_by_session=WarmupBars(buffer),
                    meta=dict(buffer.metadata), median5_spy_closes=dict(zip(buffer.axis, buffer.spy)),
                    median5_terminals={day:{term.security_id for term in schedule.get(day, ())}
                                       for day in plan.axis[:299]})
                formation = Formation(plan, window, data_version=1)
                state, cursor = formation.state, packet.day
                save()
                status('WARMUP_COMPLETE', session=cursor, warmup_sessions=299)
                break
            if len(buffer.axis) % 50 == 0:
                status('LOADING_WARMUP', session=packet.day, warmup_sessions=len(buffer.axis))

    month_ends = {day for i, day in enumerate(measurement) if i == len(measurement)-1
                  or day[:7] != measurement[i+1][:7]} | {START}
    transitions = 0
    try:
        with observe_core() as audit:
            for packet in iterator:
                if stopped or (args.max_transitions and transitions >= args.max_transitions):
                    save()
                    status('PAUSED', session=cursor, measured_sessions=measured)
                    return 0
                buffer.append(packet)
                forming = formation is not None and not formation.complete
                published = buffer.prepare(state, 1 if forming else (state.data_version or 0)+1, formation=forming)
                if forming:
                    candidate = formation.advance(published)
                    state, cursor = candidate, packet.day
                    append(root, 'formation.jsonl', dict(session=cursor, state_sha256=state.state_hash,
                        count=formation.count, decision=state.last_decision, audit=dict(audit)))
                    if formation.count % 20 == 0 or formation.complete:
                        save()
                        status('FORMATION_COMPLETE' if formation.complete else 'FORMING',
                            session=cursor, formation_sessions=formation.count)
                    transitions += 1
                    continue

                candidate = advance_session(state, published, controller_config=config, strategy_identity=identity)
                cash = packet.cash
                if cash['source'] not in ('BIL', 'FRED_GS3M_STRICT_LAG'):
                    raise ValueError('unreviewed defensive return source')
                gap, intraday = Decimal(cash['gap_factor']), Decimal(cash['intraday_factor'])
                prices = dict(bil_open_signal=str(gap), bil_close_signal=str(gap*intraday),
                    bil_close_adjusted=str(gap*intraday), bil_close_unadjusted=str(gap*intraday),
                    bil_previous_close_adjusted='1', bil_previous_session=list(buffer.axis)[-2])
                marks = (formed_economics.opening_marks(candidate, published)
                    if economics['last_session'] is not None and economics['held_allocation'] is None else None)
                new_economics = account.advance(previous=economics, state=candidate,
                    strategy_prices=prices, formed_startup_marks=marks)
                if packet.day != measurement[measured]:
                    raise ValueError('measurement session gap')
                next_metrics, reports = {}, {}
                for name, value in (('strategy', new_economics['strategy_nav']), ('spy', packet.spy),
                                    ('core', candidate.shadow_nav_history[-1])):
                    next_metrics[name], reports[name] = measure(metrics.get(name), packet.day, value)
                # Commit only a fully resolved transition and its matching accounting.
                state, cursor, economics, metrics = candidate, packet.day, new_economics, next_metrics
                measured += 1
                transitions += 1
                for key, value in audit['counters'].items():
                    totals[key] = totals.get(key, 0) + value
                append(root, 'terminal-audit.jsonl', dict(session=cursor, **dict(audit)))
                for fill in audit['fills']:
                    append(root, 'fills.jsonl', fill)
                append(root, 'daily.jsonl', dict(session=cursor, state_sha256=state.state_hash,
                    strategy=reports['strategy'], spy=reports['spy'], core=reports['core'],
                    economics=economics, decision=state.last_decision,
                    held=len(state.wealth_core['episodes']), cash=state.wealth_core['cash'],
                    valuation=state.last_evidence['wealth_core'], terminal_counters=dict(audit['counters'])))
                if cursor in month_ends:
                    append(root, 'positions.jsonl', dict(session=cursor,
                        cash=state.wealth_core['cash'], episodes=state.wealth_core['episodes']))
                    row = dict(session=cursor, measured_sessions=measured, **reports,
                        terminal_counters=totals, terminal_audit='terminal-audit.jsonl')
                    monthly(root, row)
                    save()
                    status('MONTH_COMPLETE', **row)
                elif measured % 20 == 0:
                    save()
                    status('RUNNING', session=cursor, measured_sessions=measured)
        if cursor != END or measured != 5032:
            raise ValueError('historical path incomplete')
        save()
        verify_source(Path.cwd())
        result = dict(status='COMPLETE', session=cursor, measured_sessions=measured,
            final=json.loads((root/'monthly.jsonl').read_text().splitlines()[-1]),
            state_sha256=state.state_hash, source_unchanged=True)
        write_json(root/'result.json', result)
        status('COMPLETE', **{k:v for k,v in result.items() if k != 'status'})
        return 0
    except Exception:
        failure = dict(status='REFUSED', attempted_session=packet.day,
            last_completed_session=cursor, measured_sessions=measured, error=traceback.format_exc())
        write_json(root/'refusal.json', failure)
        save()
        status('REFUSED', **{k:v for k,v in failure.items() if k != 'status'})
        return 2


def parser():
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument('--bundle', type=Path, required=True)
    value.add_argument('--archive', type=Path, required=True)
    value.add_argument('--repair', type=Path, action='append', default=[])
    value.add_argument('--spinoff-repair', type=Path)
    value.add_argument('--prospective-terminal-repair', type=Path, action='append', default=[])
    value.add_argument('--recover-checkpoint')
    value.add_argument('--output', type=Path, required=True)
    continuation = value.add_mutually_exclusive_group()
    continuation.add_argument('--resume', action='store_true')
    continuation.add_argument('--recover-from', type=Path)
    value.add_argument('--max-transitions', type=int, default=0)
    return value


if __name__ == '__main__':
    args = parser().parse_args()
    try:
        with activate() as variant:
            code = run(args, variant)
    except Exception:
        failure = dict(status='STARTUP_REFUSED', error=traceback.format_exc())
        if args.output.is_dir():
            write_json(args.output/'startup-refusal.json', failure)
        print(json.dumps(failure), flush=True)
        code = 2
    raise SystemExit(code)
