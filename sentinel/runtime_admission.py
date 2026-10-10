"""Explicit compatible executable admission over immutable rolling provenance."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import hmac
import json
import os
from pathlib import Path
from typing import Literal

from pydantic import Field
from sentinel import identity, rolling_checkpoint as origin, shadow_runtime
from sentinel.feed import publication
from sentinel.feed.rolling_contract import Contract, Digest, canonical_json, digest

SCHEMA = 'sentinel.retained-runtime-admission/1'
PREFIX = 'runtime-admission:v1:'
Refused = origin.RollingColdStartRefused
ADDITIONS = {'runtime_admission.py', 'semantic_source_basis.py', 'retained_go.py', 'retained_parity.py',
             'economic_migration.py', 'core/cash_distributions.py', 'execution_upgrade.py',
             'retained_readiness_upgrade.py', 'dual_plan_renewal_upgrade.py',
             'operational_liveness_upgrade.py', 'operational_runtime_upgrade.py',
             'callback_liveness_upgrade.py'}
ADMINISTRATIVE = {'shadow_supervisor.py', 'observation_authority.py', 'observation_startup.py'}
SEAMS = {'core/decision.py': 'sentinel.core.decision',
         'rolling_checkpoint.py': 'sentinel.rolling_checkpoint',
         'rolling_daily_checkpoint.py': 'sentinel.rolling_daily_checkpoint'}


class SourceManifest(Contract):
    schema_id: Literal['sentinel.retained-source-manifest/1'] = Field(alias='schema')
    revision: str = Field(pattern=r'^[0-9a-f]{40}$')
    files: dict[str, Digest]
    seam_sources: dict[str, str] = Field(default_factory=dict)


class Admission(Contract):
    schema_id: Literal['sentinel.retained-runtime-admission/1'] = Field(default=SCHEMA, alias='schema')
    authority_effect: Literal['NONE'] = 'NONE'
    observation_id: str
    origin_sha256: Digest
    book_runtime_sha256: Digest
    process_sha256: Digest
    strategy_sha256: Digest
    manifest_sha256: Digest
    pitr: dict


class EconomicAdmission(Admission):
    schema_id: Literal['sentinel.retained-runtime-admission/2'] = Field(
        default='sentinel.retained-runtime-admission/2', alias='schema')
    migration_profile_sha256: Digest
    origin_strategy_sha256: Digest


def process_binding(runtime):
    # Genesis provenance remains immutable; the live publication is independently
    # checked by every rolling reader. A GO publication subject cannot rebase it.
    return {key: value for key, value in runtime.items()
            if key != 'validated_data_publication_sha256'}


def current_context(*, observation_id, starting_cash):
    """Actual-image GO context, not authorization or persisted configuration."""
    from sentinel import rolling_initialization as initial
    source = identity.rehearsal_identity()
    env, artifacts = source['environment'], source['deployment_artifacts']
    if identity.certification_verdict(env, artifacts)['certified'] is not True:
        raise Refused('RETAINED_CURRENT_EXECUTABLE_UNCERTIFIED')
    name = initial.shadow._observation_id(observation_id)
    cash = shadow_runtime._starting_cash(starting_cash)
    if os.environ.get('SENTINEL_SHADOW_PUBLICATION_TIMING_POLICY', shadow_runtime.SHADOW_PUBLICATION_TIMING_POLICY) != shadow_runtime.SHADOW_PUBLICATION_TIMING_POLICY:
        raise Refused('RETAINED_PUBLICATION_POLICY_CHANGED')
    controller, strategy = shadow_runtime._strategy()
    reviewed = {'schema': 'sentinel.shadow-reviewed-config/1', 'observation_id': name,
        'starting_cash': format(cash.normalize(), 'f'),
        'execution_model': shadow_runtime.SHADOW_EXECUTION_MODEL,
        'cutoff_policy': shadow_runtime.SHADOW_CUTOFF_POLICY,
        'publication_timing_policy': shadow_runtime.SHADOW_PUBLICATION_TIMING_POLICY,
        'validated_source_identity_sha256': source['identity_hash']}
    runtime = {'schema': 'sentinel.shadow-runtime-identity/1',
        'validated_source_identity_sha256': source['identity_hash'],
        'environment_identity_sha256': source['identity_hash'],
        'sentinel_source_sha256': env['sentinel_source']['hash'],
        'wealth_core_source_sha256': env['wealth_core_source']['hash'],
        'git_commit': artifacts['git_commit'], 'runtime_image_digest': artifacts['runtime_image_digest'],
        'validated_shadow_config_sha256': digest(reviewed),
        'validated_data_publication_sha256': os.environ.get('SENTINEL_VALIDATED_DATA_PUBLICATION_SHA256', '0'*64),
        'reviewed_shadow_config': reviewed}
    return {'observation_id': name, 'starting_cash': reviewed['starting_cash'],
            'controller': controller, 'strategy': strategy, 'runtime': runtime}


def _key(context):
    return PREFIX + context['observation_id'] + ':' + digest(process_binding(context['runtime']))


def _signature(value):
    return publication._receipt_hmac({'purpose': SCHEMA, 'admission': value})


def _require_context(checkpoint, context):
    from sentinel.economic_migration import compatible
    old = checkpoint.runtime_identity['reviewed_shadow_config']
    new = context['runtime']['reviewed_shadow_config']
    without_source = lambda value: {k: v for k, v in value.items() if k != 'validated_source_identity_sha256'}
    if (checkpoint.observation_id != context['observation_id']
            or checkpoint.starting_cash != context['starting_cash']
            or (checkpoint.strategy_identity != context['strategy']
                and not compatible(checkpoint.strategy_identity, context['strategy']))
            or without_source(old) != without_source(new)):
        raise Refused('RETAINED_BOOK_CONFIGURATION_CHANGED')


def _require_binding(value, checkpoint, context):
    _require_context(checkpoint, context)
    if (value.observation_id != context['observation_id']
            or value.origin_sha256 != digest(checkpoint.model_dump(by_alias=True))
            or value.book_runtime_sha256 != digest(checkpoint.runtime_identity)
            or value.process_sha256 != digest(process_binding(context['runtime']))
            or value.strategy_sha256 != digest(context['strategy'])):
        raise Refused('RETAINED_RUNTIME_ADMISSION_BINDING_CHANGED')
    if checkpoint.strategy_identity != context['strategy']:
        from sentinel.economic_migration import PROFILE_SHA256
        if (not isinstance(value, EconomicAdmission)
                or value.migration_profile_sha256 != PROFILE_SHA256
                or value.origin_strategy_sha256 != digest(checkpoint.strategy_identity)):
            raise Refused('RETAINED_ECONOMIC_MIGRATION_ADMISSION_REQUIRED')


def _decode(row, checkpoint):
    raw = row[1]
    if (not isinstance(raw, dict) or set(raw) != {'admission', 'hmac_sha256'}
            or not isinstance(raw['admission'], dict)
            or not hmac.compare_digest(str(raw['hmac_sha256']), _signature(raw['admission']))):
        raise Refused('RETAINED_RUNTIME_ADMISSION_AUTHENTICATION_FAILED')
    cls = EconomicAdmission if raw['admission'].get('schema') == 'sentinel.retained-runtime-admission/2' else Admission
    value = cls.model_validate(raw['admission'])
    if raw['admission'] != value.model_dump(by_alias=True) or str(row[0]) != checkpoint.session:
        raise Refused('RETAINED_RUNTIME_ADMISSION_SHAPE_CHANGED')
    return value


def read(conn, context, checkpoint):
    row = conn.execute('SELECT session,state FROM sentinel_processed_sessions WHERE cursor_name=%s', (_key(context),)).fetchone()
    if row is None:
        return None
    value = _decode(row, checkpoint)
    _require_binding(value, checkpoint, context)
    return value


def _require_retained_strategy(conn, checkpoint, context, stored):
    if stored in (checkpoint.strategy_identity, context['strategy']):
        return
    from sentinel.economic_migration import POLICY, PROFILE_SHA256, compatible
    if (stored.get('cash_distribution_policy') != POLICY
            or context['strategy'].get('cash_distribution_policy') != POLICY
            or not compatible(stored, context['strategy'])):
        raise Refused('RETAINED_ECONOMIC_CHECKPOINT_IDENTITY_CHANGED')
    prefix = PREFIX + context['observation_id'] + ':'
    # Select only the small administrative namespace, never financial history.
    rows = conn.execute('SELECT cursor_name,session,state FROM sentinel_processed_sessions '
        "WHERE cursor_name LIKE %s AND state->'admission'->>'strategy_sha256'=%s",
        (prefix + '%', digest(stored)))
    found = False
    for cursor, session, raw in rows:
        value = _decode((session, raw), checkpoint)
        if (not isinstance(value, EconomicAdmission)
                or cursor != prefix + value.process_sha256
                or value.observation_id != context['observation_id']
                or value.origin_sha256 != digest(checkpoint.model_dump(by_alias=True))
                or value.book_runtime_sha256 != digest(checkpoint.runtime_identity)
                or value.strategy_sha256 != digest(stored)
                or value.migration_profile_sha256 != PROFILE_SHA256
                or value.origin_strategy_sha256 != digest(checkpoint.strategy_identity)):
            raise Refused('RETAINED_INTERMEDIATE_ADMISSION_BINDING_CHANGED')
        found = True
    if not found:
        raise Refused('RETAINED_INTERMEDIATE_ADMISSION_REQUIRED')


def bind_context(conn, context):
    checkpoint = origin.read(conn)
    if checkpoint is None:
        return
    if checkpoint.runtime_identity == context['runtime']:
        return  # The ordinary checkpoint guards retain their exact contract.
    if (checkpoint.runtime_identity.get('schema') != 'sentinel.shadow-runtime-identity/1'
            or context['runtime'].get('schema') != 'sentinel.shadow-runtime-identity/1'):
        return  # Unknown identities cannot gain a compatibility fallback.
    _require_context(checkpoint, context)
    if process_binding(checkpoint.runtime_identity) != process_binding(context['runtime']):
        if read(conn, context, checkpoint) is None:
            raise Refused('RETAINED_RUNTIME_ADMISSION_REQUIRED')
    from sentinel import rolling_daily_checkpoint as daily
    current = daily.read(conn)
    stored = checkpoint.strategy_identity if current is None else current.strategy_identity
    _require_retained_strategy(conn, checkpoint, context, stored)
    context['runtime'] = checkpoint.runtime_identity
    context['strategy'] = stored


def _retained_checkpoint(conn):
    """Authenticate both identities without loading or rewriting a strategy book."""
    checkpoint = origin.read(conn)
    if checkpoint is None:
        return None, None, None
    context = current_context(observation_id=os.environ.get('SENTINEL_SHADOW_OBSERVATION_ID', 'primary'),
        starting_cash=os.environ.get('SENTINEL_SHADOW_STARTING_CASH', '50000'))
    selected = context['strategy']
    bind_context(conn, context)
    from sentinel import rolling_daily_checkpoint as daily
    retained = daily.read(conn) or checkpoint
    if (retained.observation_id != context['observation_id']
            or retained.starting_cash != context['starting_cash']
            or retained.runtime_identity != context['runtime']
            or retained.strategy_identity != context['strategy']
            or (retained is not checkpoint
                and retained.origin_sha256 != digest(checkpoint.model_dump(by_alias=True)))):
        raise Refused('RETAINED_PUBLICATION_CHECKPOINT_BINDING_CHANGED')
    return retained, context, selected


def retained_publication_strategy(conn, pub):
    """Exact authenticated retained publication, never arbitrary input reuse."""
    retained, context, _ = _retained_checkpoint(conn)
    if retained is None:
        return None
    return context['strategy'] if retained.publication == pub.to_dict() else None


def require_retained_state(conn, *, strategy, state_strategy, state_sha256, session):
    """Bind dual-shadow adapter input to the current executable's admission."""
    retained, context, selected = _retained_checkpoint(conn)
    if (retained is None or strategy != selected or state_strategy != context['strategy']
            or state_sha256 != retained.state_sha256 or session != retained.session):
        raise Refused('RETAINED_ADAPTER_STATE_BINDING_CHANGED')


def source_closure(files):
    h = hashlib.sha256()
    for name, sha in sorted(files.items()):
        path = Path(name)
        if (path.is_absolute() or '..' in path.parts or path.as_posix() != name
                or not name.endswith('.py') or '\\' in name or '__pycache__' in path.parts):
            raise Refused('RETAINED_SOURCE_MANIFEST_PATH_INVALID')
        h.update(name.encode() + b'\0' + sha.encode() + b'\n')
    return h.hexdigest()


def prove_compatibility(manifest, checkpoint, context, *, source=None):
    from sentinel import semantic_source_basis as basis
    from sentinel.economic_migration import profile
    profile()
    from sentinel.execution_upgrade import profile as execution_profile
    execution_profile()
    from sentinel.retained_readiness_upgrade import profile as readiness_profile
    readiness_profile()
    from sentinel.dual_plan_renewal_upgrade import profile as renewal_profile
    renewal_profile()
    from sentinel.operational_liveness_upgrade import profile as liveness_profile
    liveness_profile()
    from sentinel import operational_runtime_upgrade as operational_upgrade
    operational_profile = operational_upgrade.profile()
    from sentinel import callback_liveness_upgrade as callback_upgrade
    callback_upgrade.profile()
    manifest = SourceManifest.model_validate(manifest)
    source = source or identity.rehearsal_identity()
    _require_context(checkpoint, context)
    old = checkpoint.runtime_identity
    if (manifest.revision != old['git_commit']
            or source_closure(manifest.files) != old['sentinel_source_sha256']):
        raise Refused('RETAINED_SOURCE_MANIFEST_ORIGIN_MISMATCH')
    env = deepcopy(source['environment'])
    current = identity._imported_package_root('sentinel')
    actual = {p.relative_to(current).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
              for p in current.rglob('*.py') if '__pycache__' not in p.parts}
    operational_additions = operational_upgrade.additions_allowed(actual)
    if (source_closure(actual) != context['runtime']['sentinel_source_sha256']
            or env['wealth_core_source']['hash'] != old['wealth_core_source_sha256']
            or set(manifest.files) - set(actual)
            or set(actual) - set(manifest.files) - ADDITIONS - operational_additions
            or (set(actual) & set(operational_profile['additions'])) - operational_additions):
        raise Refused('RETAINED_SOURCE_CLOSURE_CHANGED')
    for name, previous in manifest.files.items():
        if actual[name] == previous or name in (ADMINISTRATIVE | ADDITIONS):
            continue
        module = SEAMS.get(name)
        from sentinel.economic_migration import source_allowed
        if source_allowed(name, previous, actual[name]):
            continue
        from sentinel.execution_upgrade import source_allowed as execution_source_allowed
        if execution_source_allowed(name, previous, actual[name]):
            continue
        from sentinel.retained_readiness_upgrade import source_allowed as readiness_source_allowed
        if readiness_source_allowed(name, previous, actual[name]):
            continue
        from sentinel.dual_plan_renewal_upgrade import source_allowed as renewal_source_allowed
        if renewal_source_allowed(name, previous, actual[name]):
            continue
        from sentinel.operational_liveness_upgrade import source_allowed as liveness_source_allowed
        if liveness_source_allowed(name, previous, actual[name]):
            continue
        if operational_upgrade.source_allowed(name, previous, actual[name]):
            continue
        if callback_upgrade.source_allowed(name, previous, actual[name]):
            continue
        if module is None:
            raise Refused('RETAINED_ECONOMIC_SOURCE_CHANGED:' + name)
        contribution = basis.canonical_contribution(module, (current/name).read_bytes())
        if previous != contribution:
            prior_bytes = manifest.seam_sources.get(name, '').encode()
            if (hashlib.sha256(prior_bytes).hexdigest() != previous
                    or basis.canonical_contribution(module, prior_bytes) != contribution):
                raise Refused('RETAINED_ECONOMIC_SOURCE_CHANGED:' + name)
    env['sentinel_source'].update(hash=old['sentinel_source_sha256'], files=len(manifest.files))
    restored = hashlib.sha256(json.dumps(env, sort_keys=True).encode()).hexdigest()
    if restored != old['environment_identity_sha256']:
        raise Refused('RETAINED_COMPUTATIONAL_ENVIRONMENT_CHANGED')
    return digest(manifest.model_dump(by_alias=True))


def _fence(conn):
    from sentinel.automation.store import load_control
    from sentinel.execution.states import CommandState, blocks_overlapping
    control = load_control(conn, for_update=True)
    if control.enabled or not control.kill_switch_engaged:
        raise Refused('RETAINED_ADMISSION_REQUIRES_DISABLED_KILLED_STATE')
    for row in conn.execute('SELECT state FROM sentinel_commands'):
        if blocks_overlapping(CommandState(row[0])):
            raise Refused('RETAINED_ADMISSION_REQUIRES_COMMAND_RECONCILIATION')


def admit(conn, *, context, manifest):
    """One administrative append after full historical closure authentication."""
    from sentinel import backup_runtime_authority, rolling_runtime
    from sentinel.execution import journal
    try:
        with journal.writer_lock(conn):
            actual = current_context(observation_id=context['observation_id'], starting_cash=context['starting_cash'])
            if (process_binding(actual['runtime']) != process_binding(context['runtime'])
                    or actual['strategy'] != context['strategy']):
                raise Refused('RETAINED_ADMISSION_CURRENT_PROCESS_CHANGED')
            _fence(conn)
            checkpoint = origin.read(conn)
            if checkpoint is None:
                raise Refused('RETAINED_ORIGIN_REQUIRED')
            _require_context(checkpoint, context)
            existing = read(conn, context, checkpoint)
            if existing:
                rolling_runtime._closure(conn, dict(context))
                conn.rollback()
                return existing
            manifest_sha = prove_compatibility(manifest, checkpoint, context)
            from sentinel import rolling_daily_checkpoint as daily
            retained = daily.read(conn)
            original = {**context, 'runtime': checkpoint.runtime_identity,
                        'strategy': checkpoint.strategy_identity if retained is None else retained.strategy_identity}
            rolling_runtime._closure(conn, original)
            backup_runtime_authority.require(conn, operation='compatible retained runtime admission')
            migration = checkpoint.strategy_identity != context['strategy']
            cls, extra = Admission, {}
            if migration:
                from sentinel.economic_migration import PROFILE_SHA256
                cls, extra = EconomicAdmission, {'migration_profile_sha256': PROFILE_SHA256,
                    'origin_strategy_sha256': digest(checkpoint.strategy_identity)}
            value = cls(**extra, observation_id=context['observation_id'],
                origin_sha256=digest(checkpoint.model_dump(by_alias=True)),
                book_runtime_sha256=digest(checkpoint.runtime_identity),
                process_sha256=digest(process_binding(context['runtime'])),
                strategy_sha256=digest(context['strategy']), manifest_sha256=manifest_sha,
                pitr=publication._publication_recovery_target(conn))
            payload = value.model_dump(by_alias=True)
            result = conn.execute('INSERT INTO sentinel_processed_sessions(cursor_name,session,state) VALUES (%s,%s,%s::jsonb) ON CONFLICT DO NOTHING',
                (_key(context), checkpoint.session, canonical_json({'admission': payload, 'hmac_sha256': _signature(payload)})))
            if result.rowcount != 1:
                raise Refused('RETAINED_RUNTIME_ADMISSION_CAS_CHANGED')
            _fence(conn)
            backup_runtime_authority.require(conn, operation='compatible retained runtime admission commit')
            conn.commit()
            return value
    except BaseException:
        conn.rollback()
        raise
