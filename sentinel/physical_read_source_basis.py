"""Closed physical traversal witness; unknown compiler bytes keep their identity."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re

PROFILE_SHA256 = '48b1b6ab41f43715104ad1da280c6f97ffc478070773f658c8a91fb822df7568'
PROFILE = Path(__file__).with_name('physical-read-source-transition.json')
BASE_REVISION = 'c84b7c26a170dd11c7a94521bfb391f88264987b'
BASELINES = {
    'sentinel.feed.action_history': 'dd0f4e6cdb25eac66165fb24d7bf32161cad486fe8dab70fc46facb288c17179',
    'sentinel.feed.rolling_store': 'a88e70b2e84cd763813114a7f25d35d966ac0d1a3c1c3c27f3afc5d46a81104a',
}
READ_CONTRACT_SHA256 = 'ac6a4c2b407f9f437b837c394fa1e25fdc3b5dd0849edaed9c2c4ed460567c01'
ALPACA_PAGE_COMPILER = 'sentinel.feed.rolling_builder'
ALPACA_PAGE_BEFORE = 'eeb8096ce599124edd1b82bf07e43abba66a75ee1ab917db12740b6509ea4434'


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _profile():
    if PROFILE_SHA256 == '0'*64:
        return None
    raw = PROFILE.read_bytes()
    if _sha(raw) != PROFILE_SHA256:
        raise ValueError('PHYSICAL_READ_SOURCE_WITNESS_CHANGED')
    value = json.loads(raw)
    normalized,count = re.subn(rb"^PROFILE_SHA256 = '[0-9a-f]{64}'$",
        b"PROFILE_SHA256 = '"+b'0'*64+b"'",Path(__file__).read_bytes(),flags=re.M)
    if (count != 1 or set(value) != {'schema','authority_effect','base_revision',
            'compilers','read_contract_sha256','module_sha256','alpaca_page'}
            or value['schema'] != 'sentinel.physical-read-source-transition/2'
            or value['authority_effect'] != 'NONE' or value['base_revision'] != BASE_REVISION
            or set(value['compilers']) != set(BASELINES)
            or value['module_sha256'] != _sha(normalized)
            or value['read_contract_sha256'] != READ_CONTRACT_SHA256
            or _sha(Path(__file__).with_name('feed').joinpath('read_contract.py').read_bytes()) != READ_CONTRACT_SHA256):
        raise ValueError('PHYSICAL_READ_SOURCE_WITNESS_INVALID')
    for name, record in value['compilers'].items():
        if (set(record) != {'before','after'} or record['before'] != BASELINES[name]
                or not isinstance(record['after'],str) or not re.fullmatch('[0-9a-f]{64}',record['after'])):
            raise ValueError('PHYSICAL_READ_SOURCE_COMPILER_INVALID')
    page = value['alpaca_page']
    if (set(page) != {'read_files','before','after'} or page['before'] != ALPACA_PAGE_BEFORE
            or not re.fullmatch('[0-9a-f]{64}',page['after'])
            or set(page['read_files']) != {'feed/acquisition_part_schema.py','feed/acquisition_parts.py','feed/store.py'}
            or any(not re.fullmatch('[0-9a-f]{64}',item) for item in page['read_files'].values())):
        raise ValueError('PHYSICAL_ALPACA_PAGE_COMPILER_INVALID')
    return value


def contribution(module, raw):
    actual = _sha(raw)
    if module not in BASELINES and module != ALPACA_PAGE_COMPILER:
        return actual
    value = _profile()
    if module == ALPACA_PAGE_COMPILER:
        if value is not None:
            page = value['alpaca_page']
            root = Path(__file__).parent
            if (actual == page['after'] and all(_sha((root/name).read_bytes()) == digest
                    for name,digest in page['read_files'].items())):
                return page['before']
        return actual
    if value is not None and actual == value['compilers'][module]['after']:
        return value['compilers'][module]['before']
    return actual
