"""Share only an overlapping read; never cache completed operational evidence."""
from dataclasses import dataclass, field
from threading import Event, Lock
from time import monotonic


WAIT_SECONDS = 10


class BuildUnavailable(TimeoutError):
    pass


@dataclass
class Flight:
    configuration: object
    done: Event = field(default_factory=Event)
    result: object = None
    error: BaseException | None = None


class Builds:
    def __init__(self):
        self.lock = Lock()
        self.active = None

    def read(self, configuration, build, *, timeout=WAIT_SECONDS):
        with self.lock:
            flight = self.active
            owner = flight is None
            if owner:
                flight = self.active = Flight(configuration)
            elif flight.configuration != configuration:
                raise BuildUnavailable('dashboard configuration changed during refresh')
        if owner:
            try:
                flight.result = build()
            except BaseException as exc:
                flight.error = exc
            finally:
                with self.lock:
                    self.active = None
                    flight.done.set()
        else:
            started = monotonic()
            if not flight.done.wait(timeout) or monotonic()-started>timeout:
                raise BuildUnavailable('current status refresh has not completed within its wait budget')
        if flight.error is not None:
            raise flight.error
        return flight.result
