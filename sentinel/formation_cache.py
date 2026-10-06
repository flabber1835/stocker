"""Authenticated disposable formation work, shared by preview and admission.

This cache contains canonical candidate state, never a decision or authority.
Its complete source/plan/runtime binding prevents promotion by relabelling it.
"""
import hmac
import json
import os
from pathlib import Path
import tempfile

from sentinel import identity, observation_storage
from sentinel.core.formation import Formation
from sentinel.feed import publication, progress
from sentinel.feed.rolling_contract import canonical_json, digest

SCHEMA = 'sentinel.formation-work-cache/1'
MAX_BYTES = 32 * 1024 * 1024
MAX_PLANS = 4


def location(plan):
    state_dir = os.environ.get('SENTINEL_STATE_DIR')
    if not state_dir:
        return None
    # Preview is read-only with respect to financial state and deliberately has
    # no feed-writer capability. Bind actual imported code and dependencies,
    # rather than requiring a mutation authorization merely to reuse math.
    environment = identity.environment()
    if not environment['sources_known']:
        raise ValueError('FORMATION_CACHE_RUNTIME_IDENTITY_UNKNOWN')
    producer = {key: environment[key] for key in (
        'sentinel_source', 'wealth_core_source', 'distributions_hash',
        'calendar_version', 'python', 'image_lock_sha256')}
    context = {'schema': SCHEMA, 'plan': plan.model_dump(by_alias=True),
               'producer_sha256': digest(producer)}
    return Path(state_dir) / 'formation-cache' / (digest(context) + '.json'), context


def _signature(context, checkpoint):
    return publication._receipt_hmac({'purpose': SCHEMA, 'context': context,
                                     'checkpoint_sha256': checkpoint['sha256']})


def load(bound, plan):
    if bound is None:
        return None
    path, context = bound
    try:
        with path.open('rb') as source:
            encoded = source.read(MAX_BYTES + 1)
    except FileNotFoundError:
        return None
    if len(encoded) > MAX_BYTES:
        raise ValueError('FORMATION_CACHE_SIZE_EXCEEDED')
    value = json.loads(encoded)
    if set(value) != {'context', 'checkpoint', 'hmac_sha256'} or value['context'] != context:
        raise ValueError('FORMATION_CACHE_CONTEXT_CHANGED')
    checkpoint = observation_storage.decode(value['checkpoint'])
    if not hmac.compare_digest(str(value['hmac_sha256']), _signature(context, checkpoint)):
        raise ValueError('FORMATION_CACHE_AUTHENTICATION_FAILED')
    return Formation.resume(checkpoint, plan=plan)


def save(bound, formed):
    if bound is None:
        return
    path, context = bound
    checkpoint = formed.checkpoint()
    value = dict(context=context, checkpoint=observation_storage.encode(checkpoint, 'state'),
                 hmac_sha256=_signature(context, checkpoint))
    encoded = canonical_json(value).encode('utf-8')
    if len(encoded) > MAX_BYTES:
        raise ValueError('FORMATION_CACHE_SIZE_EXCEEDED')
    path.parent.mkdir(parents=True, exist_ok=True)
    name = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix='candidate-', delete=False) as output:
            name = output.name
            output.write(encoded)
            output.flush()
            os.fsync(output.fileno())
        os.replace(name, path)
        name = None
        siblings = sorted(path.parent.glob('*.json'), key=lambda p: p.stat().st_mtime,
                          reverse=True)
        for expired in siblings[MAX_PLANS:]:
            if expired != path and len(expired.stem) == 64 and all(
                    char in '0123456789abcdef' for char in expired.stem):
                expired.unlink(missing_ok=True)
    finally:
        if name is not None:
            Path(name).unlink(missing_ok=True)


def reusable(bound, plan):
    """A failed optimization never becomes an admitted financial checkpoint."""
    try:
        return load(bound, plan)
    except (OSError, ValueError, TypeError, KeyError):
        progress.emit('historical_formation', 'working', reason='DISPOSABLE_CACHE_REFUSED')
        return None


def remember(bound, formed):
    try:
        save(bound, formed)
    except (OSError, ValueError):
        progress.emit('historical_formation', 'working', reason='DISPOSABLE_CACHE_WRITE_UNAVAILABLE')
