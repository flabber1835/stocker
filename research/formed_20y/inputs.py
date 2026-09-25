"""Exact retained research inputs; strict production admission stays unchanged."""
from __future__ import annotations

import csv
import gzip
import hashlib
import io
import itertools
import json
from pathlib import Path
import zipfile

from research.bounded_20y.inputs import (
    BASE_ARCHIVE_SHA256, BASE_DATASET_SHA256, sha256, stitch_benchmark,
    SFP_SOURCE, validate_manifest)
from sentinel.feed.calendar import previous_sessions

START, END = '2006-07-31', '2026-07-31'
PREFIX_SHA = '14e0408c4432017a88e2d9cdff92a971c7e7d00ef615fb02a2ced0d70f18a061'
PREFIX_DATASET = '330a8a88a8c1a08e72d93e70f1fe5227a0e56eb08ac92e80dc48b7b9e6b6b896'
TARGETS = frozenset({'750813509120092497', '506347706538298975'})
CONFLICTS = [
    dict(ticker='FCEC', session='2005-04-28', applied_ratio=1., derived=1.,
         disposition='unresolved', stated=1.1),
    dict(ticker='FSNMQ', session='2005-02-09', applied_ratio=1., derived=1.,
         disposition='unresolved', stated=2.),
]


def verify_runtime(root: Path, certificate: dict):
    if certificate['reviewed_revision'] != 'f3e60671b525219287231d517ad6945e6ef2b649':
        raise ValueError('scope proof names another production revision')
    for name, expected in certificate['runtime_files'].items():
        if sha256(root / name) != expected:
            raise ValueError('reviewed production source changed: ' + name)
    for name, expected in certificate['proof_programs'].items():
        if Path(name).name != name or sha256(Path(__file__).parent/name) != expected:
            raise ValueError('reviewed scope program changed: ' + name)


def verify_scope(evidence: Path, certificate: dict):
    if certificate['status'] != 'RESEARCH_ONLY' or certificate['source_status'] != 'FAIL':
        raise ValueError('scope cannot confer source admission')
    for name, expected in certificate['evidence_files'].items():
        if Path(name).name != name or sha256(evidence / name) != expected:
            raise ValueError('scope evidence bytes changed: ' + name)
    proof = json.loads((evidence/'current-code-reachability.json').read_text())
    if (proof['status'] != 'PASS_DIAGNOSTIC' or proof['incoming']
            or proof['source_admission_changed'] or proof['source_status'] != 'FAIL'
            or proof['sessions'] != 5410):
        raise ValueError('scope obligations incomplete')
    signatures = set()
    for variant in proof['variants'].values():
        if (any(variant['eligible_days'].get(sid) for sid in TARGETS)
                or len(variant['eligible_days'].get('CONTROL', ())) != 5284):
            raise ValueError('scope target reachable or positive control absent')
        signatures.add(variant['consumed_sha256'])
    if len(signatures) != 1 or set(proof['variants']) != {'original', 'stated_ratio', 'perturbed_signal'}:
        raise ValueError('scope counterfactual consumption differs')
    for kind in ('adv20', 'both'):
        refusal = json.loads((evidence/f'reachability-refusal-{kind}.json').read_text())
        if (refusal['status'] != 'REFUSED' or refusal['reason'] != 'TARGET_BECAME_ELIGIBLE'
                or not TARGETS.intersection(refusal['identities'])):
            raise ValueError('scope guard-removal control not killed')


def verify_failed_prefix(prefix: Path):
    if sha256(prefix/'manifest.json') != PREFIX_SHA:
        raise ValueError('unreviewed prefix manifest')
    manifest = json.loads((prefix/'manifest.json').read_text())
    if (manifest['status'] != 'FAIL' or manifest['dataset_hash'] != PREFIX_DATASET
            or manifest['blockers'] != {'unresolved_corporate_actions': CONFLICTS}
            or manifest['counts']['unresolved_corporate_actions'] != 2):
        raise ValueError('prefix exception set changed')
    # Do not alter status or pass a fabricated PASS manifest to the strict reader.
    commitment = hashlib.sha256()
    for name, expected in sorted(manifest['members'].items()):
        if Path(name).name != name or '/' in name or '\\' in name:
            raise ValueError('invalid prefix member path')
        path = prefix/name
        observed = sha256(path)
        if path.stat().st_size != expected['bytes'] or observed != expected['sha256']:
            raise ValueError('prefix member bytes changed: ' + name)
        commitment.update(f"{name}\0{observed}\0{expected['bytes']}\n".encode())
    if commitment.hexdigest() != PREFIX_DATASET:
        raise ValueError('prefix dataset commitment changed')
    return manifest


class Inputs:
    def __init__(self, root, evidence):
        root, evidence = Path(root), Path(evidence)
        self.root = root
        self.certificate = json.loads(Path(__file__).with_name('scope-certificate.json').read_text())
        verify_runtime(Path(__file__).resolve().parents[2], self.certificate)
        verify_scope(evidence, self.certificate)
        self.prefix = root/'pit-prefix-evidence/canonical-2005'
        self.prefix_manifest = verify_failed_prefix(self.prefix)
        archive = root/'pit-source-5bdc6b39.zip'
        if sha256(archive) != BASE_ARCHIVE_SHA256:
            raise ValueError('base archive changed')
        self.archive = zipfile.ZipFile(archive)
        if len(self.archive.namelist()) != len(set(self.archive.namelist())):
            raise ValueError('duplicate archive member')
        self.base = json.loads(self.archive.read('manifest.json'))
        if self.base['dataset_hash'] != BASE_DATASET_SHA256:
            raise ValueError('base dataset changed')
        validate_manifest(self.base, self.archive.read)
        sfp = root/'pit-prefix-source'/SFP_SOURCE
        sfp_hash = sha256(sfp)
        if any(m['source_files'][SFP_SOURCE]['sha256'] != sfp_hash
               for m in (self.base, self.prefix_manifest)):
            raise ValueError('benchmark source changed')
        with gzip.open(sfp, 'rt', encoding='utf8', newline='') as f:
            bridge = [r for r in csv.DictReader(f) if r['ticker'] == 'SPY' and r['date'] == '2006-01-03']
        if len(bridge) != 1:
            raise ValueError('benchmark boundary is not unique')
        bench = stitch_benchmark(list(self.rows('benchmark.csv.gz', True)),
                                 list(self.rows('benchmark.csv.gz')),
                                 bridge[0]['close_to_close_factor'])
        self.benchmark = {r['session']: float(r['level']) for r in bench}
        if len(self.benchmark) != len(bench):
            raise ValueError('duplicate benchmark session')
        self.axis = [s for s in previous_sessions(END, 6000) if s >= '2005-01-28']
        if len(self.axis) != 5410 or any(s not in self.benchmark for s in self.axis):
            raise ValueError('incomplete research session axis')

    def rows(self, member, prefix=False):
        binary = (self.prefix/member).open('rb') if prefix else self.archive.open(member)
        with binary, gzip.GzipFile(fileobj=binary) as gz:
            yield from csv.DictReader(io.TextIOWrapper(gz, encoding='utf8', newline=''))

    def small_rows(self, member):
        yield from self.rows(member, True)
        yield from self.rows(member)

    def sessions(self, after=None):
        expected = [s for s in self.axis if after is None or s > after]
        index = 0
        for year in range(int((after or self.axis[0])[:4]), 2027):
            for day, group in itertools.groupby(self.rows(f'observations-{year}.csv.gz', year == 2005),
                                                key=lambda r: r['session']):
                if day < self.axis[0] or (after and day <= after):
                    continue
                if index >= len(expected) or day != expected[index]:
                    raise ValueError('nonadjacent observation session: ' + day)
                batch = list(group)
                if len({r['security_id'] for r in batch}) != len(batch):
                    raise ValueError('duplicate observation identity: ' + day)
                index += 1
                yield day, batch
        if index != len(expected):
            raise ValueError('incomplete full observation schedule')
