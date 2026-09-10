#!/usr/bin/env python3
"""Production entry wrapper that installs the canonical race-safe .env writer."""
from __future__ import annotations

from pathlib import Path
import sys
from typing import Mapping, Optional, Sequence

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

import sentinel_autonomous_deploy as core
import sentinel_autonomous_deploy_bootstrap as bootstrap
from sentinel_env_writer import EnvWriteRefused, safe_update_dotenv


def _deploy_writer(path: Path, updates: Mapping[str, str]) -> None:
    try:
        safe_update_dotenv(path, updates)
    except EnvWriteRefused as exc:
        raise core.DeployRefused(str(exc)) from None


def install_safe_writers() -> None:
    core.update_dotenv = _deploy_writer
    bootstrap._safe_update_dotenv = _deploy_writer


def main(argv: Optional[Sequence[str]] = None) -> int:
    install_safe_writers()
    return bootstrap.main(argv)


if __name__ == "__main__":
    raise SystemExit(main())
