"""Authenticated source-byte extraction only; no hypothetical holding arithmetic."""
from __future__ import annotations

import csv
import gzip
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import zipfile

ARCHIVE_SHA = 'c0a62a6bbb8b67f77a1fca34f5e836a36f90bdf67dd83e196ef3d3369a7925f6'
READER_SHA = '106105423b48ebac2872871801abf263e05f4cc10a2e40bf8cd799957e4ada23'


def need(value, code):
    if not value:
        raise ValueError(code)


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(encoded(value)).hexdigest()


def file_sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def load_original(book):
    path = Path('/stoprepo/research/concentration_stop/data.py')
    need(path.is_file() and file_sha(path) == READER_SHA, 'EXACT_PINNED_ORIGINAL_DATA_READER')
    spec = importlib.util.spec_from_file_location('pinned_original_data', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.load_book(book)


def load_corpus(archive, bundle, source, selected_keys):
    """Return lexical CSV rows on the predeclared bounded source calendar."""
    archive, bundle = Path(archive), Path(bundle)
    need(file_sha(archive) == ARCHIVE_SHA, 'EXACT_FROZEN_CORPUS_ARCHIVE')
    axis = [row['session'] for row in source['rows']]
    indices = {day: i for i, day in enumerate(axis)}
    windows, wanted = {}, {}
    for key in sorted(selected_keys):
        ep = source['episodes'][key]
        need(len(ep['sids']) == 1, 'SINGLE_SECURITY_SOURCE_WINDOW')
        if ep['endpoint_kind'] != 'SELL':
            windows[key] = dict(exit_index=None, endpoint_index=len(axis)-1,
                endpoint_session=axis[-1], complete_followup=False, sessions=[], prior_session=None)
            continue
        start = indices[ep['endpoint_session']]
        end = min(start+60, len(axis)-1)
        windows[key] = dict(exit_index=start, endpoint_index=end,
            endpoint_session=axis[end], complete_followup=start+60 < len(axis),
            sessions=axis[start:end+1], prior_session=axis[start-1])
        wanted.setdefault(ep['sids'][0], set()).update(axis[start-1:end+1])
    quotes = {sid: {} for sid in wanted}
    actions, terminals, partitions = [], [], {}
    with zipfile.ZipFile(archive) as zipped:
        years = sorted({day[:4] for days in wanted.values() for day in days})
        for year in years:
            member = 'observations-'+year+'.csv.gz'
            raw = zipped.read(member)
            partitions[member] = hashlib.sha256(raw).hexdigest()
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                for row in csv.DictReader(io.TextIOWrapper(stream, encoding='utf-8', newline='')):
                    sid, day = row['security_id'], row['session']
                    if sid in wanted and day in wanted[sid]:
                        need(day not in quotes[sid], 'UNIQUE_CORPUS_SECURITY_SESSION')
                        quotes[sid][day] = row
        for member, output in [('actions.csv.gz', actions), ('terminal-events.csv.gz', terminals)]:
            raw = zipped.read(member)
            partitions[member] = hashlib.sha256(raw).hexdigest()
            with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
                for row in csv.DictReader(io.TextIOWrapper(stream, encoding='utf-8', newline='')):
                    sid = row.get('security_id')
                    day = row.get('effective_session', row.get('session', row.get('terminal_session')))
                    if sid in wanted and day in wanted[sid]:
                        output.append(row)
    for sid, days in wanted.items():
        need(set(quotes[sid]) == days, 'COMPLETE_BOUNDED_SECURITY_QUOTES:'+sid)
    bundle_files = {str(p.relative_to(bundle)): file_sha(p) for p in sorted(bundle.rglob('*')) if p.is_file()}
    need(bool(bundle_files), 'AUTHENTICATED_CORPUS_BUNDLE_PRESENT')
    return dict(quotes=quotes, actions=actions, terminals=terminals, windows=windows,
        corpus_identity=dict(archive_sha256=ARCHIVE_SHA, original_data_sha256=READER_SHA,
            partitions=partitions, bundle_files=bundle_files,
            lexical_quotes_sha256=digest(quotes), actions_sha256=digest(actions),
            terminals_sha256=digest(terminals)))
