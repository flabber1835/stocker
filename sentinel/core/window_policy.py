"""Explicit selected production semantics, independent of broker state."""
from sentinel import archive_identifiers
POLICY = 'CURRENT_WINDOW_V1'
NORMALIZATION = archive_identifiers.NORMALIZATION
FORMATION = 'CURRENT_WINDOW_FORMATION_V1'


def enabled(identity):
    return identity.get('market_input_policy') == POLICY


def formed(identity):
    return enabled(identity) and identity.get('startup_policy') == FORMATION
