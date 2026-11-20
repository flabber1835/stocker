"""Captured table rows and historical input domains."""
from datetime import date

SEP, SFP, ACTIONS, TICKERS = "SEP", "SFP", "ACTIONS", "TICKERS"


class RequestError(RuntimeError):
    pass


class CaptureRequired(RequestError):
    pass


class ProtocolError(RequestError):
    pass


class RetryDeferred(RequestError):
    def __init__(self, delay, status=None):
        self.delay, self.status = float(delay), status
        super().__init__(f"Source deferred for {self.delay:.0f} seconds")


class Unavailable(RetryDeferred):
    def __init__(self, detail, delay, status=None):
        super().__init__(delay, status)
        self.args = (detail,)


def require_capture():
    from sentinel.feed import operational_source
    capture = operational_source.current()
    if capture is None:
        raise CaptureRequired("An explicitly captured historical input is required")
    return capture


def fetch_table(table, params=None):
    if table not in {SEP, ACTIONS}:
        raise CaptureRequired("This table requires an independent historical observation")
    return require_capture().fetch_rows(table, params)


def date_params(date_from: str, date_to: str) -> dict:
    validate_date_range(date_from, date_to)
    return {"date.gte": date_from, "date.lte": date_to}


def validate_date_range(date_from: str, date_to: str) -> tuple[str, str]:
    """Validate an inclusive ISO range before any durable run or vendor read."""
    lo, hi = date.fromisoformat(str(date_from)), date.fromisoformat(str(date_to))
    if lo > hi:
        raise ValueError(f"reversed date range: {lo} is after {hi}")
    return lo.isoformat(), hi.isoformat()


def year_chunks(date_from: str, date_to: str) -> list[tuple[str, str]]:
    """Split a range into calendar years for bounded, restartable seed work."""
    date_from, date_to = validate_date_range(date_from, date_to)
    y0, y1 = int(date_from[:4]), int(date_to[:4])
    out = []
    for y in range(y0, y1 + 1):
        lo = max(f"{y}-01-01", date_from)
        hi = min(f"{y}-12-31", date_to)
        if lo <= hi:
            out.append((lo, hi))
    return out
