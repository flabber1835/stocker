"""Hash-bound retained files, including explicitly retained research assumptions."""
from collections import defaultdict
from dataclasses import asdict, dataclass
import csv
import gzip
import hashlib
import io
import itertools
import json
from pathlib import Path
import sys
import zipfile

from research.bounded_20y.run import metadata, vendor, terminals, distributions
from research.economic_replay60.inputs import Classification
from sentinel.core.spinoffs import LIQUIDATE_CHILD_AT_OPEN, SpinoffDistribution
from sentinel.feed.calendar import sessions_in_range
from sentinel.feed.rolling_contract import digest
from stock_strategy_shared.wealth_core.terminal import TerminalTerms, TerminalKind

BASE = '566a36819d7aec0d9f64cebf281fc9c20c5e086b'
BUNDLE = '8424b034be9ae0caffd1dc0a8e728854e691bd375d87ddb1d8807453026d7fff'
ARCHIVE = 'c0a62a6bbb8b67f77a1fca34f5e836a36f90bdf67dd83e196ef3d3369a7925f6'
DATASET = '5bdc6b39e4a8ec4d3e4cebba6091b18a8b4032b41509581366bb60c0d0600993'
START, END = '2006-07-31', '2026-07-31'


def sha256(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def axis():
    days = sessions_in_range('2004-11-19', END)
    if len(days) != 5457 or days[425] != START:
        raise ValueError('historical calendar changed')
    return days


def verify(bundle, archive):
    bundle = Path(bundle).resolve()
    manifest = json.loads((bundle/'manifest.json').read_text())
    raw = {k:v for k,v in manifest.items() if k != 'bundle_commitment_sha256'}
    if digest(raw) != BUNDLE or manifest['bundle_commitment_sha256'] != BUNDLE:
        raise ValueError('prepared manifest binding changed')
    if manifest['strict_pit_certified'] is not False:
        raise ValueError('research source authority changed')
    for name, expected in manifest['members'].items():
        path = (bundle/name).resolve()
        if (bundle not in path.parents or not path.is_file()
                or path.stat().st_size != expected['bytes'] or sha256(path) != expected['sha256']):
            raise ValueError('prepared member changed: '+name)
    if (Path(archive).stat().st_size != manifest['base_archive']['bytes']
            or sha256(archive) != ARCHIVE):
        raise ValueError('archive binding changed')
    with zipfile.ZipFile(archive) as source:
        base = json.loads(source.read('manifest.json'))
        if base['dataset_hash'] != DATASET or base['status'] != 'PASS':
            raise ValueError('canonical dataset changed')
    return manifest


def rows(path):
    with gzip.open(path, 'rt', encoding='utf8', newline='') as stream:
        yield from csv.DictReader(stream)


def archive_rows(archive, member):
    with archive.open(member) as raw, gzip.GzipFile(fileobj=raw) as compressed:
        with io.TextIOWrapper(compressed, encoding='utf8', newline='') as stream:
            yield from csv.DictReader(stream)


def apply_repair(schedule, repair):
    """Apply an exact data correction only to a fresh scenario's input schedule."""
    result = {day:list(terms) for day, terms in schedule.items()}
    if repair.get('schema') != 'terminal-repair/1' or not repair.get('source_evidence'):
        raise ValueError('source-backed terminal repair required')
    for row in repair['suppress']:
        terms = result.get(row['session'], [])
        matching = [term for term in terms if term.security_id == row['security_id']]
        if len(matching) != 1 or digest(asdict(matching[0])) != row['term_sha256']:
            raise ValueError('suppressed terminal identity changed')
        result[row['session']] = [term for term in terms if term.security_id != row['security_id']]
    for row in repair['add']:
        term = TerminalTerms(**{**row, 'kind': TerminalKind(row['kind'])})
        if not term.completeness(0)[0]:
            raise ValueError('incomplete replacement terminal')
        terms = result.setdefault(term.session, [])
        if any(t.security_id == term.security_id for t in terms):
            raise ValueError('duplicate replacement terminal')
        terms.append(term)
    return result


def actions(bundle, repairs):
    bundle = Path(bundle)
    schedule = terminals(json.loads((bundle/'terminal-schedule.json').read_text()))
    provenance = []
    for path in repairs:
        path = Path(path)
        repair = json.loads(path.read_text())
        hashes = {sha256(p) for p in path.parent.glob('*.html')}
        retained = [row['sha256'] for row in repair['source_evidence'] if row.get('sha256')]
        if not retained or any(value not in hashes for value in retained):
            raise ValueError('retained primary evidence missing: '+str(path))
        schedule = apply_repair(schedule, repair)
        provenance.append(dict(name=path.parent.name, sha256=sha256(path), document=repair))
    spins = defaultdict(list)
    for row in json.loads((bundle/'supplements.json').read_text()):
        if row.get('kind') == 'SPINOFF':
            spins[row['effective_session']].append(SpinoffDistribution(
                session=row['effective_session'], parent_ticker=row['ticker'],
                parent_security_id=row['security_id'], child_ticker=row['child_ticker'],
                child_security_id=row['child_security_id'], source_row_id=row['id'],
                value_evidence=row.get('value_evidence'), child_shares_per_parent=row['child_shares_per_parent'],
                child_price=row.get('child_price'), cash_in_lieu_price=row.get('cash_in_lieu_price'),
                policy=LIQUIDATE_CHILD_AT_OPEN))
    return schedule, spins, provenance


@dataclass(frozen=True)
class Packet:
    day: str
    bars: tuple
    meta: dict
    sectors: dict
    spy: str
    cash: dict
    terminal: tuple
    spins: tuple


def packets(bundle, archive_path, manifest, schedule, spins):
    bundle = Path(bundle)
    classifier = Classification()
    overlay = {(r['session'], r['security_id']):r for r in
               json.loads((bundle/'spinoff-proxy-overlay.json').read_text())}
    if len(overlay) != 4:
        raise ValueError('spinoff cash-proxy overlay changed')
    applied = set()
    benchmark = {r['session']:r['level'] for r in rows(bundle/'benchmark.csv.gz')}
    cash = {r['session']:r for r in rows(bundle/'cash.csv.gz')}
    expected, observed, metadata_cache = axis(), [], {}
    with zipfile.ZipFile(archive_path) as archive:
        raw_spins = distributions(archive_rows(archive, 'actions.csv.gz'))
        for day, reviewed in spins.items():
            parents = {r.parent_security_id for r in reviewed}
            raw_spins[day] = [r for r in raw_spins.get(day, ()) if r.parent_security_id not in parents]+reviewed
        for partition in manifest['observation_partitions']:
            source = (rows(bundle/partition['path']) if 'path' in partition else
                      archive_rows(archive, partition['archive_member']))
            for day, group in itertools.groupby(source, lambda r:r['session']):
                if len(observed) >= len(expected) or day != expected[len(observed)]:
                    raise ValueError('source session gap or duplicate: '+day)
                observed.append(day)
                bars, meta, sectors, symbols = [], {}, {}, set()
                for original in group:
                    key = (day, original['security_id'])
                    if key in overlay:
                        original = overlay[key]
                        applied.add(key)
                    row = classifier.apply(original)
                    sid, ticker = sys.intern(row['security_id']), sys.intern(row['ticker'])
                    row = {**row, 'security_id':sid, 'ticker':ticker}
                    if sid in meta or ticker in symbols or row['listing_first_session'] > day:
                        raise ValueError('duplicate/future source identity')
                    symbols.add(ticker)
                    cache_key = (sid, ticker, row['security_type_eligible'], row['issuer_id'], row['listing_first_session'] or day)
                    if cache_key not in metadata_cache:
                        metadata_cache[cache_key] = metadata(row)
                    meta[sid] = metadata_cache[cache_key]
                    sectors[sid] = row['ff12'] or None
                    bars.append(vendor(row))
                yield Packet(day, tuple(bars), meta, sectors, benchmark[day], cash[day],
                             tuple(schedule.get(day, ())), tuple(raw_spins.get(day, ())))
    if observed != expected or applied != set(overlay):
        raise ValueError('source axis or spinoff overlay incomplete')
