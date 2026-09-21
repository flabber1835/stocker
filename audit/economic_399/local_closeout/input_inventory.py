"""Inspect pinned local Git inputs; never grant production publication authority."""
import argparse
import csv
import gzip
import hashlib
import io
import json
from pathlib import Path
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[3]
REF = 'e088bfd26c695309e259cfc44ab1e8982d6f858d'


def git(*args, **kwargs):
    return subprocess.run(['git', *args], cwd=ROOT, check=True, **kwargs)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scratch', type=Path, required=True)
    args = parser.parse_args()
    args.scratch.mkdir(parents=True, exist_ok=True)
    result = {'commit': REF, 'files': []}
    for name in ('sharadar/SHARADAR_TICKERS.zip', 'sharadar/SHARADAR_ACTIONS.zip'):
        raw = git('show', REF + ':' + name, stdout=subprocess.PIPE).stdout
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            member = archive.namelist()[0]
            with archive.open(member) as stream:
                reader = csv.DictReader(io.TextIOWrapper(stream))
                header = reader.fieldnames
                rows = list(reader) if 'TICKERS' in name else [next(reader)]
        result['files'].append(dict(path=name, bytes=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(), member=member, header=header))
        if 'TICKERS' in name:
            sys.path[:0] = [str(ROOT), str(ROOT / 'shared')]
            from sentinel.feed import tickers_authority, coherence
            try:
                checked = tickers_authority.validate(rows)
                coherence.assert_tickers_metadata(checked)
                result['tickers_structural_probe'] = dict(status='PASS', rows=len(checked))
            except (ValueError, RuntimeError) as exc:
                result['tickers_structural_probe'] = dict(
                    status='REFUSED', exception=type(exc).__name__, detail=str(exc))
    sfp = args.scratch / 'SFP.zip'
    with sfp.open('wb') as stream:
        for index in range(1, 5):
            git('show', f'{REF}:sharadar/SFP/SHARADAR_SFP.zip.{index:03}', stdout=stream)
    digest = hashlib.sha256()
    with sfp.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    expected = '8d2ebf7485977d9c40ec379eb33bd9d36d39d69db13602e5c51862d03172400c'
    assert digest.hexdigest() == expected, 'SFP differs from retained Phase-1 source manifest'
    counts = {}
    with zipfile.ZipFile(sfp) as archive:
        with archive.open(archive.namelist()[0]) as stream:
            reader = csv.DictReader(io.TextIOWrapper(stream))
            header = reader.fieldnames
            for row in reader:
                if row['ticker'] not in ('SPY', 'BIL'):
                    continue
                value = counts.setdefault(row['ticker'], dict(rows=0, first=row['date'], last=row['date']))
                value['rows'] += 1
                value['first'] = min(value['first'], row['date'])
                value['last'] = max(value['last'], row['date'])
    result['files'].append(dict(path='sharadar/SFP/SHARADAR_SFP.zip.001..004',
        bytes=sfp.stat().st_size, sha256=digest.hexdigest(), header=header, series=counts))
    sep = args.scratch / 'SEP2022.csv.gz'
    with sep.open('wb') as stream:
        git('show', REF + ':sharadar/SHARADAR_SEP_2022.csv.gz', stdout=stream)
    with gzip.open(sep, 'rt') as stream:
        header = next(csv.reader(stream))
    result['files'].append(dict(path='sharadar/SHARADAR_SEP_2022.csv.gz',
        bytes=sep.stat().st_size, sha256=hashlib.sha256(sep.read_bytes()).hexdigest(), header=header))
    result['admission'] = ('NOT_ESTABLISHED: file/Git provenance and structural validity '
        'do not supply export refresh-bracket evidence, complete API/CSV reference '
        'agreement or production publication/coverage receipts. No provider request made.')
    output = Path(__file__).with_name('raw-input-inventory.json')
    output.write_bytes((json.dumps(result, indent=2) + '\n').encode())
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
