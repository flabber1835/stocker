"""Versioned correction data, captured once and bound to snapshot evidence."""
from __future__ import annotations

import copy
import hmac
import json
import os
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

from sentinel.feed.correction_model import CorrectionRefused, MAX_BYTES, validate
from sentinel.feed.rolling_contract import digest

BOOTSTRAP = Path(__file__).resolve().parents[2] / 'data/sharadar/source-corrections-v1.json'
_PIN = ContextVar('source_correction_dataset', default=None)


def root():
    return Path(os.environ.get('SENTINEL_STATE_DIR', '/var/lib/sentinel')) / 'source-corrections-v1'


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise CorrectionRefused('duplicate correction JSON field: ' + key)
        result[key] = value
    return result


def read(path):
    try:
        with path.open('rb') as stream:
            data = stream.read(MAX_BYTES + 4097)
        if len(data) > MAX_BYTES + 4096:
            raise CorrectionRefused('correction file exceeds byte bound')
        return json.loads(data, object_pairs_hook=_pairs)
    except (OSError, ValueError) as exc:
        raise CorrectionRefused('correction file unavailable or invalid') from exc


def bootstrap():
    return validate(read(BOOTSTRAP))


def signature(payload):
    from sentinel.feed.publication import _receipt_hmac
    try:
        return _receipt_hmac({'purpose': 'sentinel.source-correction-install/1', 'installation': payload})
    except RuntimeError as exc:
        raise CorrectionRefused("correction signing key unavailable") from exc


def authenticated(envelope):
    """Validate a signed immutable record independently of the active pointer."""
    if not isinstance(envelope, dict) or set(envelope) != {'installation', 'hmac_sha256'}:
        raise CorrectionRefused('invalid correction installation envelope')
    payload = envelope['installation']
    if (not isinstance(payload, dict)
            or set(payload) != {'dataset', 'parent_sha256', 'reviewer', 'installed_at'}
            or not hmac.compare_digest(str(envelope['hmac_sha256']), signature(payload))):
        raise CorrectionRefused('correction installation authentication failed')
    value = validate(payload['dataset'])
    from sentinel.feed.correction_model import require_extension
    require_extension(bootstrap(), value)
    return value


def installed():
    directory = root()
    try:
        directory.stat()
    except FileNotFoundError:
        return bootstrap()
    envelope = read(directory / 'current.json')
    value = authenticated(envelope)
    retained = read(directory / (digest(value) + '.json'))
    if retained != envelope:
        raise CorrectionRefused('installed correction version differs from immutable record')
    return value


def current():
    selected = _PIN.get()
    return copy.deepcopy(selected) if selected is not None else installed()


@contextmanager
def using(value):
    token = _PIN.set(validate(value))
    try:
        yield
    finally:
        _PIN.reset(token)


def coverage_exceptions():
    from sentinel.feed.source_authority.seed_model import _exception, _terminal_exception
    result = {}
    for row in current()['coverage']:
        fields = [row[key] for key in ('session', 'permaticker', 'ticker', 'category')]
        item = (_exception(*fields, row['first_session'], row['first_observed'])
                if row['kind'] == 'SESSION_ABSENCE' else _terminal_exception(*fields, row['last_session']))
        result[(item.session, item.permaticker)] = item
    return result
