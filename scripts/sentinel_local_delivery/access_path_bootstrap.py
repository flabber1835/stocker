"""Read-only schema-admission metadata; never a candidate canonical proof."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re

from .model import Journal, digest, read_json, require
from .qualification import sha256_file

SCHEMA = 'sentinel.checkpoint-access-bootstrap/1'
INSTALLED_SCHEMA = 'sentinel.checkpoint-access-installed/1'
REQUEST_SCHEMA = 'sentinel.local-paper-delivery/5'
PHASE = 'POST_SCHEMA_ACCESS_PATH'
CHILD_SECONDS = 60
CONTRACT_KEYS = frozenset({'schema', 'authority_effect', 'request_sha256', 'operation_id',
    'predecessor', 'candidate', 'state_sha256', 'predecessor_proof_sha256',
    'system_identifier', 'operational_installation_sha256', 'access_contract_sha256'})
_METADATA_KEYS = frozenset({'transaction_read_only', 'system_identifier',
    'operational_installation_sha256', 'access_contract_sha256', 'access_installation_sha256'})

# This child reads only authenticated installation rows and catalog metadata.
# The coordinator separately owns the unchanged complete financial proof.
PROBE = r'''import hashlib,json,os,sys
import psycopg
from psycopg.conninfo import make_conninfo
from sentinel import operational_schema,checkpoint_lineage_access as access
mode=sys.argv[1]
assert mode in ('absent','installed')
def sha(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),
        ensure_ascii=True,allow_nan=False).encode('ascii')).hexdigest()
dsn=make_conninfo(os.environ['SENTINEL_DATABASE_URL'],connect_timeout=5,
    options='-c default_transaction_read_only=on -c statement_timeout=15000 -c lock_timeout=1000')
with psycopg.connect(dsn) as conn:
    conn.read_only=True
    assert conn.execute('SHOW transaction_read_only').fetchone()[0]=='on'
    assert conn.execute('SHOW statement_timeout').fetchone()[0]=='15s'
    assert conn.execute('SHOW lock_timeout').fetchone()[0]=='1s'
    assert operational_schema.require_schema(conn)
    original=operational_schema.installation(conn,required=True)
    installation=access.installation(conn,required=(mode=='installed'))
    if mode=='absent':
        assert installation is None,'ACCESS_COMPONENT_ALREADY_INSTALLED'
    system=str(conn.execute('SELECT system_identifier::text FROM pg_control_system()').fetchone()[0])
    output=dict(transaction_read_only=conn.read_only,system_identifier=system,
        operational_installation_sha256=sha(original),access_contract_sha256=access._contract(),
        access_installation_sha256=None if installation is None else sha(installation))
    conn.rollback()
print(json.dumps(output,sort_keys=True))
'''


def _selected(host):
    request = host.request
    require(getattr(host, 'supports_post_schema_access_path', False) is True
        and request.get('schema') == REQUEST_SCHEMA
        and request.get('canonical_proof_phase') == PHASE
        and request.get('handoff_mode') == 'PRE_OPEN', 'ACCESS_BOOTSTRAP_NOT_SELECTED')


def _bindings(host, state):
    _selected(host)
    request = host.request
    require(isinstance(state, dict) and isinstance(state.get('system'), str)
        and state['system'].isdigit() and state['system'] == request['predecessor']['system'],
        'ACCESS_BOOTSTRAP_DATABASE_CHANGED')
    return dict(request_sha256=digest(request), operation_id=request['operation_id'],
        predecessor={key: request['predecessor'][key] for key in ('commit', 'image')},
        candidate=deepcopy(request['candidate']), state_sha256=digest(state),
        system_identifier=state['system'])


def _predecessor(host, state, retained):
    require(isinstance(retained, dict) and bool(retained), 'ACCESS_BOOTSTRAP_RETAINED_PROOF_REQUIRED')
    built = read_json(host.operation_dir/'build.json')
    require(built['foundation'] == host.request['predecessor']
        and built['commit'] == host.request['candidate']['commit']
        and built['image'] == host.request['candidate']['image']
        and built['source_identity'] == host.request['candidate']['source_identity']
        and built['source'] == host.request['source']
        and built['deployment'] == host.request['deployment'], 'ACCESS_BOOTSTRAP_BUILD_CHANGED')
    anchor = built['predecessor_receipt']
    require(not getattr(host, 'allow_started_predecessor', False)
        and anchor.get('allow_started', False) is False, 'ACCESS_BOOTSTRAP_STARTED_PREDECESSOR')
    selected = Path(anchor['path'])
    require(selected.is_absolute() and selected.name == 'receipt.json'
        and selected == Path(host.predecessor_receipt)
        and not any(path.is_symlink() for path in (selected, *selected.parents)),
        'ACCESS_BOOTSTRAP_PREDECESSOR_PATH')
    require(sha256_file(selected) == anchor['sha256'], 'ACCESS_BOOTSTRAP_ANCHOR_CHANGED')
    prior = Journal(selected.parent)
    record = prior.read()
    require(record['stage'] == 'VERIFIED', 'ACCESS_BOOTSTRAP_VERIFIED_PREDECESSOR_REQUIRED')
    require(all(prior.request['candidate'][key] == host.request['predecessor'][key]
                for key in ('commit', 'image')), 'ACCESS_BOOTSTRAP_PREDECESSOR_RUNTIME_CHANGED')
    proof = record['artifacts']['canonical_proof']
    require(proof == retained
        and record['artifacts'].get('successor_proof_sha256') == digest(retained)
        and host.predecessor_canonical_proof(state) == retained,
        'ACCESS_BOOTSTRAP_PREDECESSOR_PROOF_CHANGED')
    require(sha256_file(selected) == anchor['sha256'], 'ACCESS_BOOTSTRAP_ANCHOR_CHANGED')


def _metadata(host, *, installed):
    values = host.candidate_values(host.load_values())
    candidate = host.request['candidate']
    require(values['SENTINEL_GIT_COMMIT'] == candidate['commit']
        and all(values[key] == candidate['image'] for key in ('SENTINEL_RUNTIME_IMAGE_DIGEST',
            'SENTINEL_TEST_IMAGE_DIGEST', 'SENTINEL_RUNTIME_IMAGE_REF', 'SENTINEL_LOCAL_PAPER_IMAGE')),
        'ACCESS_BOOTSTRAP_CANDIDATE_CHANGED')
    result = host.compose(values, 'run', '--rm', '--no-deps', '--pull', 'never',
        '--entrypoint', 'python', 'sentinel-authorized-cli', '-B', '-c', PROBE,
        'installed' if installed else 'absent', timeout=CHILD_SECONDS)
    require(len(result.stdout) <= 8192, 'ACCESS_BOOTSTRAP_METADATA_BOUND')
    value = json.loads(result.stdout)
    require(isinstance(value, dict) and set(value) == _METADATA_KEYS
        and value['transaction_read_only'] is True
        and isinstance(value['system_identifier'], str) and value['system_identifier'].isdigit()
        and all(isinstance(value[key], str) and re.fullmatch('[0-9a-f]{64}', value[key])
            for key in ('operational_installation_sha256', 'access_contract_sha256')),
        'ACCESS_BOOTSTRAP_METADATA_INVALID')
    access = value['access_installation_sha256']
    require((isinstance(access, str) and re.fullmatch('[0-9a-f]{64}', access) is not None)
            if installed else access is None, 'ACCESS_BOOTSTRAP_COMPONENT_STATE_CHANGED')
    return value


def preflight(host, state, retained):
    """Authenticate predecessor and clean absence without financial qualification."""
    bound = _bindings(host, state)
    _predecessor(host, state, retained)
    metadata = _metadata(host, installed=False)
    require(metadata['system_identifier'] == bound['system_identifier'], 'ACCESS_BOOTSTRAP_DATABASE_CHANGED')
    return dict(schema=SCHEMA, authority_effect='NONE', **bound,
        predecessor_proof_sha256=digest(retained),
        operational_installation_sha256=metadata['operational_installation_sha256'],
        access_contract_sha256=metadata['access_contract_sha256'])


def post_schema(host, state, contract):
    """Authenticate installed access metadata; never mint a canonical result."""
    bound = _bindings(host, state)
    require(isinstance(contract, dict) and set(contract) == CONTRACT_KEYS
        and contract['schema'] == SCHEMA and contract['authority_effect'] == 'NONE'
        and all(contract[key] == value for key, value in bound.items())
        and all(isinstance(contract[key], str) and re.fullmatch('[0-9a-f]{64}', contract[key])
            for key in ('predecessor_proof_sha256', 'operational_installation_sha256', 'access_contract_sha256')),
        'ACCESS_BOOTSTRAP_CONTRACT_CHANGED')
    metadata = _metadata(host, installed=True)
    require(all(metadata[key] == contract[key] for key in ('system_identifier',
        'operational_installation_sha256', 'access_contract_sha256')), 'ACCESS_BOOTSTRAP_INSTALLATION_CHANGED')
    return dict(schema=INSTALLED_SCHEMA, authority_effect='NONE',
        **{key: contract[key] for key in ('request_sha256', 'state_sha256', 'system_identifier',
            'operational_installation_sha256', 'access_contract_sha256')},
        access_installation_sha256=metadata['access_installation_sha256'])
