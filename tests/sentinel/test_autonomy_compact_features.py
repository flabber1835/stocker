from dataclasses import asdict, replace
import json
from unittest.mock import patch

from sentinel import rolling_initialization as init
from sentinel.core import rolling_continuity, window_features
from sentinel.core.kernel import advance_session
from sentinel.core.decision import shadow_target
from sentinel.feed import operational_snapshot as op
from sentinel.strategy import controller_for_identity
from tests.sentinel.test_current_window_production import ready, start
from tests.sentinel.test_operational_snapshot import operational_source
from tests.sentinel.test_rolling_snapshot_publisher import conn, pg, source
from tests.sentinel.test_rolling_daily import refresh

__all__ = ['conn', 'pg', 'source', 'ready', 'operational_source']


def test_full_kernel_transition_and_restoration_match_legacy_candidate_histories(
        conn, ready, operational_source, monkeypatch):
    first = start(conn)
    from sentinel import rolling_checkpoint
    previous = rolling_checkpoint.read(conn).snapshot
    conn.commit()
    refresh(conn, operational_source, monkeypatch)
    with op.pinned(conn) as (pub, binding):
        material, anchors, proof = rolling_continuity.prepare(conn, prior=first.state,
            previous_binding=previous, publication=pub, binding=binding)
        published = replace(init._published(material, pub), signal_basis_anchors=anchors, history_proof=proof)
        from sentinel.core.rolling_inputs import SnapshotReferences
        refs = SnapshotReferences(conn, candidate_id=binding['candidate_id'], snapshot_id=binding['snapshot_id'])
        with patch.object(window_features.Signal, 'from_feature',
                          side_effect=lambda bar: window_features.Signal.model_validate(asdict(bar))):
            legacy = window_features.load(conn, prior=first.state, refs=refs, publication=pub)
    compact = window_features.WindowFeatures.model_validate(published.window_features)
    assert all(len(signal.closes) == 1 for signal in compact.signals)
    assert any(len(signal.closes) == 127 for signal in legacy.signals)
    assert compact.histories == legacy.histories
    legacy_input = replace(published, window_features=legacy.model_dump(mode='json', by_alias=True),
                           history_proof={**proof, 'features_sha256':legacy.sha256})
    identity = first.state.strategy_identity
    controller = controller_for_identity(identity)
    actual = advance_session(first.state, published, controller_config=controller, strategy_identity=identity)
    expected = advance_session(first.state, legacy_input, controller_config=controller, strategy_identity=identity)
    assert actual.to_dict() == expected.to_dict()
    assert actual.state_hash == expected.state_hash
    assert shadow_target(actual) == shadow_target(expected)
    from sentinel.core.session import SessionState
    assert SessionState.from_dict(json.loads(json.dumps(actual.to_dict()))).state_hash == expected.state_hash


def test_representative_candidate_bytes_are_bounded_by_current_facts():
    from sentinel.core.window_features import Signal
    from stock_strategy_shared.wealth_core.engine import SecurityBar, score_universe
    from stock_strategy_shared.wealth_core.v5 import config
    full, compact = [], []
    for index in range(5000):
        bar = SecurityBar(f'S{index}', f'S{index}', f'SID:S{index}',
            tuple(100 + index*.1 + day*.01 for day in range(127)), 150., True, '', (.1, .01, .2, .45))
        full.append(Signal.model_validate(asdict(bar)))
        compact.append(Signal.from_feature(bar))
    before = len(json.dumps([signal.model_dump(mode='json') for signal in full], separators=(',', ':')))
    after = len(json.dumps([signal.model_dump(mode='json') for signal in compact], separators=(',', ':')))
    assert after < before*.2
    assert score_universe([signal.bar() for signal in full], config()) == score_universe(
        [signal.bar() for signal in compact], config())
    print(json.dumps({'candidates':len(full), 'legacy_json_bytes':before, 'compact_json_bytes':after}))
