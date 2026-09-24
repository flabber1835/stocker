"""Versioned startup evidence required before reviewing paper authority."""
import re
from collections.abc import Mapping

from sentinel.authority import AuthorityRefused, canonical_sha256
from sentinel.controller import owned_impairment
from sentinel.core.decision import runtime_strategy_identity
from sentinel.feed import calendar
from sentinel.formed_origin import POLICY

FORMED_SCHEMA = 'sentinel.paper-observation-warmup/3'
COLD_SCHEMA = 'sentinel.paper-observation-warmup/2'


def require(warmup, *, strategy_sha256, controller_sha256):
    config = owned_impairment.load()
    owned = (controller_sha256 == config.digest
             or strategy_sha256 == canonical_sha256(runtime_strategy_identity(config)))
    if not isinstance(warmup, Mapping) or warmup.get('warmup_sessions') != 252:
        raise AuthorityRefused('observation proof requires 252 feature sessions')
    if owned:
        formed = warmup.get('formation')
        if (warmup.get('schema') != FORMED_SCHEMA or warmup.get('measured_sessions') != 379
                or not isinstance(formed, Mapping)
                or formed.get('schema') != 'sentinel.formation-parity/1'
                or formed.get('policy') != POLICY or formed.get('sessions') != 126
                or any(not re.fullmatch('[0-9a-f]{64}', str(formed.get(key, '')))
                       for key in ('chain_sha256', 'state_sha256', 'source_sha256'))):
            raise AuthorityRefused('Owned55 observation requires the current formed startup proof')
        try:
            days = calendar.previous_sessions(warmup.get('decision_session'), 379)
        except (TypeError, ValueError) as exc:
            raise AuthorityRefused('Owned55 observation decision session is invalid') from exc
        if (len(days) != 379 or days[-1] != warmup.get('decision_session')
                or formed.get('end') != days[-2]
                or warmup.get('first_session') != days[0]):
            raise AuthorityRefused('Owned55 observation formation axis differs')
    elif warmup.get('schema') != COLD_SCHEMA or warmup.get('measured_sessions') != 253:
        raise AuthorityRefused('paper-observation candidate lacks the current 252+1 warmup')
