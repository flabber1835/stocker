"""File/geometry/JSON admission tests, never a production backup or restore."""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import runpy
import sys

import pytest


SCRIPT = Path(__file__).resolve().parents[2] / 'scripts/sentinel-backup-verify-chain.py'
spec = importlib.util.spec_from_file_location('backup_chain_contract', SCRIPT)
chain = importlib.util.module_from_spec(spec)
spec.loader.exec_module(chain)
SIZE = 1024 * 1024
SYSTEM = '424242'
BASE = 'base-20261009T010000Z'
START = '000000010000000000000001'
END = '000000010000000000000002'


def checksummed(path, content):
    path.write_bytes(content)
    path.with_name(path.name + '.sha256').write_text(
        'sha256=' + hashlib.sha256(content).hexdigest() + '\n')


@pytest.fixture
def media(tmp_path):
    base = tmp_path / 'base' / BASE
    namespace = tmp_path / 'wal' / ('cluster-' + SYSTEM)
    base.mkdir(parents=True)
    namespace.mkdir(parents=True)
    (base / 'backup_manifest').write_text(json.dumps({'WAL-Ranges': [
        {'Timeline': 1, 'End-LSN': '0/100000'}]}))
    (base / 'backup_label').write_text('isolated synthetic label\n')
    (base / 'sentinel-pitr-base-identity').write_text('system_identifier=' + SYSTEM + '\n')
    (base / 'sentinel-recovery-marker').write_text(
        'marker=sentinel-backup-20261009T010000Z-17\n'
        'lsn=0/200000\nwal=' + END + '\nsystem_identifier=' + SYSTEM + '\n')
    checksummed(namespace / START, b'a' * SIZE)
    checksummed(namespace / END, b'b' * SIZE)
    return tmp_path, base, namespace


def verify(media, **kwargs):
    values = dict(root=media[0], base_name=BASE, system_id=SYSTEM,
                  last_wal=END, segment_size=SIZE)
    values.update(kwargs)
    return chain.verify(**values)


def test_complete_chain_checks_every_segment_without_modifying_media(media):
    before = {str(p.relative_to(media[0])): p.read_bytes()
              for p in media[0].rglob('*') if p.is_file()}
    assert verify(media) == (START, (START, END))
    after = {str(p.relative_to(media[0])): p.read_bytes()
             for p in media[0].rglob('*') if p.is_file()}
    assert after == before


@pytest.mark.parametrize('kind', ['missing', 'directory', 'symlink', 'hardlink'])
def test_checksum_objects_cannot_escape_or_alias_their_owned_identity(tmp_path, kind):
    target = tmp_path / 'wal'
    if kind == 'directory':
        target.mkdir()
    elif kind in {'symlink', 'hardlink'}:
        source = tmp_path / 'other'
        source.write_bytes(b'other object')
        target.symlink_to(source) if kind == 'symlink' else os.link(source, target)
    with pytest.raises(chain.ChainRefused, match='missing or unreadable|non-symlink|hard links'):
        chain._regular(target, label='owned WAL')


@pytest.mark.parametrize('kind', ['missing', 'file', 'symlink'])
def test_backup_directories_must_be_real_directories(tmp_path, kind):
    target = tmp_path / 'base'
    if kind == 'file':
        target.touch()
    elif kind == 'symlink':
        other = tmp_path / 'other'
        other.mkdir()
        target.symlink_to(other, target_is_directory=True)
    with pytest.raises(chain.ChainRefused, match='missing or unreadable|non-symlink directory'):
        chain._directory(target, label='base')


@pytest.mark.parametrize('text', ['key', '=value', 'key=', 'key=value\nkey=other'])
def test_metadata_never_accepts_an_ambiguous_field(text):
    with pytest.raises(chain.ChainRefused, match='incomplete or duplicated'):
        chain._metadata(text)
    assert chain._metadata('system_identifier=424242\n') == {'system_identifier': SYSTEM}


@pytest.mark.parametrize('manifest', [
    {}, {'WAL-Ranges': None}, {'WAL-Ranges': []}, {'WAL-Ranges': ['bad']},
    {'WAL-Ranges': [{}]}, {'WAL-Ranges': [{'Timeline': 'bad'}]},
    {'WAL-Ranges': [{'Timeline': 0}]}, {'WAL-Ranges': [{'Timeline': 2**32}]},
    {'WAL-Ranges': [{'Timeline': 1, 'End-LSN': 'broken'}]},
    {'WAL-Ranges': [{'Timeline': 1, 'End-LSN': '100000000/0'}]},
    {'WAL-Ranges': [{'Timeline': 1, 'End-LSN': '0/100000000'}]},
])
def test_manifest_range_requires_bounded_timeline_and_postgres_lsn(manifest):
    with pytest.raises(chain.ChainRefused, match='manifest'):
        chain._manifest_start(manifest, SIZE)


@pytest.mark.parametrize('start,end,size,reason', [
    (START, END, 0, 'unsupported WAL segment size'),
    (START, END, -1, 'unsupported WAL segment size'),
    (START, END, 3, 'unsupported WAL segment size'),
    ('bad', END, SIZE, 'malformed WAL filename'),
    ('000000010000000000001000', END, SIZE, 'outside configured geometry'),
    (START, '000000020000000000000002', SIZE, 'different timelines'),
    (END, START, SIZE, 'precedes'),
    ('000000010000000000000000', '00000001000000F400000241', SIZE, 'reviewed bound'),
])
def test_chain_geometry_refuses_missing_or_unbounded_horizons(start, end, size, reason):
    with pytest.raises(chain.ChainRefused, match=reason):
        chain._expected(start, end, size)


def test_chain_rollover_enumerates_both_logs_in_order():
    assert chain._expected('000000030000000000000FFF',
        '000000030000000100000000', SIZE) == (
        '000000030000000000000FFF', '000000030000000100000000')


@pytest.mark.parametrize('mutation,reason', [
    ('missing_sidecar', 'missing or unreadable'),
    ('malformed_sidecar', 'sidecar is malformed'),
    ('unreadable_sidecar', 'sidecar is unreadable'),
    ('wrong_digest', 'failed SHA-256'),
    ('truncated', 'missing or truncated'),
    ('empty', 'is empty'),
])
def test_checksum_admission_refuses_every_incomplete_or_changed_object(tmp_path, mutation, reason):
    path = tmp_path / 'object'
    checksummed(path, b'complete object')
    sidecar = path.with_name(path.name + '.sha256')
    exact_size = len(path.read_bytes())
    if mutation == 'missing_sidecar':
        sidecar.unlink()
    elif mutation == 'malformed_sidecar':
        sidecar.write_text('not a digest')
    elif mutation == 'unreadable_sidecar':
        sidecar.write_bytes(b'\xff')
    elif mutation == 'wrong_digest':
        path.write_bytes(b'changed content')
        exact_size = None
    elif mutation == 'truncated':
        path.write_bytes(b'partial')
    else:
        path.write_bytes(b'')
        exact_size = None
    with pytest.raises(chain.ChainRefused, match=reason):
        chain._verify_checksum_object(path, label='WAL', exact_size=exact_size)


@pytest.mark.parametrize('name,value,reason', [
    ('base_name', '../outside', 'base backup name'),
    ('system_id', 'not-a-cluster', 'system identifier'),
    ('system_id', '0', 'system identifier'),
    ('system_id', str(2**64), 'system identifier'),
])
def test_restore_identity_is_validated_before_path_access(media, name, value, reason):
    with pytest.raises(chain.ChainRefused, match=reason):
        verify(media, **{name: value})


@pytest.mark.parametrize('file,content,reason', [
    ('backup_manifest', b'not JSON', 'manifest is unreadable or malformed'),
    ('sentinel-pitr-base-identity', b'system_identifier=999\n', 'different PostgreSQL cluster'),
    ('sentinel-recovery-marker', b'\xff', 'metadata is unreadable'),
    ('sentinel-recovery-marker', b'marker=x\n', 'fields are invalid'),
    ('sentinel-recovery-marker',
     b'marker=sentinel-backup-20261009T010000Z-17\nlsn=0/200000\nwal=' + END.encode() +
     b'\nsystem_identifier=999\n', 'different PostgreSQL cluster'),
])
def test_manifest_and_markers_cannot_admit_another_cluster_or_broken_json(media, file, content, reason):
    (media[1] / file).write_bytes(content)
    with pytest.raises(chain.ChainRefused, match=reason):
        verify(media)


@pytest.mark.parametrize('field,value,reason', [
    ('marker', 'another-marker', 'identity is malformed'),
    ('lsn', 'not-an-lsn', 'LSN is malformed'),
    ('wal', '000000010000000000000003', 'outside the retained restore chain'),
])
def test_recovery_marker_must_belong_to_the_verified_horizon(media, field, value, reason):
    marker = media[1] / 'sentinel-recovery-marker'
    values = chain._metadata(marker.read_text())
    values[field] = value
    marker.write_text(''.join(k+'='+v+'\n' for k,v in values.items()))
    with pytest.raises(chain.ChainRefused, match=reason):
        verify(media)


@pytest.mark.parametrize('history_present', [False, True])
def test_promoted_timeline_requires_its_own_checksummed_history(media, history_present):
    start, end = '00000003' + START[8:], '00000003' + END[8:]
    (media[1] / 'backup_manifest').write_text(json.dumps({'WAL-Ranges': [
        {'Timeline': 3, 'End-LSN': '0/100000'}]}))
    marker = media[1] / 'sentinel-recovery-marker'
    marker.write_text(marker.read_text().replace(END, end))
    for old, new in ((START, start), (END, end)):
        (media[2] / old).rename(media[2] / new)
        (media[2] / (old + '.sha256')).rename(media[2] / (new + '.sha256'))
    if history_present:
        checksummed(media[2] / '00000003.history', b'1\t0/100000\tfixture promotion\n')
        assert verify(media, last_wal=end) == (start, (start, end))
    else:
        with pytest.raises(chain.ChainRefused, match='timeline history is missing'):
            verify(media, last_wal=end)


@pytest.mark.parametrize('manifest', [None, [], False, 0, 'unexpected manifest'])
def test_valid_json_with_wrong_root_type_is_a_typed_refusal(media, manifest):
    (media[1] / 'backup_manifest').write_text(json.dumps(manifest))
    with pytest.raises(chain.ChainRefused, match='manifest'):
        verify(media)


def test_zero_segment_geometry_is_refused_before_manifest_arithmetic(media):
    with pytest.raises(chain.ChainRefused, match='unsupported WAL segment size'):
        verify(media, segment_size=0)


@pytest.mark.parametrize('mode', ['valid', 'missing_wal', 'wrong_json_type', 'zero_geometry'])
def test_cli_reports_chain_admission_or_typed_refusal(media, monkeypatch, capsys, mode):
    if mode == 'missing_wal':
        (media[2] / END).unlink()
    elif mode == 'wrong_json_type':
        (media[1] / 'backup_manifest').write_text('null')
    size = 0 if mode == 'zero_geometry' else SIZE
    monkeypatch.setattr(sys, 'argv', [str(SCRIPT), '--root', str(media[0]), '--base', BASE,
        '--system-id', SYSTEM, '--last-wal', END, '--segment-size', str(size)])
    with pytest.raises(SystemExit) as result:
        runpy.run_path(str(SCRIPT), run_name='__main__')
    output = capsys.readouterr()
    assert result.value.code == (0 if mode == 'valid' else 4)
    if mode == 'valid':
        assert 'wal_chain_ready:true' in output.out and 'segments=2' in output.out
        assert output.err == ''
    else:
        assert output.out == '' and output.err.startswith('REFUSED: ')
