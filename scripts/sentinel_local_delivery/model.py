"""Strict portable host records; these records grant no broker authority."""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile

SCHEMA = 'sentinel.local-paper-delivery/2'
LEGACY_SCHEMA = 'sentinel.local-paper-delivery/1'
LEGACY_STAGES = ('NEW', 'PREFLIGHT_PASS', 'STOP_REQUESTED', 'APPLICATIONS_STOPPED',
                 'SHADOW_STARTED', 'SHADOW_VERIFIED', 'START_REQUESTED', 'APPLICATIONS_STARTED', 'VERIFIED')
STAGES = ('NEW','PREFLIGHT_PASS','DRAIN_REQUESTED','DRAIN_ACKNOWLEDGED','STOP_REQUESTED',
          'APPLICATIONS_STOPPED','SCHEMA_INSTALL_REQUESTED','SCHEMA_INSTALLED',
          'COMPOSE_INSTALL_REQUESTED','COMPOSE_INSTALLED','SHADOW_STARTED','SHADOW_VERIFIED',
          'START_REQUESTED','APPLICATIONS_STARTED','VERIFIED')
REVIEWED_HOST_ARTIFACTS = frozenset({'README.md','docker-compose.sentinel-automation.yml',
                                    'docker-compose.sentinel-local-paper.yml'})
COMPAT_DRAIN_PREDECESSOR = 'b2e308bb664718da373175f1a7d988d07b159ae2'


class DeliveryRefused(RuntimeError):
    pass


def require(condition, reason):
    if not condition:
        raise DeliveryRefused(reason)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def utcnow():
    return datetime.now(timezone.utc)


def read_json(path):
    path = Path(path)
    require(path.is_file() and not path.is_symlink(), 'RECORD_PATH_UNSAFE')
    require(path.stat().st_size <= 16*1024*1024, 'RECORD_TOO_LARGE')
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'RECORD_DUPLICATE_KEY')
            result[key] = value
        return result
    return json.loads(path.read_text(encoding='utf-8'), object_pairs_hook=unique,
                      parse_constant=lambda _: require(False, 'RECORD_NONFINITE'))


def write_new(path, value):
    path = Path(path)
    with path.open('xb') as stream:
        os.chmod(path, 0o600)
        stream.write(canonical(value)+b'\n')
        stream.flush()
        os.fsync(stream.fileno())


def atomic_json(path, value):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(prefix='.delivery-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(canonical(value)+b'\n')
            stream.flush()
            os.fsync(stream.fileno())
        Path(temporary).replace(path)
        if os.name == 'posix':
            directory = os.open(path.parent, os.O_RDONLY)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()


def validate_request(value):
    require(isinstance(value, dict) and set(value) == {
        'schema', 'operation_id', 'source', 'deployment', 'predecessor',
        'candidate', 'qualification', 'allowed_delta', 'created_at'}, 'REQUEST_SHAPE')
    require(value['schema'] in {SCHEMA,LEGACY_SCHEMA}, 'REQUEST_SCHEMA')
    require(isinstance(value['operation_id'], str) and
            re.fullmatch(r'[a-z0-9][a-z0-9-]{0,79}', value['operation_id']) is not None,
            'REQUEST_OPERATION_ID')
    for name in ('source', 'deployment'):
        require(isinstance(value[name], str), 'REQUEST_PATH_UNSAFE')
        path = Path(value[name])
        require(path.is_absolute() and '..' not in path.parts
                and not any(item.is_symlink() for item in (path, *path.parents)),
                'REQUEST_PATH_UNSAFE')
    for role in ('predecessor', 'candidate'):
        item = value[role]
        require(isinstance(item, dict) and {'commit', 'image'} <= set(item), 'REQUEST_RUNTIME')
        require(isinstance(item['commit'], str) and isinstance(item['image'], str)
                and re.fullmatch(r'[0-9a-f]{40}', item['commit']) is not None
                and re.fullmatch(r'sha256:[0-9a-f]{64}', item['image']) is not None,
                'REQUEST_RUNTIME_IDENTITY')
    require(set(value['predecessor']) == {'commit', 'image', 'postgres', 'system'},
            'REQUEST_PREDECESSOR_SHAPE')
    require(set(value['candidate']) == {'commit', 'image', 'source_identity'},
            'REQUEST_CANDIDATE_SHAPE')
    identity = value['candidate']['source_identity']
    require(isinstance(identity, dict) and set(identity) == {'source','wealth','shadow_config'}
            and all(isinstance(item,str) and re.fullmatch(r'[0-9a-f]{64}',item)
                    for item in identity.values()), 'REQUEST_SOURCE_IDENTITY')
    require(isinstance(value['predecessor']['postgres'],dict)
            and isinstance(value['predecessor']['system'],str)
            and value['predecessor']['system'].isdigit(), 'REQUEST_POSTGRES_IDENTITY')
    qualification = value['qualification']
    require(isinstance(qualification,dict) and set(qualification) == {
        'report_path','report_sha256','commit','passed','source_files'}, 'REQUEST_QUALIFICATION_SHAPE')
    require(qualification['commit']==value['candidate']['commit']
            and qualification['passed'] is True
            and isinstance(qualification['report_path'],str)
            and Path(qualification['report_path']).is_absolute()
            and isinstance(qualification['report_sha256'],str)
            and re.fullmatch(r'[0-9a-f]{64}',qualification['report_sha256'])
            and isinstance(qualification['source_files'],dict)
            and bool(qualification['source_files']), 'REQUEST_QUALIFICATION_IDENTITY')
    require(isinstance(value['created_at'],str), 'REQUEST_TIME')
    try:
        require(datetime.fromisoformat(value['created_at']).utcoffset() is not None,'REQUEST_TIME')
    except ValueError as exc:
        raise DeliveryRefused('REQUEST_TIME') from exc
    require(value['candidate']['commit'] != value['predecessor']['commit']
            and value['candidate']['image'] != value['predecessor']['image'], 'SUCCESSOR_REQUIRED')
    paths = value['allowed_delta']
    require(isinstance(paths, list) and paths and all(isinstance(p,str) for p in paths)
            and len(paths) == len(set(paths)),
            'REQUEST_DELTA_SHAPE')
    for name in paths:
        require(isinstance(name, str) and (name.startswith(('sentinel/', 'scripts/', 'tests/', 'docs/', 'tools/'))
                or name in REVIEWED_HOST_ARTIFACTS)
                and '\\' not in name and '..' not in name.split('/')
                and '/.env' not in name and not name.endswith('.env'), 'REQUEST_DELTA_PATH')
    return value


class Journal:
    """A single-operation stage journal with a checked digest-linked history."""
    def __init__(self, folder):
        self.folder = Path(folder).resolve()
        self.request = validate_request(read_json(self.folder/'request.json'))
        self.subject = digest(self.request)
        self.stages = LEGACY_STAGES if self.request['schema'] == LEGACY_SCHEMA else STAGES

    def read(self):
        path = self.folder/'receipt.json'
        if not path.exists():
            require(self.request['schema']==SCHEMA,'LEGACY_DELIVERY_CANNOT_RESUME')
            return dict(schema=SCHEMA, operation_id=self.request['operation_id'],
                        request_sha256=self.subject, stage='NEW', history=[], artifacts={})
        value = read_json(path)
        require(set(value) == {'schema', 'operation_id', 'request_sha256', 'stage',
                               'history', 'artifacts'}, 'RECEIPT_SHAPE')
        require(value['schema'] == self.request['schema'] and value['operation_id'] == self.request['operation_id']
                and value['request_sha256'] == self.subject, 'RECEIPT_REQUEST_MISMATCH')
        require(isinstance(value['history'], list) and len(value['history']) < len(self.stages)
                and isinstance(value['artifacts'], dict), 'RECEIPT_HISTORY_SHAPE')
        previous = self.subject
        for index, event in enumerate(value['history'], 1):
            require(set(event) == {'stage', 'at', 'previous', 'artifacts_sha256', 'sha256'},
                    'RECEIPT_EVENT_SHAPE')
            require(event['stage'] == self.stages[index] and event['previous'] == previous,
                    'RECEIPT_EVENT_ORDER')
            require(event['sha256'] == digest({k:v for k,v in event.items() if k!='sha256'}),
                    'RECEIPT_EVENT_DIGEST')
            previous = event['sha256']
        require(len(value['history']) < len(self.stages)
                and value['stage'] == self.stages[len(value['history'])], 'RECEIPT_STAGE')
        require(self.request['schema'] != LEGACY_SCHEMA or value['stage']=='VERIFIED',
                'LEGACY_DELIVERY_CANNOT_RESUME')
        if value['history']:
            require(value['history'][-1]['artifacts_sha256'] == digest(value['artifacts']),
                    'RECEIPT_ARTIFACTS_CHANGED')
        return value

    def advance(self, expected, stage, **artifacts):
        require(self.request['schema']==SCHEMA,'LEGACY_DELIVERY_CANNOT_RESUME')
        current = self.read()
        require(current['stage'] == expected and STAGES.index(stage) == STAGES.index(expected)+1,
                'RECEIPT_STAGE_CONFLICT')
        require(all(key not in current['artifacts'] or current['artifacts'][key] == value
                    for key, value in artifacts.items()), 'RECEIPT_ARTIFACT_REPLACEMENT')
        current['artifacts'].update(artifacts)
        event = dict(stage=stage, at=utcnow().isoformat(),
                     previous=current['history'][-1]['sha256'] if current['history'] else self.subject,
                     artifacts_sha256=digest(current['artifacts']))
        event['sha256'] = digest(event)
        current['history'].append(event)
        current['stage'] = stage
        atomic_json(self.folder/'receipt.json', current)
        return current
