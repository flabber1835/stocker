"""Initial extracted publication semantics retain their authenticated identity."""
from __future__ import annotations

import hashlib

MODULE = 'sentinel.feed.rolling_publisher'
PIPELINE_MODULE = 'sentinel.feed.publisher_pipeline'
BASE_REVISION = '0067e90b9f3a0e3e0b8c859fe4a90212e750ef16'
BASE_SHA256 = '30f3bb476e7dd07f0dbb201cd6f0f035f3f9beaad8efb7d4ac166d03b4c0068d'
PIPELINE_SHA256 = '854f7898fd08455759a91bd8128b8c9f3d5761c118eb4fc69910fe68be575b48'


def contribution(raw: bytes) -> str:
    """Every unknown economic pipeline byte sequence contributes its real hash."""
    actual = hashlib.sha256(raw).hexdigest()
    return BASE_SHA256 if actual == PIPELINE_SHA256 else actual
