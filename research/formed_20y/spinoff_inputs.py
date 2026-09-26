"""Exact research-row repairs for in-kind distributions encoded as cash proxies."""
from decimal import Decimal

from sentinel.core.spinoffs import LIQUIDATE_CHILD_AT_OPEN
from sentinel.feed.rolling_contract import digest

# Complete original observation hashes, independently checked against ACTIONS.
# The original archive is immutable; only its research interpretation changes.
REVIEWED = {
    ('2014-08-28', '177752727931112051'): (
        '00fcea928d21d7d95076cd9dca7df901290e8f30cf3988362f3ae76877e12a52',
        'LVNTA', '905572516413780896', 'LTRPA', '1'),
    ('2015-07-01', '842836433184266027'): (
        '78d097ea759bdc06cf0d4a6f3dd09e63518a5de4cf3d3a1f29723c4dce19592b',
        'BAX', '128227091113957066', 'BXLT', '1'),
    ('2021-06-03', '899932545079148879'): (
        'dd7a4f47253270395c9cf98f826f8b9defd191fbcfbe59498198f1f6dce55b7a',
        'MRK', '373965186538085411', 'OGN', '0.1'),
}

REVIEWED_MULTI = {
    ('2016-07-25', '177752727931112051'): (
        'e07d5d2d14342f9b1e0b64ce09842d58957e68a0bdfd3f653c261dfb4c0bb09e',
        'LVNTA', (
            ('833187168852645886', 'CHUBA', '0.1'),
            ('1082580992675866020', 'CHUBK', '0.2'),
        )),
}


def normalize(rows, distributions):
    """Require exact source and child terms before removing a reviewed proxy."""
    supported = {}
    identities = set()
    for event in distributions:
        if event.policy != LIQUIDATE_CHILD_AT_OPEN:
            continue  # Preserve the canonical missing-child-terms refusal.
        key = (event.session, event.parent_security_id)
        identity = key + (event.child_security_id, event.source_row_id)
        if identity in identities:
            raise ValueError('duplicate supported spinoff input')
        identities.add(identity)
        supported.setdefault(key, []).append(event)
    result, audit, seen = [], [], set()
    for row in rows:
        key = (row['session'], row['security_id'])
        events = supported.get(key)
        if events is None:
            result.append(row)
            continue
        if key in seen:
            raise ValueError('duplicate spinoff observation')
        seen.add(key)
        expected = REVIEWED.get(key)
        multi = REVIEWED_MULTI.get(key)
        if expected is None and multi is None:
            if Decimal(row['dividend_per_share'] or '0') != 0:
                raise ValueError('unreviewed spinoff cash proxy')
            result.append(row)
            continue
        if multi is not None:
            source_hash, parent, children = multi
            actual = {(event.child_security_id, event.child_ticker,
                       str(Decimal(event.child_shares_per_parent)))
                      for event in events}
            wanted = {(child_id, child, str(Decimal(ratio)))
                      for child_id, child, ratio in children}
            if actual != wanted or any(event.parent_ticker != parent for event in events):
                raise ValueError('reviewed spinoff child terms changed')
        else:
            source_hash, parent, child_id, child, ratio = expected
            if len(events) != 1:
                raise ValueError('reviewed spinoff child terms changed')
            event = events[0]
            if (event.parent_ticker != parent or event.child_security_id != child_id
                    or event.child_ticker != child
                    or Decimal(event.child_shares_per_parent) != Decimal(ratio)):
                raise ValueError('reviewed spinoff child terms changed')
        if digest(row) != source_hash:
            raise ValueError('reviewed spinoff observation changed')
        if row['ticker'] != parent:
            raise ValueError('reviewed spinoff child terms changed')
        changed = {**row, 'dividend_per_share': '0'}
        result.append(changed)
        audit.append(dict(session=key[0], security_id=key[1], source_row_sha256=source_hash,
            normalized_row_sha256=digest(changed),
            source_event_id=','.join(sorted(event.source_row_id for event in events)),
            original_dividend_per_share=row['dividend_per_share'], dividend_per_share='0',
            reason='IN_KIND_CHILD_DISTRIBUTION_NOT_ADDITIONAL_CASH'))
    if any(key in (REVIEWED | REVIEWED_MULTI) and key not in seen for key in supported):
        raise ValueError('reviewed spinoff parent observation missing')
    return result, audit
