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
WINDOW_SCHEMA = 'sentinel.paper-observation-warmup/4'
WINDOW_FORMED_SCHEMA = 'sentinel.paper-observation-warmup/5'


def require(warmup, *, strategy_sha256, controller_sha256):
    from sentinel.strategy import production_strategy
    from sentinel.core import window_policy
    selected_controller, selected = production_strategy()
    selected_window = window_policy.enabled(selected) and strategy_sha256 == canonical_sha256(selected)
    formed_window = selected_window and window_policy.formed(selected)
    if selected_window and not formed_window:
        if (not isinstance(warmup, Mapping) or warmup.get('schema') != WINDOW_SCHEMA
                or warmup.get('warmup_sessions') != 299 or warmup.get('measured_sessions') != 300
                or controller_sha256 != selected_controller.digest or warmup.get('formation')):
            raise AuthorityRefused('current-window observation requires the 299+1 fresh startup proof')
        days = calendar.previous_sessions(warmup.get('decision_session'), 300)
        if len(days) != 300 or warmup.get('first_session') != days[0]:
            raise AuthorityRefused('current-window observation axis differs')
        return
    config = owned_impairment.load()
    owned = (formed_window or controller_sha256 == config.digest
             or strategy_sha256 == canonical_sha256(runtime_strategy_identity(config)))
    feature_count = 299 if formed_window else 252
    total_count = feature_count + 127
    if (not isinstance(warmup, Mapping) or warmup.get('warmup_sessions') != feature_count
            or (formed_window and controller_sha256 != selected_controller.digest)):
        raise AuthorityRefused('observation proof requires the selected feature sessions and controller')
    if owned:
        formed = warmup.get('formation')
        if (warmup.get('schema') != (WINDOW_FORMED_SCHEMA if formed_window else FORMED_SCHEMA)
                or warmup.get('measured_sessions') != total_count
                or not isinstance(formed, Mapping)
                or formed.get('schema') != 'sentinel.formation-parity/1'
                or formed.get('policy') != POLICY or formed.get('sessions') != 126
                or any(not re.fullmatch('[0-9a-f]{64}', str(formed.get(key, '')))
                       for key in ('chain_sha256', 'state_sha256', 'source_sha256'))):
            raise AuthorityRefused('Owned55 observation requires the current formed startup proof')
        try:
            days = calendar.previous_sessions(warmup.get('decision_session'), total_count)
        except (TypeError, ValueError) as exc:
            raise AuthorityRefused('Owned55 observation decision session is invalid') from exc
        if (len(days) != total_count or days[-1] != warmup.get('decision_session')
                or formed.get('end') != days[-2]
                or warmup.get('first_session') != days[0]):
            raise AuthorityRefused('Owned55 observation formation axis differs')
    elif warmup.get('schema') != COLD_SCHEMA or warmup.get('measured_sessions') != 253:
        raise AuthorityRefused('paper-observation candidate lacks the current 252+1 warmup')
