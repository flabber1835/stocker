"""Authenticated identity of a locally formed origin; never execution authority."""
from __future__ import annotations

import hmac
from typing import Literal

from pydantic import Field

from sentinel.feed import calendar, publication
from sentinel.feed.rolling_contract import Contract, Digest, digest

SCHEMA = 'sentinel.formed-origin/1'
POLICY = 'CURRENT_INFORMATION_INITIALIZATION_V1'


class Origin(Contract):
    schema_id: Literal['sentinel.formed-origin/1'] = Field(default=SCHEMA, alias='schema')
    median5_profile: Literal['wealth-core-median5-v1'] = 'wealth-core-median5-v1'
    first_session: str
    observation_id: str
    starting_cash: str
    strategy_sha256: Digest
    runtime_sha256: Digest
    publication_sha256: Digest
    snapshot_id: Digest
    plan: dict
    formation_count: Literal[126] = 126
    formation_chain: Digest
    initial_state_sha256: Digest
    feature_warmup: dict


def _signature(payload):
    return publication._receipt_hmac({'purpose': SCHEMA, 'origin': payload})


def build(formed, *, context, pub, binding):
    if not formed.complete or formed.plan.metadata_policy != POLICY:
        raise ValueError('FORMED_ORIGIN_INCOMPLETE_OR_WRONG_POLICY')
    payload = Origin(first_session=pub.window_end, observation_id=context['observation_id'],
        starting_cash=context['starting_cash'], strategy_sha256=digest(context['strategy']),
        runtime_sha256=digest(context['runtime']), publication_sha256=digest(pub.to_dict()),
        snapshot_id=binding['snapshot_id'], plan=formed.plan.model_dump(by_alias=True),
        formation_chain=formed.chain, initial_state_sha256=formed.state.state_hash,
        feature_warmup=formed.warmup_identity).model_dump(by_alias=True)
    signed = {**payload, 'hmac_sha256': _signature(payload)}
    return {**signed, 'warmup_input_sha256': digest(signed)}


def validate(value, *, first_session):
    from sentinel.core.formation import FormationPlan
    from sentinel.controller.owned_impairment import enabled
    from sentinel.shadow_observation import _validate_warmup_input_identity
    if not isinstance(value, dict) or 'hmac_sha256' not in value or 'warmup_input_sha256' not in value:
        raise ValueError('FORMED_ORIGIN_SHAPE_CHANGED')
    payload = {k: v for k, v in value.items() if k not in {'hmac_sha256', 'warmup_input_sha256'}}
    origin = Origin.model_validate(payload)
    if (payload != origin.model_dump(by_alias=True)
            or not hmac.compare_digest(str(value['hmac_sha256']), _signature(payload))
            or value['warmup_input_sha256'] != digest({k: v for k, v in value.items() if k != 'warmup_input_sha256'})):
        raise ValueError('FORMED_ORIGIN_AUTHENTICATION_FAILED')
    plan = FormationPlan.model_validate(origin.plan)
    if (not enabled(plan.strategy) or plan.metadata_policy != POLICY or origin.first_session != first_session
            or calendar.next_session(plan.end) != first_session
            or plan.capital != origin.starting_cash or digest(plan.strategy) != origin.strategy_sha256):
        raise ValueError('FORMED_ORIGIN_PLAN_CHANGED')
    _validate_warmup_input_identity(origin.feature_warmup, first_session=plan.axis[252])
    if origin.feature_warmup['metadata_mode'] != 'PROSPECTIVE_STATIC_FEATURE_METADATA':
        raise ValueError('FORMED_ORIGIN_METADATA_POLICY_CHANGED')
    return dict(value)


def require_seed(identity, *, state, observation_id, starting_cash, strategy, runtime):
    validate(identity, first_session=calendar.next_session(state.last_processed_session))
    if (identity['initial_state_sha256'] != state.state_hash
            or identity['observation_id'] != observation_id
            or identity['starting_cash'] != starting_cash
            or identity['strategy_sha256'] != digest(strategy)
            or identity['runtime_sha256'] != digest(runtime)
            or state.last_processed_session != identity['plan']['end']):
        raise ValueError('FORMED_ORIGIN_STATE_OR_CONTEXT_CHANGED')
