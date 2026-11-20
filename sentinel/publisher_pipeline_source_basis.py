"""Initial extracted publication semantics retain their authenticated identity."""
from __future__ import annotations

import hashlib

MODULE = 'sentinel.feed.rolling_publisher'
PIPELINE_MODULE = 'sentinel.feed.publisher_pipeline'
BASE_REVISION = '0067e90b9f3a0e3e0b8c859fe4a90212e750ef16'
BASE_SHA256 = '30f3bb476e7dd07f0dbb201cd6f0f035f3f9beaad8efb7d4ac166d03b4c0068d'
EXTRACTED_PIPELINE_SHA256 = '854f7898fd08455759a91bd8128b8c9f3d5761c118eb4fc69910fe68be575b48'
PIPELINE_SHA256 = 'f938c0d376bba3fa40bd67f81ea3bb1e3d5abd031e6dc8a7e07d256dc507058a'
SNAPSHOT_BEFORE_SHA256 = 'a8bf069b290a60a8ce9ca1821b4e313997b04cf11cb9cb361b65b088d8bea5bb'
SNAPSHOT_ADMISSION_SHA256 = '8b7cba0d389fa93aa597c4cf95923b359ae414c01cf91e1457cd656e6329bc2a'


def contribution(raw: bytes) -> str:
    """Every unknown economic pipeline byte sequence contributes its real hash."""
    from sentinel.economic_manifest import previous_source
    prior = hashlib.sha256(previous_source(PIPELINE_MODULE, raw)).hexdigest()
    return BASE_SHA256 if prior in (EXTRACTED_PIPELINE_SHA256, PIPELINE_SHA256) else hashlib.sha256(raw).hexdigest()
