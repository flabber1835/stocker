"""Compatibility views over reviewed data, with no embedded instrument facts."""
from collections.abc import Sequence


class _Records(Sequence):
    def __init__(self, field):
        self.field = field

    def __getitem__(self, index):
        from sentinel.feed.source_corrections import current
        return current()[self.field][index]

    def __len__(self):
        from sentinel.feed.source_corrections import current
        return len(current()[self.field])


DISPUTED_CASH_EVENTS = _Records('disputed_cash_events')
CASH_ADJUDICATION_AUTHORITIES = _Records('cash_authorities')
