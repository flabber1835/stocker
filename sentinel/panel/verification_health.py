"""Disposable verifier health uses only its two original local heartbeats."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

VERIFIER_HEARTBEAT = Path('/tmp/sentinel-verification-heartbeat')
OPERATIONAL_HEARTBEAT = Path('/tmp/sentinel-operational-projection-heartbeat')


def health(*, verifier_path=None, operational_path=None, now=None):
    try:
        verifier_path = VERIFIER_HEARTBEAT if verifier_path is None else verifier_path
        operational_path = OPERATIONAL_HEARTBEAT if operational_path is None else operational_path
        stamp = datetime.fromisoformat(verifier_path.read_text(encoding='ascii'))
        operational = datetime.fromisoformat(operational_path.read_text(encoding='ascii'))
        now = datetime.now(timezone.utc) if now is None else now
        return 0 if all(timedelta(0) <= now-value <= timedelta(seconds=45)
                        for value in (stamp, operational)) else 1
    except (OSError, ValueError, TypeError):
        return 1
