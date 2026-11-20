"""One bounded, process-local snapshot for explicitly non-current navigation."""
import pickle
from dataclasses import dataclass, field
from threading import Lock

MAX_BYTES = 2 * 1024 * 1024
_lock = Lock()
_value = None


@dataclass
class _Entry:
    content: bytes
    rendered: bool = False
    lock: Lock = field(default_factory=Lock)


def remember(configuration, panel):
    global _value
    # Only this process serializes these detached inputs. No wire/cache/database
    # bytes are ever accepted here or deserialized by the fallback.
    body = pickle.dumps(panel, protocol=5)
    with _lock:
        _value = (configuration, _Entry(body)) if len(body) <= MAX_BYTES else None


def read(configuration):
    from sentinel.panel.render import render
    with _lock:
        if _value is None or _value[0] != configuration:
            return None
        entry = _value[1]
    with entry.lock:
        if not entry.rendered:
            html = render(pickle.loads(entry.content), refresh_pending=True).encode('utf-8')
            entry.content = html if len(html) <= MAX_BYTES else b''
            entry.rendered = True
        return entry.content or None


def clear():
    global _value
    with _lock:
        _value = None
