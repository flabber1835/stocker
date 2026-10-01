"""Explicit selected production semantics, independent of broker state."""
POLICY = 'CURRENT_WINDOW_V1'
NORMALIZATION = 'sentinel.sharadar-current-window/1'
FORMATION = 'CURRENT_WINDOW_FORMATION_V1'


def enabled(identity):
    return identity.get('market_input_policy') == POLICY


def formed(identity):
    return enabled(identity) and identity.get('startup_policy') == FORMATION
