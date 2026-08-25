"""One broker-free shadow advance with machine-distinguishable exit semantics."""
from __future__ import annotations

import json
import sys

from sentinel import shadow_runtime
from sentinel.shadow_service import (
    ShadowServiceConfig,
    ShadowServiceRefused,
    ShadowServiceRetry,
    ShadowServiceWaiting,
    advance_once,
)

EXIT_REFUSED = 2
EXIT_WAITING = 10
EXIT_RETRY = 11


def main() -> int:
    try:
        config = ShadowServiceConfig.from_env()
        result = advance_once(config)
        print(json.dumps(result, sort_keys=True), flush=True)
        return 0
    except ShadowServiceWaiting as exc:
        print(f"WAITING: {exc}", file=sys.stderr, flush=True)
        return EXIT_WAITING
    except ShadowServiceRetry as exc:
        print(f"RETRY: {exc}", file=sys.stderr, flush=True)
        return EXIT_RETRY
    except (ShadowServiceRefused, shadow_runtime.ShadowRuntimeRefused) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr, flush=True)
        return EXIT_REFUSED


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
