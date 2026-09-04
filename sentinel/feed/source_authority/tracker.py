"""Complete-seed SEP mutation watermark tracking."""
from __future__ import annotations

import datetime as dt
from typing import Optional

from sentinel.feed import sharadar
from .dates import SepUpdateEnvelope


class LastUpdatedTrackingFetch:
    """Commit a maximum only after complete, valid source exhaustion."""

    def __init__(self, fetch, *, update_ceiling: dt.date | str | None = None):
        self._fetch = fetch
        # Production always supplies the validated seed-through date. The today
        # fallback preserves the older diagnostic-only constructor while still
        # refusing future clocks; it never establishes a production cursor.
        ceiling = dt.date.today() if update_ceiling is None else update_ceiling
        self._envelope = SepUpdateEnvelope.through(
            ceiling, context="complete SEP seed observation")
        self.max_sep_lastupdated: Optional[dt.date] = None

    @property
    def seed_coverage_evidence(self):
        return getattr(self._fetch, "seed_coverage_evidence", None)

    def __call__(self, table, params=None, **kwargs):
        rows = self._fetch(table, params, **kwargs)
        if table != sharadar.SEP:
            return rows

        def replay():
            local_max: Optional[dt.date] = None
            complete = False
            try:
                for raw in rows:
                    row = dict(raw)
                    observed = self._envelope.validate(
                        row.get("lastupdated"),
                        ticker=str(row.get("ticker") or "").strip().upper(),
                        session=str(row.get("date") or ""))
                    if observed is not None and (
                            local_max is None or observed > local_max):
                        local_max = observed
                    yield row
                complete = True
            finally:
                if complete and local_max is not None and (
                        self.max_sep_lastupdated is None
                        or local_max > self.max_sep_lastupdated):
                    self.max_sep_lastupdated = local_max
        return replay()
