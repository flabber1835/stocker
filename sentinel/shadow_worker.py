"""One broker-free shadow advance with machine-distinguishable exit semantics."""
from __future__ import annotations

import json
import sys

from sentinel import backup_guard, shadow_runtime
from sentinel.feed import sharadar
from sentinel.shadow_recovery import (
    ShadowServiceConfig,
    ShadowServiceRefused,
    ShadowServiceRetry,
    ShadowServiceWaiting,
    advance_once,
)

EXIT_REFUSED = 2
EXIT_WAITING = 10
EXIT_RETRY = 11
EXIT_AVAILABILITY = 12


def _sharadar_availability(exc: BaseException) -> bool:
    """Return true only for provider states that may heal without code/config.

    ``SharadarRequestError`` is intentionally broad at the provider boundary:
    it also represents HTTP auth/configuration failures, while
    ``SharadarProtocolError`` represents malformed successful responses. Those
    must not be treated as an indefinitely harmless outage. The two genuinely
    availability-shaped cases are an explicit Retry-After deferral or exhausted
    retries after transport/retryable-HTTP failures; the latter has the stable
    provider-boundary rendering ``failed after N attempt(s)``.
    """
    if isinstance(exc, sharadar.SharadarProtocolError):
        return False
    if isinstance(exc, sharadar.SharadarRetryDeferred):
        return True
    if type(exc) is sharadar.SharadarRequestError:
        return "Sharadar request failed after " in str(exc)
    return False


def _availability_failure(exc: BaseException) -> bool:
    current: BaseException | None = exc
    seen = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, backup_guard.BackupUnavailable):
            return True
        if _sharadar_availability(current):
            return True
        current = current.__cause__ or current.__context__
    return False


def main() -> int:
    try:
        config = ShadowServiceConfig.from_env()
        result = advance_once(config)
        print(json.dumps(result, sort_keys=True), flush=True)
        return 0
    except ShadowServiceWaiting as exc:
        print(f"WAITING: {exc}", file=sys.stderr, flush=True)
        return EXIT_WAITING
    except backup_guard.BackupUnavailable as exc:
        print(f"AVAILABILITY: {exc}", file=sys.stderr, flush=True)
        return EXIT_AVAILABILITY
    except backup_guard.BackupWriteFenced as exc:
        print(f"REFUSED: {exc}", file=sys.stderr, flush=True)
        return EXIT_REFUSED
    except ShadowServiceRetry as exc:
        if _availability_failure(exc):
            print(f"AVAILABILITY: {exc}", file=sys.stderr, flush=True)
            return EXIT_AVAILABILITY
        print(f"RETRY: {exc}", file=sys.stderr, flush=True)
        return EXIT_RETRY
    except (ShadowServiceRefused, shadow_runtime.ShadowRuntimeRefused) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr, flush=True)
        return EXIT_REFUSED


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
