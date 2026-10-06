"""One bounded non-current HTML presentation; never machine health evidence."""
from threading import Lock

MAX_BYTES = 2 * 1024 * 1024
_lock = Lock()
_value = None


def remember(configuration, html):
    global _value
    body = html.encode('utf-8')
    with _lock:
        _value = (configuration, body) if len(body) <= MAX_BYTES else None


def read(configuration):
    with _lock:
        return _value[1] if _value is not None and _value[0] == configuration else None


def clear():
    global _value
    with _lock:
        _value = None
