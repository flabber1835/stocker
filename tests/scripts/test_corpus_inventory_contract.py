"""Actual inventory/readers against disposable synthetic corpus bytes only.

The recovered corpus pins are read unchanged. Private test manifests verify
generic inventory behavior; no reference pin, historical book or corpus changes.
"""
import gzip
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import runpy
import sys
import zipfile

import pytest

ROOT = Path(os.environ.get('SENTINEL_REPO_ROOT', Path(__file__).resolve().parents[2]))
SOURCE = ROOT/'scripts/sentinel-corpus-inventory.py'
spec = importlib.util.spec_from_file_location('corpus_inventory_contract', SOURCE)
inventory = importlib.util.module_from_spec(spec)
spec.loader.exec_module(inventory)
METADATA = ('SHARADAR_TICKERS.zip', 'SHARADAR_ACTIONS.zip', 'SHARADAR_SFP.zip')
YEARS = ('SHARADAR_SEP_1998.csv.gz', 'SHARADAR_SEP_1999.csv.gz')
CSV = 'ticker,date,close\nBIL,1998-02-02,100\nSPY,1998-01-02,200\nBIL,1998-02-01,101\n'


def zip_csv(path, text=CSV, *, members=None):
    with zipfile.ZipFile(path, 'w') as archive:
        for name, payload in (members or {'table.csv': text}).items():
            archive.writestr(name, payload)
    return path


def gzip_csv(path, text=CSV):
    path.write_bytes(gzip.compress(text.encode(), mtime=0))
    return path


def corpus(tmp_path):
    root = tmp_path/'corpus'
    root.mkdir()
    for name in METADATA:
        zip_csv(root/name)
    for name in YEARS:
        gzip_csv(root/name)
    pins = {name: hashlib.sha256((root/name).read_bytes()).hexdigest() for name in (*METADATA, *YEARS)}
    return root, pins


def invoke(monkeypatch, root, output, pins, *, deep=False):
    monkeypatch.setattr(inventory, 'pinned_hashes', lambda: dict(pins))
    monkeypatch.setattr(sys, 'argv', [str(SOURCE), '--sharadar', str(root), '--out', str(output)]
        + (['--deep'] if deep else []))
    assert inventory.main() == 0
    return json.loads(output.read_text())


def test_reference_hash_table_is_read_without_repinning():
    pins = inventory.pinned_hashes()
    assert len(pins) == 32 and all(len(value) == 64 for value in pins.values())
    assert set(METADATA) <= pins.keys()


def test_hash_table_parser_has_no_fabricated_fallback(tmp_path):
    source = tmp_path/'reference.py'
    source.write_text("EXPECTED_HASHES = {'one.zip':'" + '1'*64 + "'}\n")
    assert inventory.pinned_hashes(source) == {'one.zip': '1'*64}
    source.write_text("EXPECTED_HASHES = {'one.zip':'not-sha'}\n")
    with pytest.raises(SystemExit, match='no pinned hashes'):
        inventory.pinned_hashes(source)
    source.write_text('NO_HASH_TABLE = {}\n')
    with pytest.raises(ValueError):
        inventory.pinned_hashes(source)


@pytest.mark.parametrize('content', [b'', b'one byte stream', b'\x00\xff'*21])
def test_streamed_hash_matches_exact_bytes_over_many_chunks(tmp_path, content):
    path = tmp_path/'source'
    path.write_bytes(content)
    assert inventory.sha256(path, chunk=3) == hashlib.sha256(content).hexdigest()


def test_unsorted_dates_missing_dates_and_ticker_cardinality_are_reported(tmp_path):
    path = gzip_csv(tmp_path/'year.gz', CSV + 'X,,5\nSPY,1997-12-31,7\nX,1999-01-01,8\n')
    assert inventory.sep_date_range(path) == {'first_date': '1997-12-31',
        'last_date': '1999-01-01', 'rows': 5, 'distinct_tickers': 3}
    date_only = gzip_csv(tmp_path/'date-only.gz', 'date\n2000-01-01\n')
    assert inventory.sep_date_range(date_only)['distinct_tickers'] == 1


@pytest.mark.parametrize('text,columns', [('', None), ('ticker,close\nX,1\n', ['ticker', 'close'])])
def test_missing_date_header_is_an_explicit_report_error(tmp_path, text, columns):
    path = gzip_csv(tmp_path/'year.gz', text)
    assert inventory.sep_date_range(path) == {'error': 'no date column', 'columns': columns}


@pytest.mark.parametrize('raw', [b'not gzip', gzip.compress(b'ticker,date\nX,\xff\n', mtime=0)])
def test_corrupt_or_nontext_year_is_reported_without_success(tmp_path, raw):
    path = tmp_path/'year.gz'
    path.write_bytes(raw)
    result = inventory.sep_date_range(path)
    assert set(result) == {'error'} and result['error']


def test_empty_year_does_not_invent_a_date_range(tmp_path):
    path = gzip_csv(tmp_path/'year.gz', 'ticker,date\n')
    assert inventory.sep_date_range(path) == {'first_date': None, 'last_date': None,
        'rows': 0, 'distinct_tickers': 0}


def test_ticker_cardinality_is_bounded_while_dates_and_rows_continue(tmp_path):
    text = 'ticker,date\n' + ''.join(f'X{i},2000-01-01\n' for i in range(200001))
    path = gzip_csv(tmp_path/'bounded-year.gz', text + 'LATE,2001-01-01\n')
    result = inventory.sep_date_range(path)
    assert result == {'first_date': '2000-01-01', 'last_date': '2001-01-01',
        'rows': 200002, 'distinct_tickers': 200000}


@pytest.mark.parametrize('members', [
    {'README.txt': 'no CSV'}, {'one.csv': CSV, 'two.CSV': CSV},
])
def test_zip_ambiguity_is_reported_instead_of_selecting_a_member(tmp_path, members):
    path = zip_csv(tmp_path/'table.zip', members=members)
    result = inventory.zip_csv_info(path)
    assert set(result) == {'error'} and 'expected one CSV' in result['error']


@pytest.mark.parametrize('raw', [b'not zip', b''])
def test_corrupt_zip_reports_its_read_failure(tmp_path, raw):
    path = tmp_path/'table.zip'
    path.write_bytes(raw)
    result = inventory.zip_csv_info(path)
    assert set(result) == {'error'} and 'BadZipFile' in result['error']


def test_zip_counts_and_missing_sleeve_tickers_are_explicit(tmp_path):
    path = zip_csv(tmp_path/'table.zip', 'ticker,date\nSPY,2000-01-01\nOTHER,2000-01-01\n')
    ordinary = inventory.zip_csv_info(path)
    assert ordinary == {'inner_csv': 'table.csv', 'columns': ['ticker', 'date'], 'rows': 2}
    selected = inventory.zip_csv_info(path, {'SPY', 'BIL'})
    assert selected['wanted_ticker_rows'] == {'SPY': 1} and selected['missing_wanted'] == ['BIL']
    assert selected['rows'] == 2


def test_zip_bad_utf8_is_not_mistaken_for_an_empty_table(tmp_path):
    path = zip_csv(tmp_path/'bad.zip', members={'table.csv': b'ticker\n\xff\n'})
    assert 'UnicodeDecodeError' in inventory.zip_csv_info(path)['error']


@pytest.mark.parametrize('blocked', ['not-directory', 'incomplete-promotion'])
def test_main_refuses_unavailable_or_half_promoted_corpus(monkeypatch, tmp_path, blocked):
    root = tmp_path/'corpus'
    if blocked == 'incomplete-promotion':
        root.mkdir()
        (root/'.sentinel-sep-promotion.json').write_text('{}')
    output = tmp_path/'never.json'
    monkeypatch.setattr(sys, 'argv', [str(SOURCE), '--sharadar', str(root), '--out', str(output)])
    with pytest.raises(SystemExit, match='not a directory' if blocked == 'not-directory' else 'incomplete'):
        inventory.main()
    assert not output.exists()


@pytest.mark.parametrize('deep', [False, True])
@pytest.mark.parametrize('bulk', [False, True])
def test_complete_per_year_corpus_is_never_reported_as_bulk_only(monkeypatch, tmp_path, deep, bulk):
    root, pins = corpus(tmp_path)
    if bulk:
        zip_csv(root/'SHARADAR_SEP.zip')
    (root/'ignored-directory').mkdir()
    (root/'duplicate.bin').write_bytes((root/YEARS[0]).read_bytes())
    output = tmp_path/'inventory.json'
    before = {path.name: path.read_bytes() for path in root.iterdir() if path.is_file()}
    report = invoke(monkeypatch, root, output, pins, deep=deep)
    summary = report['summary']
    assert summary['missing'] == summary['mismatched_pinned'] == 0
    assert summary['corpus_is_byte_identical_to_the_recovered_run'] is True
    assert summary['sep_per_year_files_present'] is True
    assert summary['sep_present_only_as_bulk_zip'] is False
    assert summary['metadata_inputs_byte_identical'] is True
    assert report['files']['duplicate.bin']['pinned'] is None
    assert any('duplicate.bin' in names for names in report['duplicates_by_content'].values())
    assert ('content' in report['files'][YEARS[0]]) is deep
    assert report['files']['SHARADAR_SFP.zip']['content']['missing_wanted'] == []
    assert {path.name: path.read_bytes() for path in root.iterdir() if path.is_file()} == before


@pytest.mark.parametrize('bulk,missing_metadata', [(True, False), (False, False), (True, True)])
def test_bulk_only_and_absent_metadata_have_distinct_next_steps(monkeypatch, tmp_path, capsys, bulk, missing_metadata):
    root, pins = corpus(tmp_path)
    for name in YEARS:
        (root/name).unlink()
    if bulk:
        zip_csv(root/'SHARADAR_SEP.zip')
    if missing_metadata:
        (root/'SHARADAR_SFP.zip').unlink()
    report = invoke(monkeypatch, root, tmp_path/'report.json', pins)
    summary = report['summary']
    assert summary['sep_present_only_as_bulk_zip'] is (bulk and not missing_metadata)
    assert summary['sep_per_year_files_present'] is False
    assert summary['metadata_inputs_byte_identical'] is (not missing_metadata)
    assert summary['missing'] == 2 + int(missing_metadata)
    assert summary['corpus_is_byte_identical_to_the_recovered_run'] is False
    assert report['summary']['missing_files'] == sorted([*YEARS] + (['SHARADAR_SFP.zip'] if missing_metadata else []))
    assert capsys.readouterr().out


def test_newer_corpus_hash_is_reported_as_difference_without_overwriting_pins(monkeypatch, tmp_path):
    root, pins = corpus(tmp_path)
    zip_csv(root/'SHARADAR_ACTIONS.zip', 'ticker,action\nX,dividend\n')
    report = invoke(monkeypatch, root, tmp_path/'report.json', pins)
    assert report['summary']['mismatched_files'] == ['SHARADAR_ACTIONS.zip']
    assert report['summary']['corpus_is_byte_identical_to_the_recovered_run'] is False
    assert report['files']['SHARADAR_ACTIONS.zip']['pinned'] == pins['SHARADAR_ACTIONS.zip']


def test_script_entrypoint_with_empty_private_corpus_does_not_claim_real_reproduction(monkeypatch, tmp_path):
    root = tmp_path/'empty-corpus'
    root.mkdir()
    output = tmp_path/'report.json'
    monkeypatch.setattr(sys, 'argv', [str(SOURCE), '--sharadar', str(root), '--out', str(output)])
    with pytest.raises(SystemExit) as completed:
        runpy.run_path(str(SOURCE), run_name='__main__')
    assert completed.value.code == 0
    report = json.loads(output.read_text())
    assert report['summary']['missing'] == 32
    assert report['summary']['corpus_is_byte_identical_to_the_recovered_run'] is False
    assert report['summary']['metadata_inputs_byte_identical'] is False
