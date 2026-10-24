"""Synthetic market time only; PostgreSQL leases and mutation clocks stay real.

The fixed date starts just before the next regular open after an actually
closed source session. Tests advance it explicitly to the scheduled submission
instant. This is deterministic composition evidence, never exchange latency,
real clock-skew certification or a claim about today's market availability.
"""
from datetime import datetime as RealDateTime, timedelta, timezone
import importlib


class _DateTimeType(type):
    def __instancecheck__(cls, value):
        return isinstance(value, RealDateTime)


class BusinessClock:
    def __init__(self, instant):
        self.instant = instant.astimezone(timezone.utc)
        owner = self
        class DateTime(RealDateTime, metaclass=_DateTimeType):
            @classmethod
            def now(cls, tz=None):
                value = owner.instant
                return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)
        self.datetime = DateTime

    def now(self):
        return self.instant

    def install(self, monkeypatch):
        # These are explicit Python wall-clock inputs used by the production
        # adapters/guards. No validator, calendar calculation or DB SQL clock
        # is replaced. isinstance checks retain the real datetime domain.
        modules = (
            'tools.opening_gateway_qualification',
            'sentinel.automation_runtime', 'sentinel.authority.validation',
            'sentinel.standing_observation_authority',
            'sentinel.paper.preparation', 'sentinel.paper.execution',
            'sentinel.paper.recovery', 'sentinel.paper.validation',
            'sentinel.execution.alpaca', 'sentinel.execution.fill_notifications',
            'sentinel.panel.sources', 'sentinel.panel.read_projection',
            'sentinel.panel.verification_service',
        )
        for name in modules:
            module = importlib.import_module(name)
            if hasattr(module,'datetime'):
                monkeypatch.setattr(module,'datetime',self.datetime)
        from sentinel.feed import calendar, operational_snapshot, alpaca_source
        from sentinel import rolling_initialization, shadow_runtime
        original_date_module = calendar._dt
        class CalendarClock:
            datetime = self.datetime
            def __getattr__(self,name):
                return getattr(original_date_module,name)
        monkeypatch.setattr(calendar,'_dt',CalendarClock())
        monkeypatch.setattr(operational_snapshot,'_now',self.now)
        monkeypatch.setattr(rolling_initialization,'_now',lambda conn:self.now())
        monkeypatch.setattr(alpaca_source,'_today',lambda:self.now().date())
        monkeypatch.setattr(shadow_runtime,'_utcnow',self.now)


def prospective_clock(monkeypatch):
    from sentinel.feed import calendar
    actually_closed = calendar.latest_closed_session(RealDateTime.now(timezone.utc))
    effective = calendar.next_session(actually_closed)
    opened,_ = calendar.session_window(effective)
    result = BusinessClock(opened-timedelta(minutes=5))
    result.install(monkeypatch)
    return result,actually_closed
