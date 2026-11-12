"""Exact action-history traversal successor for the retained economic identity."""
from __future__ import annotations

import hashlib
from pathlib import Path

from sentinel import physical_read_source_basis as predecessor

MODULE = 'sentinel.feed.action_history'
PREDECESSOR_SHA256 = '3e5301af6bb46fee50c7e687364ce9fe418234acda548e638142af2ec9ce7f45'
COMPILER_SHA256 = '694052870c917c2a0d253834ecf683d84fa4a5094c415c7454fb3949dcdc77bf'
LAYOUT_SHA256 = '7005074c8e79295c6b175fa8b78f555e3e4a00af34865867891a789bba0cc076'
FEED = Path(__file__).with_name('feed')


def contribution(raw: bytes) -> str:
    actual = hashlib.sha256(raw).hexdigest()
    if actual != COMPILER_SHA256:
        return predecessor.contribution(MODULE, raw)
    if hashlib.sha256(FEED.joinpath('normalized_layout.py').read_bytes()).hexdigest() != LAYOUT_SHA256:
        return actual
    if (hashlib.sha256(FEED.joinpath('read_contract.py').read_bytes()).hexdigest()
            != predecessor.READ_CONTRACT_SHA256):
        return actual
    profile = predecessor._profile()
    if profile is None or profile['compilers'][MODULE]['after'] != PREDECESSOR_SHA256:
        return actual
    return profile['compilers'][MODULE]['before']
