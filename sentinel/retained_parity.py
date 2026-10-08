"""Bounded read-only proof of the retained canonical transition and restart."""
from __future__ import annotations

from dataclasses import fields
from decimal import Decimal
from enum import Enum
from typing import Literal, get_args, get_type_hints
from pydantic import Field, field_validator

from sentinel import rolling_checkpoint as origin, rolling_runtime, runtime_admission
from sentinel import shadow_observation as shadow
from sentinel.core.kernel import advance_session
from sentinel.core.session import (PublishedSession, SessionState, VendorBar,
    SecurityMeta, FeedAnchor, DefensiveBar, TerminalTerms)
from sentinel.core.spinoffs import SpinoffDistribution
from sentinel.feed.rolling_contract import Contract, Digest, digest

SCOPE = 'ROLLING_RETAINED_STATE_AND_RESTART'
SCHEMA = 'sentinel.retained-transition-proof/1'
SPLIT_SCHEMA = 'sentinel.retained-transition-proof/2'
Refused = origin.RollingColdStartRefused


class Checks(Contract):
    prior_unchanged: Literal[True]
    input_unchanged: Literal[True]
    restart_equivalent: Literal[True]
    result_roundtrip_equivalent: Literal[True]
    frontier_advanced: Literal[True]
    publication_version_bound: Literal[True]
    strategy_bound: Literal[True]
    decision_present: Literal[True]

    @field_validator('*', mode='before')
    @classmethod
    def exact_true(cls, value):
        if value is not True:
            raise ValueError('retained checks require exact JSON true')
        return value


class Proof(Contract):
    schema_id: Literal['sentinel.retained-transition-proof/1'] = Field(alias='schema')
    authority_effect: Literal['NONE']
    scope: Literal['ROLLING_RETAINED_STATE_AND_RESTART']
    observation_id: str = Field(pattern=r'^[A-Za-z0-9][A-Za-z0-9.-]{0,63}$')
    session: str
    origin_sha256: Digest
    checkpoint_sha256: Digest
    record_sha256: Digest
    state_sha256: Digest
    input_sha256: Digest
    prior_state_sha256: Digest
    book_runtime_sha256: Digest
    process_sha256: Digest
    strategy_sha256: Digest
    runtime_receipt_sha256: Digest
    admission_sha256: Digest | None
    checks: Checks


class SplitProof(Proof):
    schema_id: Literal['sentinel.retained-transition-proof/2'] = Field(alias='schema')
    book_strategy_sha256: Digest
    admission_sha256: Digest


def validate(value):
    model = SplitProof if isinstance(value, dict) and value.get('schema') == SPLIT_SCHEMA else Proof
    proof = model.model_validate(value)
    if value != proof.model_dump(by_alias=True):
        raise Refused('RETAINED_PROOF_SHAPE_CHANGED')
    if isinstance(proof, SplitProof) and proof.book_strategy_sha256 == proof.strategy_sha256:
        raise Refused('RETAINED_PROOF_STRATEGIES_NOT_DISTINCT')
    from sentinel.feed import calendar
    if calendar.previous_sessions(proof.session, 1) != [proof.session]:
        raise Refused('RETAINED_PROOF_SESSION_INVALID')
    return proof


def _row(cls, raw):
    if not isinstance(raw, dict) or set(raw) != {field.name for field in fields(cls)}:
        raise Refused('RETAINED_INPUT_ROW_SHAPE_CHANGED')
    hints = get_type_hints(cls)
    values = dict(raw)
    for name, annotation in hints.items():
        value = values[name]
        choices = get_args(annotation) or (annotation,)
        if value is None:
            continue
        if float in choices and str not in choices:
            if isinstance(value, bool):
                raise Refused('RETAINED_INPUT_NUMBER_INVALID')
            values[name] = float(value)
        elif Decimal in choices:
            values[name] = Decimal(value)
        elif isinstance(annotation, type) and issubclass(annotation, Enum):
            values[name] = annotation(value)
    return cls(**values)


def decode(value):
    """Round-trip every committed input field; never invent omitted evidence."""
    try:
        bar = lambda raw: None if raw is None else _row(DefensiveBar, raw)
        published = PublishedSession(session=value['session'], data_version=value['data_version'],
            bars=[_row(VendorBar, row) for row in value['bars']],
            meta={key: _row(SecurityMeta, row) for key, row in value['meta'].items()},
            sectors=value['sectors'], spy_closeadj=[None if x is None else float(x) for x in value['spy_closeadj']],
            spy_sessions=value['spy_sessions'], spy_expected_sessions=value['spy_expected_sessions'],
            terminal_events=[_row(TerminalTerms, row) for row in value['terminal_events']],
            feed_anchors={key: _row(FeedAnchor, row) for key, row in value['feed_anchors'].items()},
            defensive_bar=bar(value['defensive_bar']), defensive_previous_bar=bar(value['defensive_previous_bar']),
            signal_basis_anchors={key: _row(VendorBar, row) for key, row in value.get('signal_basis_anchors', {}).items()},
            history_proof=value.get('rolling_continuity') or value.get('current_window_continuity'),
            window_features=value.get('window_features'),
            cash_distributions=value.get('cash_distributions'),
            strategy_transition=value.get('strategy_transition'),
            spinoff_distributions=[_row(SpinoffDistribution, row) for row in value.get('spinoff_distributions', [])])
        if shadow._published_input_value(published) != value:
            raise Refused('RETAINED_INPUT_ROUNDTRIP_CHANGED')
        return published
    except (KeyError, TypeError, ValueError, ArithmeticError) as exc:
        raise Refused('RETAINED_INPUT_DECODE_REFUSED') from exc


def prove(conn, *, held, observation_id, starting_cash):
    context = runtime_admission.current_context(observation_id=observation_id, starting_cash=starting_cash)
    process = dict(context['runtime'])
    process_strategy = dict(context['strategy'])
    checkpoint, observer, retained, attested, _ = rolling_runtime._closure(conn, context)
    if checkpoint.publication != held.to_dict() or checkpoint.session != held.window_end:
        raise Refused('RETAINED_PROOF_PUBLICATION_CHANGED')
    if attested is None:
        raise Refused('RETAINED_PROOF_RUNTIME_RECEIPT_REQUIRED')
    initial = origin.read(conn)
    if hasattr(checkpoint, 'history_anchor'):
        from sentinel.feed import calendar
        previous_session = calendar.previous_sessions(checkpoint.session, 2)[0]
        store = shadow.PostgresShadowObservationStore(conn, observation_id=observation_id,
            records_from=previous_session, commit_genesis=False)
        records = store.records()
        if (len(records) != 2 or records[-1]['record_sha256'] != checkpoint.record_sha256
                or records[0]['record_sha256'] != checkpoint.history_anchor['previous_record_sha256']
                or shadow._sha256({k: v for k, v in records[0].items() if k != 'record_sha256'}) != records[0]['record_sha256']):
            raise Refused('RETAINED_PROOF_PREDECESSOR_CHANGED')
        prior = SessionState.from_dict(records[0]['state'])
        if prior.state_hash != records[-1]['prior_state_sha256'] or prior.state_hash != records[0]['state_sha256']:
            raise Refused('RETAINED_PROOF_PRIOR_STATE_CHANGED')
    else:
        prior = observer.initial_state
    published = decode(checkpoint.input_value)
    prior_hash = prior.state_hash
    restarted = SessionState.from_dict(prior.to_dict())
    result = advance_session(prior, published, controller_config=context['controller'], strategy_identity=context['strategy'])
    replay = advance_session(restarted, published, controller_config=context['controller'], strategy_identity=context['strategy'])
    checks = {
        'prior_unchanged': prior.state_hash == restarted.state_hash == prior_hash,
        'input_unchanged': shadow._published_input_value(published) == checkpoint.input_value,
        'restart_equivalent': result.to_dict() == replay.to_dict(),
        'result_roundtrip_equivalent': result.to_dict() == SessionState.from_dict(result.to_dict()).to_dict(),
        'frontier_advanced': result.last_processed_session == published.session,
        'publication_version_bound': result.data_version == held.version,
        'strategy_bound': result.strategy_identity == context['strategy'],
        'decision_present': bool(result.last_decision),
    }
    if not all(checks.values()) or result.state_hash != checkpoint.state_sha256 or result.to_dict() != retained.state.to_dict():
        raise Refused('RETAINED_PROOF_CANONICAL_RESULT_CHANGED')
    admission = runtime_admission.read(conn, {**context, 'runtime': process, 'strategy': process_strategy}, initial)
    feature = initial.warmup_input_identity.get('feature_warmup', initial.warmup_input_identity)
    binding = {'schema': SCHEMA, 'authority_effect': 'NONE', 'scope': SCOPE,
        'observation_id': observation_id, 'session': checkpoint.session,
        'origin_sha256': digest(initial.model_dump(by_alias=True)),
        'checkpoint_sha256': digest(checkpoint.model_dump(by_alias=True)),
        'record_sha256': checkpoint.record_sha256, 'state_sha256': checkpoint.state_sha256,
        'input_sha256': digest(checkpoint.input_value), 'prior_state_sha256': prior_hash,
        'book_runtime_sha256': digest(initial.runtime_identity),
        'process_sha256': digest(runtime_admission.process_binding(process)),
        'strategy_sha256': digest(context['strategy']),
        'runtime_receipt_sha256': digest(attested.model_dump(by_alias=True)),
        'admission_sha256': digest(admission.model_dump(by_alias=True)) if admission else None,
        'checks': checks}
    if process_strategy != context['strategy']:
        binding.update(schema=SPLIT_SCHEMA, book_strategy_sha256=binding['strategy_sha256'],
            strategy_sha256=digest(process_strategy))
    validate(binding)
    return {'retained': binding, 'warmup_input': feature, 'state': result,
        'input_sha256': binding['input_sha256'], 'prior_state_sha256': prior_hash,
        'result_state_sha256': result.state_hash, 'decision_sha256': digest(result.last_decision),
        'checks': checks}
