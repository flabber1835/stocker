"""Real private corpus bytes and interrupted-generation recovery acceptance.

All files belong to pytest's temporary directory. No source export, historical
corpus, database, certificate, broker or production service is touched.
"""
import copy
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
SOURCE = ROOT/'scripts/sentinel-split-sep-bulk.py'
spec = importlib.util.spec_from_file_location('sep_splitter_fault_contract', SOURCE)
splitter = importlib.util.module_from_spec(spec)
spec.loader.exec_module(splitter)
HEADER = 'ticker,date,close\n'
TOKEN = '0123456789abcdef'


def sha(payload):
    return hashlib.sha256(payload).hexdigest()


def generation(tmp_path, phase='PREPARED', *, original=True):
    out = tmp_path/'years'
    out.mkdir()
    fp = tmp_path/'metadata'/'fingerprint.json'
    fp.parent.mkdir()
    staging = out/('.sentinel-sep-staging.'+TOKEN)
    staging.mkdir()
    backup_dir = out/('.sentinel-sep-backup.'+TOKEN)
    backup_dir.mkdir()
    entries = []
    for final in (out/'SHARADAR_SEP_1998.csv.gz', fp):
        is_fp = final == fp
        staged = (fp.parent/('.'+fp.name+'.sep-staging.'+TOKEN)
                  if is_fp else staging/final.name)
        backup = (fp.parent/('.'+fp.name+'.sep-backup.'+TOKEN)
                  if is_fp else backup_dir/final.name)
        old = b'old:'+final.name.encode()
        new = b'new:'+final.name.encode()
        staged.write_bytes(new)
        if phase == 'PREPARED':
            if original:
                final.write_bytes(old)
        else:
            if original:
                backup.write_bytes(old)
            final.write_bytes(new)
        entries.append({'final': str(final), 'staged': str(staged),
            'backup': str(backup), 'had_original': original,
            'sha256': sha(new), 'backup_sha256': sha(old) if original else None})
    payload = splitter._marker_payload(phase=phase, token=TOKEN,
                                      staging=staging, entries=entries)
    marker = out/splitter.PROMOTION_MARKER
    marker.write_text(json.dumps(payload))
    return out, fp, marker, payload


def retained_files(tmp_path):
    return {str(path.relative_to(tmp_path)): path.read_bytes()
            for path in tmp_path.rglob('*') if path.is_file()}


@pytest.mark.parametrize('content', [b'', b'abcdef', b'\x00\xff'*41])
def test_streamed_sha_is_exact(tmp_path, content):
    path = tmp_path/'bytes'
    path.write_bytes(content)
    assert splitter._sha256(path, chunk=3) == sha(content)
    splitter._fsync_file(path)


def test_year_writer_exact_fingerprint_dates_tickers_and_idempotent_close(tmp_path):
    path = tmp_path/'SHARADAR_SEP_1998.csv.gz'
    writer = splitter.YearWriter(path, HEADER)
    rows = [('SPY,1998-02-02,20\n', '1998-02-02', 'SPY'),
            ('BIL,1998-01-02,10\n', '1998-01-02', 'BIL'),
            ('SPY,1998-01-03,21\n', '1998-01-03', 'SPY')]
    for row in rows:
        writer.write(*row)
    result = writer.close()
    assert writer.close() == result
    writer.abort()
    assert writer.raw.closed and writer.fh.closed
    assert gzip.decompress(path.read_bytes()).decode() == HEADER+''.join(r[0] for r in rows)
    assert result == {'file': path.name, 'rows': 3, 'first_date': '1998-01-02',
        'last_date': '1998-02-02', 'distinct_tickers': 2,
        'content_fingerprint': f"{sum(int(sha(r[0].encode()), 16) for r in rows) % splitter.MODULUS:064x}",
        'sha256_of_gzip': sha(path.read_bytes())}
    splitter._validate_year(path, expected_name=path.name,
                            expected_sha256=result['sha256_of_gzip'])


@pytest.mark.parametrize('close_fails', [False, True])
def test_abort_closes_owned_raw_stream_even_when_gzip_close_fails(tmp_path, monkeypatch, close_fails):
    writer = splitter.YearWriter(tmp_path/'private.gz', HEADER)
    actual_close = writer.fh.close
    if close_fails:
        def fail():
            actual_close()
            raise OSError('injected gzip close')
        monkeypatch.setattr(writer.fh, 'close', fail)
        with pytest.raises(OSError, match='injected gzip close'):
            writer.abort()
    else:
        writer.abort()
    assert writer.raw.closed and writer._closed
    writer.abort()


@pytest.mark.parametrize('case', ['missing', 'wrong-name', 'header', 'empty', 'changed'])
def test_year_validation_rejects_missing_bad_header_or_drift(tmp_path, case):
    path = tmp_path/'SHARADAR_SEP_1998.csv.gz'
    text = '' if case == 'empty' else ('price\n1\n' if case == 'header' else HEADER)
    if case != 'missing':
        path.write_bytes(gzip.compress(text.encode(), mtime=0))
    with pytest.raises(RuntimeError):
        splitter._validate_year(path, expected_name='wrong.gz' if case == 'wrong-name' else path.name,
            expected_sha256='0'*64 if case == 'changed' else None)


def test_directory_fsync_closes_descriptor_on_failure_and_supports_platform_without_directory_flag(tmp_path, monkeypatch):
    opened = []
    actual_open = os.open
    def track(*args):
        fd = actual_open(*args)
        opened.append(fd)
        return fd
    monkeypatch.setattr(splitter.os, 'open', track)
    monkeypatch.delattr(splitter.os, 'O_DIRECTORY')
    def fail(fd):
        raise OSError('injected directory sync')
    monkeypatch.setattr(splitter.os, 'fsync', fail)
    with pytest.raises(OSError, match='injected directory sync'):
        splitter._fsync_dir(tmp_path)
    with pytest.raises(OSError):
        os.fstat(opened[0])


@pytest.mark.parametrize('failure', ['none', 'file-sync', 'replace', 'directory-sync'])
def test_atomic_marker_write_retains_complete_old_or_new_value(tmp_path, monkeypatch, failure):
    owned = tmp_path/'markers'
    owned.mkdir()
    marker = owned/'marker.json'
    old = b'{"old":true}\n'
    marker.write_bytes(old)
    payload = {'schema': 'private', 'value': 3}
    def fail(*args):
        raise OSError('injected '+failure)
    if failure == 'file-sync':
        monkeypatch.setattr(splitter.os, 'fsync', fail)
    elif failure == 'replace':
        monkeypatch.setattr(splitter.os, 'replace', fail)
    elif failure == 'directory-sync':
        monkeypatch.setattr(splitter, '_fsync_dir', fail)
    if failure == 'none':
        splitter._write_json_fsynced(marker, payload)
    else:
        with pytest.raises(OSError, match='injected '+failure):
            splitter._write_json_fsynced(marker, payload)
    if failure in ('file-sync', 'replace'):
        assert marker.read_bytes() == old
    else:
        assert json.loads(marker.read_text()) == payload
    assert sorted(p.name for p in owned.iterdir()) == ['marker.json']


@pytest.mark.parametrize('kind', ['missing', 'file', 'directory', 'symlink'])
def test_owned_cleanup_does_not_follow_a_symlink(tmp_path, kind):
    target = tmp_path/'private'
    victim = tmp_path/'retained'
    victim.write_bytes(b'preserve')
    if kind == 'file':
        target.write_bytes(b'owned')
    elif kind == 'directory':
        target.mkdir()
        (target/'owned').write_bytes(b'owned')
    elif kind == 'symlink':
        target.symlink_to(victim)
    splitter._cleanup_path(target)
    assert not target.exists() and not target.is_symlink()
    assert victim.read_bytes() == b'preserve'


INVALID_ROOT = [None, [], {}, {'schema': 'wrong'}, {'phase': 'UNKNOWN'},
    {'phase': []}, {'phase': {}}, {'entries': {}}, {'staging': None},
    {'token': None}, {'token': 'g'*16}, {'token': '1'*7}, {'token': '1'*65},
    {'staging': '/escaped/staging'}, {'entries': []}, {'numeric': 1.5},
    {'staging': '\x00'}]


@pytest.mark.parametrize('change', INVALID_ROOT)
def test_marker_root_schema_type_and_path_refusal_preserves_every_byte(tmp_path, change):
    out, fp, marker, payload = generation(tmp_path)
    if isinstance(change, dict) and change:
        payload.update(change)
    else:
        payload = change
    marker.write_text(json.dumps(payload))
    before = retained_files(tmp_path)
    with pytest.raises(SystemExit, match='^REFUSED:'):
        splitter._recover_promotion(out, fingerprint_final=fp)
    assert retained_files(tmp_path) == before


INVALID_ENTRY = [None, {}, {'extra': 1}, {'had_original': 1}, {'sha256': None},
    {'sha256': 'x'*64}, {'backup_sha256': None}, {'backup_sha256': 7},
    {'backup_sha256': '0'*63}, {'final': None}, {'final': 3}, {'staged': []},
    {'backup': {}}, {'final': '/escaped/SHARADAR_SEP_1998.csv.gz'},
    {'final': 'SHARADAR_SEP_bad.csv.gz'}, {'staged': '/escaped/member'},
    {'backup': '/escaped/backup'}, {'staged': ''}, {'backup': '\x00'}]


@pytest.mark.parametrize('change', INVALID_ENTRY)
def test_marker_entry_types_hashes_and_ownership_refuse_before_cleanup(tmp_path, change):
    out, fp, marker, payload = generation(tmp_path)
    if isinstance(change, dict) and change:
        payload['entries'][0].update(change)
    else:
        payload['entries'][0] = change
    marker.write_text(json.dumps(payload))
    before = retained_files(tmp_path)
    with pytest.raises(SystemExit, match='^REFUSED:'):
        splitter._recover_promotion(out, fingerprint_final=fp)
    assert retained_files(tmp_path) == before


@pytest.mark.parametrize('case', ['unreadable', 'duplicate-phase', 'duplicate-entry', 'nan',
                                'infinity', 'overflow', 'duplicate-final', 'unexpected-backup'])
def test_ambiguous_marker_has_no_recovery_authority(tmp_path, case):
    out, fp, marker, payload = generation(tmp_path)
    text = json.dumps(payload)
    if case == 'unreadable':
        text = '{broken'
    elif case == 'duplicate-phase':
        text = text.replace('"phase": "PREPARED"', '"phase": "COMMITTED", "phase": "PREPARED"')
    elif case == 'duplicate-entry':
        text = text.replace('"had_original": true', '"had_original": false, "had_original": true', 1)
    elif case in ('nan', 'infinity', 'overflow'):
        text = text[:-1]+', "numeric": '+{'nan':'NaN', 'infinity':'Infinity', 'overflow':'1e999'}[case]+'}'
    elif case == 'duplicate-final':
        payload['entries'].append(copy.deepcopy(payload['entries'][0]))
        text = json.dumps(payload)
    else:
        payload['entries'][0]['had_original'] = False
        text = json.dumps(payload)
    marker.write_text(text)
    before = retained_files(tmp_path)
    with pytest.raises(SystemExit, match='^REFUSED:'):
        splitter._recover_promotion(out, fingerprint_final=fp)
    assert retained_files(tmp_path) == before


@pytest.mark.parametrize('phase', ['PREPARED', 'BACKED_UP', 'COMMITTED'])
@pytest.mark.parametrize('original', [False, True])
def test_exact_owned_generation_recovery_is_idempotent(tmp_path, phase, original):
    out, fp, marker, payload = generation(tmp_path, phase, original=original)
    splitter._recover_promotion(out, fingerprint_final=fp)
    for entry in payload['entries']:
        final = Path(entry['final'])
        if phase == 'COMMITTED':
            assert final.read_bytes() == b'new:'+final.name.encode()
        elif original:
            assert final.read_bytes() == b'old:'+final.name.encode()
        else:
            assert not final.exists()
        assert not Path(entry['staged']).exists()
        assert not Path(entry['backup']).exists()
    assert not marker.exists() and not Path(payload['staging']).exists()
    before = retained_files(tmp_path)
    splitter._recover_promotion(out, fingerprint_final=fp)
    assert retained_files(tmp_path) == before


@pytest.mark.parametrize('case', ['prepared-drift', 'prepared-absent', 'backup-drift',
    'backup-lost', 'committed-drift', 'committed-missing', 'foreign-new-final',
    'foreign-final-with-backup', 'prepared-foreign-final'])
def test_recovery_does_not_discard_ambiguous_original_or_unowned_final(tmp_path, case):
    phase = ('PREPARED' if case.startswith('prepared') else
             'COMMITTED' if case.startswith('committed') else 'BACKED_UP')
    original = case not in ('foreign-new-final', 'prepared-foreign-final')
    out, fp, marker, payload = generation(tmp_path, phase, original=original)
    entry = payload['entries'][0]
    if case in ('prepared-absent', 'committed-missing'):
        Path(entry['final']).unlink()
    elif case == 'backup-lost':
        Path(entry['backup']).unlink()
    elif case == 'backup-drift':
        Path(entry['backup']).write_bytes(b'changed backup')
    else:
        Path(entry['final']).write_bytes(b'unrecognized current bytes')
    before = retained_files(tmp_path)
    with pytest.raises(SystemExit, match='^REFUSED:'):
        splitter._recover_promotion(out, fingerprint_final=fp)
    assert retained_files(tmp_path) == before


def test_backup_directory_cannot_become_file_restore_authority(tmp_path):
    out, fp, marker, payload = generation(tmp_path, 'BACKED_UP')
    backup = Path(payload['entries'][0]['backup'])
    backup.unlink()
    backup.mkdir()
    (backup/'unowned').write_bytes(b'preserve')
    before = retained_files(tmp_path)
    with pytest.raises(SystemExit, match='^REFUSED:'):
        splitter._recover_promotion(out, fingerprint_final=fp)
    assert retained_files(tmp_path) == before


def test_prepared_partial_backup_and_durable_partial_rollback_resume(tmp_path, monkeypatch):
    out, fp, marker, payload = generation(tmp_path)
    entry = payload['entries'][0]
    os.replace(entry['final'], entry['backup'])
    splitter._recover_promotion(out, fingerprint_final=fp)
    assert Path(entry['final']).read_bytes() == b'old:'+Path(entry['final']).name.encode()
    assert not marker.exists()


def test_backed_up_member_already_restored_consumed_backup_is_a_valid_checkpoint(tmp_path):
    out, fp, marker, payload = generation(tmp_path, 'BACKED_UP')
    entry = payload['entries'][0]
    os.replace(entry['backup'], entry['final'])
    splitter._recover_promotion(out, fingerprint_final=fp)
    assert not marker.exists()
    for entry in payload['entries']:
        assert sha(Path(entry['final']).read_bytes()) == entry['backup_sha256']


@pytest.mark.parametrize('phase', ['PREPARED', 'BACKED_UP'])
def test_rollback_accepts_exact_old_bytes_while_a_verified_backup_still_exists(tmp_path, phase):
    out, fp, marker, payload = generation(tmp_path, phase)
    for entry in payload['entries']:
        final, backup = Path(entry['final']), Path(entry['backup'])
        old = b'old:'+final.name.encode()
        final.write_bytes(old)
        backup.write_bytes(old)
    splitter._recover_promotion(out, fingerprint_final=fp)
    assert not marker.exists()
    assert all(sha(Path(e['final']).read_bytes()) == e['backup_sha256'] for e in payload['entries'])


@pytest.mark.parametrize('original', [False, True])
def test_backed_up_generation_recovers_before_any_new_member_was_promoted(tmp_path, original):
    out, fp, marker, payload = generation(tmp_path, 'BACKED_UP', original=original)
    for entry in payload['entries']:
        Path(entry['final']).unlink()
    splitter._recover_promotion(out, fingerprint_final=fp)
    assert not marker.exists()
    for entry in payload['entries']:
        final = Path(entry['final'])
        assert final.exists() == original
        if original:
            assert sha(final.read_bytes()) == entry['backup_sha256']


def zip_csv(path, content=HEADER+'SPY,1998-01-02,20\n', *, members=None):
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in (members if members is not None else {'sep.csv': content}).items():
            archive.writestr(name, value)
    return path


def invoke(monkeypatch, archive, out, fp, *, force=False, last=1999):
    monkeypatch.setattr(sys, 'argv', [str(SOURCE), '--zip', str(archive), '--out', str(out),
        '--fingerprint', str(fp), '--last-year', str(last)]+(['--force'] if force else []))
    return splitter.main()


def test_real_split_skips_malformed_outside_and_blank_rows_preserves_exact_accepted_bytes(tmp_path, monkeypatch, capsys):
    text = HEADER+'\nSPY,1998-02-02,20\nBIL,1998-01-02,10\nshort\nX,nodate,5\nX,1997-01-01,2\nSPY,1998-03-03,21'
    archive = zip_csv(tmp_path/'bulk.zip', text)
    out, fp = tmp_path/'years', tmp_path/'metadata'/'fp.json'
    assert invoke(monkeypatch, archive, out, fp) == 0
    report = json.loads(fp.read_text())
    assert report['rows_written'] == 3 and report['malformed_rows_skipped'] == 2
    assert report['rows_outside_year_range'] == {'1997': 1}
    assert report['source_zip_sha256'] == sha(archive.read_bytes())
    expected = HEADER+'SPY,1998-02-02,20\nBIL,1998-01-02,10\nSPY,1998-03-03,21\n'
    assert gzip.decompress((out/'SHARADAR_SEP_1998.csv.gz').read_bytes()).decode() == expected
    assert gzip.decompress((out/'SHARADAR_SEP_1999.csv.gz').read_bytes()).decode() == HEADER
    assert report['years']['1998']['first_date'] == '1998-01-02'
    assert 'EMPTY years' in capsys.readouterr().out
    assert not (out/splitter.PROMOTION_MARKER).exists()
    before = retained_files(tmp_path)
    with pytest.raises(SystemExit, match='already exist'):
        invoke(monkeypatch, archive, out, fp)
    assert retained_files(tmp_path) == before
    replacement = zip_csv(tmp_path/'next.zip', HEADER+'BIL,1999-01-01,101\n')
    assert invoke(monkeypatch, replacement, out, fp, force=True) == 0
    assert json.loads(fp.read_text())['rows_written'] == 1
    assert gzip.decompress((out/'SHARADAR_SEP_1999.csv.gz').read_bytes()).decode() == HEADER+'BIL,1999-01-01,101\n'
    assert not any(p.name.startswith('.sentinel-sep-') for p in out.iterdir())


@pytest.mark.parametrize('members,reason', [({}, 'expected one CSV'),
    ({'a.csv':HEADER, 'b.CSV':HEADER}, 'expected one CSV'),
    ({'a.csv':''}, 'empty CSV'), ({'a.csv':'price\n1\n'}, 'no date/ticker')])
def test_bad_archive_refuses_and_releases_staging_only(tmp_path, monkeypatch, members, reason):
    archive = zip_csv(tmp_path/'bulk.zip', members=members)
    out, fp = tmp_path/'years', tmp_path/'fp.json'
    with pytest.raises(SystemExit, match=reason):
        invoke(monkeypatch, archive, out, fp)
    assert list(out.iterdir()) == [] and not fp.exists()
    assert archive.exists()


def test_quoted_csv_fields_are_not_silently_dropped_or_misfingerprinted(tmp_path, monkeypatch):
    text = HEADER+'"PRIVATE,TICKER",1998-01-02,20\n"QUOTED",1999-01-01,10\n'
    archive = zip_csv(tmp_path/'bulk.zip', text)
    out, fp = tmp_path/'years', tmp_path/'fp.json'
    assert invoke(monkeypatch, archive, out, fp) == 0
    report = json.loads(fp.read_text())
    assert report['rows_written'] == 2 and report['malformed_rows_skipped'] == 0
    assert report['years']['1998']['distinct_tickers'] == 1
    assert gzip.decompress((out/'SHARADAR_SEP_1998.csv.gz').read_bytes()).decode() == HEADER+'"PRIVATE,TICKER",1998-01-02,20\n'


@pytest.mark.parametrize('boundary', ['before-marker', 'after-backup', 'after-first-promotion'])
def test_failed_main_leaves_only_owned_recoverable_checkpoint(tmp_path, monkeypatch, boundary):
    archive = zip_csv(tmp_path/'bulk.zip')
    out, fp = tmp_path/'years', tmp_path/'fp.json'
    assert invoke(monkeypatch, archive, out, fp, last=1998) == 0
    old = {str(p):p.read_bytes() for p in (out/'SHARADAR_SEP_1998.csv.gz', fp)}
    replacement = zip_csv(tmp_path/'new.zip', HEADER+'BIL,1998-03-01,30\n')
    actual_marker = splitter._write_json_fsynced
    actual_replace = os.replace
    def write(path, payload):
        if boundary == 'before-marker':
            raise OSError('injected interruption')
        actual_marker(path, payload)
        if boundary == 'after-backup' and payload['phase'] == 'BACKED_UP':
            raise OSError('injected interruption')
    def replace(src, dst):
        actual_replace(src, dst)
        if boundary == 'after-first-promotion' and '.sentinel-sep-staging.' in str(src) and str(src).endswith('.gz'):
            raise OSError('injected interruption')
    with monkeypatch.context() as faults:
        faults.setattr(splitter, '_write_json_fsynced', write)
        faults.setattr(splitter.os, 'replace', replace)
        with pytest.raises(OSError, match='injected interruption'):
            invoke(monkeypatch, replacement, out, fp, force=True, last=1998)
    marker = out/splitter.PROMOTION_MARKER
    assert marker.exists() == (boundary != 'before-marker')
    splitter._recover_promotion(out, fingerprint_final=fp)
    assert all(Path(path).read_bytes() == value for path, value in old.items())
    assert not marker.exists()


def test_cli_main_executes_actual_reader_and_emits_nonempty_year_report(tmp_path, monkeypatch, capsys):
    archive = zip_csv(tmp_path/'bulk.zip', HEADER+'SPY,1998-01-02,1\n')
    out, fp = tmp_path/'years', tmp_path/'fp.json'
    monkeypatch.setattr(sys, 'argv', [str(SOURCE), '--zip', str(archive), '--out', str(out),
                                   '--fingerprint', str(fp), '--last-year', '1998'])
    with pytest.raises(SystemExit) as exit_info:
        runpy.run_path(str(SOURCE), run_name='__main__')
    assert exit_info.value.code == 0
    assert json.loads(fp.read_text())['rows_written'] == 1
    assert 'EMPTY years' not in capsys.readouterr().out


def test_promoted_member_hash_mismatch_cannot_be_committed(tmp_path, monkeypatch):
    archive = zip_csv(tmp_path/'bulk.zip')
    out, fp = tmp_path/'years', tmp_path/'fp.json'
    actual_replace = os.replace
    def corrupt(src, dst):
        actual_replace(src, dst)
        if '.sentinel-sep-staging.' in str(src) and str(src).endswith('.gz'):
            Path(dst).write_bytes(b'corrupted promoted member')
    monkeypatch.setattr(splitter.os, 'replace', corrupt)
    with pytest.raises(RuntimeError, match='promoted SEP artifact failed validation'):
        invoke(monkeypatch, archive, out, fp, last=1998)
    marker = out/splitter.PROMOTION_MARKER
    assert json.loads(marker.read_text())['phase'] == 'BACKED_UP'
    before = retained_files(tmp_path)
    with pytest.raises(SystemExit, match='unowned bytes'):
        splitter._recover_promotion(out, fingerprint_final=fp)
    assert retained_files(tmp_path) == before


def test_actual_five_million_rows_progress_and_exact_fingerprint(tmp_path, monkeypatch, capsys):
    line = b'SPY,1998-01-02,1\n'
    count = 5_000_000
    archive = tmp_path/'bulk.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as zipped:
        with zipped.open('sep.csv', 'w') as member:
            member.write(HEADER.encode())
            block = line*10_000
            for _ in range(count//10_000):
                member.write(block)
    out, fp = tmp_path/'years', tmp_path/'fp.json'
    assert invoke(monkeypatch, archive, out, fp, last=1998) == 0
    report = json.loads(fp.read_text())
    year = report['years']['1998']
    assert report['rows_written'] == count and year['rows'] == count
    assert year['distinct_tickers'] == 1
    assert year['content_fingerprint'] == f"{(count*int(sha(line), 16)) % splitter.MODULUS:064x}"
    assert year['sha256_of_gzip'] == sha((out/year['file']).read_bytes())
    with gzip.open(out/year['file'], 'rb') as rows:
        assert rows.readline() == HEADER.encode()
        assert sum(1 for row in rows if row == line) == count
    assert '5,000,000 rows ...' in capsys.readouterr().err
