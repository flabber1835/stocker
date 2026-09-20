"""Stream a pinned historical artifact for integrity/workload facts, not admission."""
import argparse
from collections import Counter
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
import time
import zipfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--archive-sha256', required=True)
    parser.add_argument('--pointer', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    started = time.monotonic()
    pointer = json.loads(args.pointer.read_text())
    with args.archive.open('rb') as stream:
        archive_hash = hashlib.file_digest(stream, 'sha256').hexdigest()
    assert archive_hash == args.archive_sha256, 'archive digest mismatch'
    observations = Counter()
    securities = set()
    counts = {}
    headers = {}
    with zipfile.ZipFile(args.archive) as archive:
        raw = archive.read('manifest.json')
        assert hashlib.sha256(raw).hexdigest() == pointer['manifest_sha256']
        manifest = json.loads(raw)
        for key in ('dataset_hash', 'reconstruction_code_sha', 'window', 'counts', 'status'):
            assert manifest[key] == pointer[key], key
        members = manifest['members']
        names = archive.namelist()
        assert len(names) == len(set(names))
        assert set(names) == {*members, 'manifest.json', 'SHA256SUMS.txt'}
        assert all(Path(name).name == name for name in names)
        sums = dict((name, digest) for digest, name in
                    (line.split('  ', 1) for line in archive.read('SHA256SUMS.txt').decode().splitlines()))
        assert set(sums) == {*members, 'manifest.json'}
        assert sums['manifest.json'] == pointer['manifest_sha256']
        aggregate = hashlib.sha256()
        for name, spec in sorted(members.items()):
            assert archive.getinfo(name).file_size == spec['bytes'], name
            with archive.open(name) as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            assert digest == spec['sha256'] == sums[name], name
            aggregate.update(f'{name}\0{digest}\0{spec["bytes"]}\n'.encode())
            with archive.open(name) as raw_stream:
                stream = gzip.GzipFile(fileobj=raw_stream) if name.endswith('.gz') else raw_stream
                with io.TextIOWrapper(stream, encoding='utf-8', newline='') as text:
                    reader = csv.reader(text)
                    header = next(reader)
                    headers[name] = header
                    count = 0
                    previous = None
                    for row in reader:
                        assert len(row) == len(header), (name, count)
                        count += 1
                        if name.startswith('observations-'):
                            day, sid, ticker = row[0:3]
                            assert day[:4] == name[13:17], name
                            key = (day, ticker, sid)
                            assert previous is None or key > previous, (name, key)
                            previous = key
                            observations[day] += 1
                            securities.add(sid)
            assert count == spec['rows'], (name, count, spec['rows'])
            counts[name] = count
            print(json.dumps({'member': name, 'rows': count, 'bytes': spec['bytes'],
                              'sha256': digest, 'seconds': time.monotonic()-started}), flush=True)
        assert aggregate.hexdigest() == pointer['dataset_hash']
    assert sum(observations.values()) == manifest['counts']['observation_rows']
    assert len(securities) == manifest['counts']['security_count']
    ordered = [observations[day] for day in sorted(observations)]
    rolling = sum(ordered[:300])
    maximum = rolling
    for index in range(300, len(ordered)):
        rolling += ordered[index] - ordered[index-300]
        maximum = max(maximum, rolling)
    result = {'scope': 'ARTIFACT_INTEGRITY_AND_WORKLOAD_ONLY_NOT_ECONOMIC_CERTIFICATION',
              'archive_sha256': archive_hash, 'dataset_hash': pointer['dataset_hash'],
              'schema': manifest['schema'], 'counts': manifest['counts'],
              'window': manifest['window'], 'member_rows_verified': counts,
              'headers': headers, 'max_observed_rows_per_session': max(ordered),
              'max_observation_rows_in_300_observed_sessions': maximum,
              'first_observed_session': min(observations), 'last_observed_session': max(observations),
              'observed_session_count': len(observations), 'seconds': time.monotonic()-started}
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    main()
