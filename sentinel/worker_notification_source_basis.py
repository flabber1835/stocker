"""One exact diagnostic-only publisher successor; never arbitrary source reuse."""
from __future__ import annotations

import hashlib

MODULE = 'sentinel.feed.rolling_publisher'
BASE_REVISION = '596e8496bb0028498847f8e8a4afb26df3f786ba'
REVIEWED_REVISION = '49faad3aa8cbb815b26f5fad3fc85e57588943db'
BASE_SHA256 = '30f3bb476e7dd07f0dbb201cd6f0f035f3f9beaad8efb7d4ac166d03b4c0068d'
REVIEWED_SHA256 = 'b31e0429c4e9c235c9ae18b39f98ce93b03f6817a973107c8aa83d9889c9d443'
BASE_AST_SHA256 = '792f5dab3a95a3df3d1cd9ff49e67a7dc5835be2cffe87e8def0549ab9ea0185'
STAGE_SEQUENCE = (
    'SHADOW_ADVANCE', 'ACQUISITION_LOCK', 'SOURCE_PREFLIGHT', 'SOURCE_PREFLIGHT',
    'SOURCE_REFERENCES', 'PRICE_ACQUISITION', 'CANDIDATE_BUILD',
    'CANDIDATE_VALIDATION', 'SOURCE_CORROBORATION', 'PUBLICATION',
)
DIAGNOSTIC_IMPORT = 'from sentinel import shadow_dependency_notifications as notices'
DIAGNOSTIC_CALL = 'notices.capture_stage(exc, operation_stage)'


def contribution(raw: bytes) -> str:
    """Closed source pair; every other byte sequence contributes its real hash."""
    actual = hashlib.sha256(raw).hexdigest()
    if actual in {BASE_SHA256, REVIEWED_SHA256}:
        return BASE_SHA256
    return actual
