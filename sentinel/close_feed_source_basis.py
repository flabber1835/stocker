"""Exact action-history traversal successor for the retained economic identity."""
from __future__ import annotations

import hashlib
from pathlib import Path

from sentinel import physical_read_source_basis as predecessor

MODULE = 'sentinel.feed.action_history'
PREDECESSOR_SHA256 = '3e5301af6bb46fee50c7e687364ce9fe418234acda548e638142af2ec9ce7f45'
COMPILER_SHA256 = '694052870c917c2a0d253834ecf683d84fa4a5094c415c7454fb3949dcdc77bf'
LAYOUT_SHA256 = '589e8a87edfb31ca29f47b58e73cdf22c2f517bb9ff674d4983bd28681dd6927'
SESSION_LAYOUT_SHA256 = '8ba563c4bc749174ce631c125aa59360b046545770b34438234995fdb311ce25'
SHARED_SESSION_LAYOUT_SHA256 = '5952fb94d212d55b9a8f52254c82f4589df34ed51254fbcdbf63f095f87d051a'
FEED = Path(__file__).with_name('feed')


def contribution(raw: bytes) -> str:
    actual = hashlib.sha256(raw).hexdigest()
    if actual != COMPILER_SHA256:
        return predecessor.contribution(MODULE, raw)
    if hashlib.sha256(FEED.joinpath('normalized_layout.py').read_bytes()).hexdigest() not in {
            LAYOUT_SHA256, SESSION_LAYOUT_SHA256, SHARED_SESSION_LAYOUT_SHA256}:
        return actual
    if (hashlib.sha256(FEED.joinpath('read_contract.py').read_bytes()).hexdigest()
            != predecessor.READ_CONTRACT_SHA256):
        return actual
    profile = predecessor._profile()
    if profile is None or profile['compilers'][MODULE]['after'] != PREDECESSOR_SHA256:
        return actual
    return profile['compilers'][MODULE]['before']
