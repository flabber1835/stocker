#!/usr/bin/env python3
"""Annual-prefix retained-research entrypoint over the full immutable PIT package."""
from __future__ import annotations

import os

os.environ.setdefault("CANONICAL_PIT_EXPECTED_END", "2026-07-31")

import backtester.run_research_strict_pit_20y_terminal_grace as terminal  # noqa: E402

base = terminal.base
_original = base.corrected.transformed_source


def _full_package_prefix_source(mode, output):
    text = _original(mode, output)
    old = "expected_end=os.environ.get('CERTIFICATION_END_SESSION'))"
    new = (
        "expected_end=os.environ.get('CANONICAL_PIT_EXPECTED_END', "
        "os.environ.get('CERTIFICATION_END_SESSION')))"
    )
    count = text.count(old)
    if count != 1:
        raise RuntimeError(
            f"canonical research package-end seam: expected one match, found {count}"
        )
    return text.replace(old, new, 1)


base.corrected.transformed_source = _full_package_prefix_source

if __name__ == "__main__":
    raise SystemExit(base.main())
