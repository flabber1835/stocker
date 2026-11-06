"""Synthetic market time only; PostgreSQL leases and mutation clocks stay real.

The synthetic date starts just before a strictly future regular opening. Its
source session is closed relative to that virtual market clock. Tests advance
it explicitly to the scheduled submission instant. This is deterministic
composition evidence, never real provider finality, exchange latency, real
clock-skew certification or a claim about today's market availability.
"""
from datetime import datetime as RealDateTime, timedelta, timezone
import importlib


class _DateTimeType(type):
    def __instancecheck__(cls, value):
        return isinstance(value, RealDateTime)


class BusinessClock:
    def __init__(self, instant):
        self.instant = instant.astimezone(timezone.utc)
        self.wall_offset = None
        owner = self
        class DateTime(RealDateTime, metaclass=_DateTimeType):
            @classmethod
            def now(cls, tz=None):
                value = owner.now()
                return value.astimezone(tz) if tz is not None else value.replace(tzinfo=None)
        self.datetime = DateTime

    def now(self):
        return (RealDateTime.now(timezone.utc)+self.wall_offset
                if self.wall_offset is not None else self.instant)

    def follow_wall(self):
        """Observation phase after terminal trading; never rewind business time."""
        self.wall_offset = max(timedelta(0), self.instant-RealDateTime.now(timezone.utc))

    def install(self, monkeypatch):
        # Only market/authority inputs advance. Financial observation, receipt
        # and dashboard clocks remain real, as do native SQL lease clocks and
        # monotonic deadlines. isinstance checks retain the datetime domain.
        modules = (
            'tools.opening_gateway_qualification',
            'sentinel.automation_runtime', 'sentinel.authority.validation',
            'sentinel.standing_observation_authority',
            'sentinel.paper.preparation', 'sentinel.paper.execution',
            'sentinel.paper.recovery', 'sentinel.paper.validation',
            'sentinel.execution.alpaca', 'sentinel.execution.fill_notifications',
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
    wall = RealDateTime.now(timezone.utc)
    decision = calendar.latest_closed_session(wall)
    effective = calendar.next_session(decision)
    opened,_ = calendar.session_window(effective)
    if opened <= wall:
        decision = effective
        effective = calendar.next_session(decision)
        opened,_ = calendar.session_window(effective)
    result = BusinessClock(opened-timedelta(minutes=5))
    result.install(monkeypatch)
    return result,decision
