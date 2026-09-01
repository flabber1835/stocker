#!/usr/bin/env python3
"""Run the strict-PIT production replay against the exact current-main source.

This compatibility launcher exists only on the backtester branch. It reuses the
retained historical harness while binding every production-source identity seam
to the unmodified current-main checkout. No production source file is patched.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CURRENT_MAIN_SHA = "c851386fa4dddcf2e2533af3a1d313c38220b7f2"
EXPECTED_PRODUCTION_BLOBS = {
    "sentinel/core/kernel.py": "12617af8eb954d4ae18fef2ae16977048e2e40cd",
    "sentinel/core/production.py": "99e8f87aa456fc672c84b0b0ceb3d674ca7ccf4c",
    "shared/stock_strategy_shared/wealth_core/adapter.py": "466a8f8202692e65e08596a7a47d45bd15bb3fd3",
    "shared/stock_strategy_shared/wealth_core/state.py": "8dd316ed28ff9b82c216f852118f8ef83d8510ad",
}


def _main_root() -> Path:
    args = list(sys.argv[1:])
    for index, value in enumerate(args):
        if value == "--main-root":
            if index + 1 >= len(args):
                raise RuntimeError("--main-root requires a path")
            return Path(args[index + 1]).resolve()
        if value.startswith("--main-root="):
            return Path(value.split("=", 1)[1]).resolve()
    return (ROOT / "main-src").resolve()


def _git(root: Path, *args: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(root), *args],
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        raise RuntimeError(completed.stderr.strip() or "git command failed")
    return completed.stdout.strip()


def verify_unmodified_current_main(root: Path) -> None:
    if _git(root, "rev-parse", "HEAD") != CURRENT_MAIN_SHA:
        raise RuntimeError("production checkout is not the certified current-main revision")
    if _git(root, "status", "--porcelain"):
        raise RuntimeError("production checkout is modified; certification requires pristine main")
    for path, expected_blob in EXPECTED_PRODUCTION_BLOBS.items():
        observed = _git(root, "hash-object", path)
        if observed != expected_blob:
            raise RuntimeError(
                f"production source blob mismatch for {path}: {observed} != {expected_blob}"
            )


def _load_retained_harness():
    # Import only when an actual historical replay is requested. Source-identity
    # and causality checks must remain independent of SEC evidence construction.
    import backtester.run_production_strict_pit_20y as retained
    return retained


def bind_current_main_identity(retained) -> None:
    """Override retained-harness identity constants, never production code."""
    modules = {
        retained,
        retained.strict,
        retained.strict.corrected,
        retained.strict.prod,
        retained.strict.base,
        retained.strict.runner,
    }
    for module in modules:
        if hasattr(module, "EXPECTED_MAIN_SHA"):
            setattr(module, "EXPECTED_MAIN_SHA", CURRENT_MAIN_SHA)
    retained.EXPECTED_MAIN_SHA = CURRENT_MAIN_SHA
    retained.strict.runner.EXPECTED_MAIN_SHA = CURRENT_MAIN_SHA
    os.environ["BACKTESTER_MAIN_SHA"] = CURRENT_MAIN_SHA


def main() -> int:
    root = _main_root()
    verify_unmodified_current_main(root)
    if "--self-test-source-identity" in sys.argv[1:]:
        print(
            "[SELFTEST PASS] unmodified current-main production source "
            f"root={root} sha={CURRENT_MAIN_SHA}",
            flush=True,
        )
        return 0
    retained = _load_retained_harness()
    bind_current_main_identity(retained)
    print(
        "[SOURCE IDENTITY PASS] production=current-main "
        f"sha={CURRENT_MAIN_SHA} patched=false",
        flush=True,
    )
    return int(retained.main())


if __name__ == "__main__":
    raise SystemExit(main())
