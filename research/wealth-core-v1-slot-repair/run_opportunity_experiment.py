#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve()
BASE_RUNNER = HERE.parents[1] / "wealth-core-v1-slot-mechanics-v1" / "run_experiment.py"

spec = importlib.util.spec_from_file_location("wealth_core_slot_base_runner", BASE_RUNNER)
if spec is None or spec.loader is None:
    raise RuntimeError(f"cannot load base runner: {BASE_RUNNER}")
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)

_original_install_reclaim = base.install_reclaim


def _fixed_install_reclaim(src: str, variant: str) -> str:
    out = _original_install_reclaim(src, variant)
    if variant in {"opportunity-micro-reclaim", "opportunity-partial-reclaim"}:
        needle = (
            "                ready=[s for s in book.slots if not s.held() and not s.reserved() and gday>=s.ready_day]\n"
            "                if not ready and not unresolved and book.cash>0 and not any(s.held() and s.pending_sell for s in book.slots):"
        )
        replacement = (
            "                ready=[s for s in book.slots if not s.held() and not s.reserved() and gday>=s.ready_day]\n"
            "                _slot_exp_candidate=None\n"
            "                if not ready and not unresolved and book.cash>0 and not any(s.held() and s.pending_sell for s in book.slots):"
        )
        out = base.replace_once(out, needle, replacement, "opportunity candidate initialization")
    return out


base.install_reclaim = _fixed_install_reclaim

if __name__ == "__main__":
    raise SystemExit(base.main())
