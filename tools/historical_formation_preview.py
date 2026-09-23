"""Local preview from the retained research archive; no deployment authority.

Uses the production formation component. SEC identities and research metadata
assumptions are explicitly retained and never relabelled as Sharadar authority.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
import csv
import gzip
import io
import itertools
import json
from pathlib import Path
import time
from types import SimpleNamespace
import zipfile

from research.bounded_20y.inputs import BASE_ARCHIVE_SHA256, BASE_DATASET_SHA256, sha256
from research.bounded_20y.run import metadata, vendor, terminals, distributions
from research.economic_replay60.inputs import Classification, OVERLAY_SHA256
from sentinel.core.formation import Formation, FormationPlan
from sentinel.core.session import FeedAnchor
from sentinel.core.session import PublishedSession
from sentinel.core.spinoffs import SpinoffDistribution, LIQUIDATE_CHILD_AT_OPEN
from sentinel.feed.rolling_contract import digest
from sentinel.strategy import production_strategy
from stock_strategy_shared.wealth_core.feed import DecisionMetadataTimelineBuilder


def rows(archive, name):
    with archive.open(name) as binary, gzip.GzipFile(fileobj=binary) as compressed:
        yield from csv.DictReader(io.TextIOWrapper(compressed, encoding='utf-8'))


def write(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    if path.suffix == '.gz':
        with gzip.open(temporary, 'wt', encoding='utf-8', compresslevel=1) as stream:
            json.dump(value, stream, separators=(',', ':'), allow_nan=False)
    else:
        temporary.write_text(json.dumps(value, indent=2, allow_nan=False), encoding='utf-8')
    temporary.replace(path)


def run(args):
    started = time.monotonic()
    if sha256(args.archive) != BASE_ARCHIVE_SHA256:
        raise ValueError('retained archive bytes changed')
    supplements = json.loads(args.supplements.read_text(encoding='utf-8'))
    seen = set()
    for row in supplements:
        if (row['id'] in seen or not row.get('sources')
                or row['known_by'] > row['effective_session']
                or row['original_event_session'] > row['effective_session']):
            raise ValueError('supplement lacks retained unique causal evidence')
        seen.add(row['id'])
    source = dict(archive_sha256=BASE_ARCHIVE_SHA256, dataset_sha256=BASE_DATASET_SHA256,
        supplements_sha256=sha256(args.supplements), classification_sha256=OVERLAY_SHA256,
        identity_domain='RESEARCH_SEP_TAPE_SEC_ISSUER_FF12',
        limitations=['NOT_SHARADAR_IDENTITY', 'RESEARCH_CLASSIFICATION_ASSUMPTIONS',
                     'KNOWN_SILV_WARMUP_METADATA_ERROR', 'NO_GO_AUTHORITY'])
    cfg, identity = production_strategy()
    plan = FormationPlan(end='2026-07-31', capital='50000', strategy=identity, source_sha256=digest(source))
    axis = plan.axis
    args.output.mkdir(parents=True, exist_ok=args.resume)
    cp = args.output / 'checkpoint.json.gz'
    if args.resume:
        with gzip.open(cp, 'rt', encoding='utf-8') as stream:
            formed = Formation.resume(json.load(stream), plan=plan)
    else:
        formed = None
    write(args.output / 'source.json', source)
    write(args.output / 'plan.json', plan.model_dump(by_alias=True))
    classification = Classification()
    with zipfile.ZipFile(args.archive) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        if manifest['dataset_hash'] != BASE_DATASET_SHA256:
            raise ValueError('retained dataset differs')
        benchmark = {r['session']: float(r['level']) for r in rows(archive, 'benchmark.csv.gz')}
        terminal = terminals(rows(archive, 'terminal-events.csv.gz'))
        spin = distributions(rows(archive, 'actions.csv.gz'))
        for row in supplements:
            day, sid = row['effective_session'], row['security_id']
            if row.get('kind') == 'SPINOFF':
                spin[day] = [x for x in spin.get(day, ()) if x.parent_security_id != sid] + [
                    SpinoffDistribution(session=day, parent_ticker=row['ticker'], parent_security_id=sid,
                        child_ticker=row['child_ticker'], child_security_id=row['child_security_id'],
                        source_row_id=row['id'], value_evidence=row.get('value_evidence'),
                        child_shares_per_parent=row['child_shares_per_parent'], child_price=row.get('child_price'),
                        cash_in_lieu_price=row.get('cash_in_lieu_price'), policy=LIQUIDATE_CHILD_AT_OPEN)]
            else:
                terminal[day] = [x for x in terminal.get(day, ()) if x.security_id != sid] + terminals([row])[day]
        timeline = DecisionMetadataTimelineBuilder(axis[:252])
        warm_bars, meta, sectors = {}, {}, {}
        restored = formed is not None
        with (args.output / ('continuation.jsonl' if restored else 'daily.jsonl')).open('a', encoding='utf-8') as trace:
            for year in (2025, 2026):
                for day, raw in itertools.groupby(rows(archive, f'observations-{year}.csv.gz'), key=lambda r: r['session']):
                    if day < axis[0] or day > axis[-1]:
                        continue
                    batch = [classification.apply(r) for r in raw]
                    for r in batch:
                        meta[r['security_id']] = metadata(r)
                        sectors[r['security_id']] = r['ff12'] or None
                    if formed is not None and (day <= axis[251] or (
                            formed.state.last_processed_session is not None
                            and day <= formed.state.last_processed_session)):
                        continue
                    bars = tuple(vendor(r) for r in batch)
                    if day <= axis[251]:
                        timeline.add_snapshot(day, dict(meta)); warm_bars[day] = bars
                        if day == axis[251]:
                            window = SimpleNamespace(sessions=axis[:252], bars_by_session=warm_bars,
                                meta=meta, metadata_timeline=timeline.finish(),
                                median5_spy_closes={s: benchmark[s] for s in axis[:252]},
                                median5_terminals={s: {t.security_id for t in terminal.get(s, ())} for s in axis[:252]})
                            formed = Formation(plan, window, data_version=1)
                            write(cp, formed.checkpoint())
                            del window, timeline, warm_bars
                        continue
                    lo = max(0, axis.index(day) - 253)
                    spy_axis = axis[lo:axis.index(day) + 1]
                    published = PublishedSession(day, 1, bars, dict(meta), dict(sectors),
                        spy_closeadj=[benchmark[s] for s in spy_axis], spy_sessions=spy_axis,
                        spy_expected_sessions=spy_axis, terminal_events=tuple(terminal.get(day, ())),
                        spinoff_distributions=tuple(spin.get(day, ())),
                        feed_anchors={b.security_id: FeedAnchor(b.security_id, b.ticker,
                            meta[b.security_id].issuer_key()[0], 1.) for b in bars
                            if b.security_id not in formed.state.feed['series']})
                    try:
                        state = formed.advance(published)
                    except Exception as exc:
                        write(cp, formed.checkpoint())
                        write(args.output / 'status.json', dict(status='REFUSED', session=day,
                            error_type=type(exc).__name__, error=str(exc), completed=formed.count))
                        raise
                    status = dict(status='COMPLETE_NOT_ADMITTED' if formed.complete else 'RUNNING', session=day,
                        completed=formed.count, holdings=len(state.wealth_core['episodes']),
                        target=state.last_decision['target_core_exposure'], state_sha256=state.state_hash,
                        elapsed_seconds=round(time.monotonic()-started, 2))
                    trace.write(json.dumps(status)+'\n'); trace.flush()
                    write(args.output / 'status.json', status)
                    if formed.count % 10 == 0 or formed.complete:
                        write(cp, formed.checkpoint()); print(json.dumps(status), flush=True)
                    if time.monotonic()-started >= args.seconds and not formed.complete:
                        write(cp, formed.checkpoint())
                        write(args.output / 'status.json', {**status, 'status': 'PAUSED_BUDGET'})
                        return
        if formed is None or not formed.complete:
            raise ValueError('archive did not complete the requested formation axis')


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--archive', type=Path, required=True)
    p.add_argument('--supplements', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--seconds', type=int, default=1800)
    p.add_argument('--resume', action='store_true')
    run(p.parse_args())
