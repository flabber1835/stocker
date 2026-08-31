#!/usr/bin/env python3
"""Annual-prefix retained-research entrypoint over the full immutable PIT package."""
from __future__ import annotations

import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PINNED_MAIN_ROOT = ROOT / "main-src"
if PINNED_MAIN_ROOT.is_dir() and str(PINNED_MAIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PINNED_MAIN_ROOT))

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
    text = text.replace(old, new, 1)

    diagnostic_session = os.environ.get(
        "CERTIFICATION_RANKING_DIAGNOSTIC_SESSION", ""
    ).strip()
    if diagnostic_session:
        needle = "ordscore=np.lexsort((tick[pool],sid[pool],-score[pool])); durable=pool[ordscore]"
        if text.count(needle) != 1:
            raise RuntimeError(
                "research ranking diagnostic seam: expected one durable-ranking expression"
            )
        injected = needle + "\n" + (
            "                if ds==" + repr(diagnostic_session) + ":\n"
            "                    _diag_payload={'session':ds,'eligible_universe':int(len(et)),"
            "'leadership_ids':[str(sid[int(x)]) for x in pool],"
            "'ranking':[{'security_id':str(sid[int(x)]),'ticker':str(tick[int(x)]),"
            "'momentum':float(mom[int(x)]),'recent':float(recent[int(x)]),"
            "'score':float(score[int(x)])} for x in durable]}\n"
            "                    print('[RANKING DIAGNOSTIC] role=research '+"
            "json.dumps(_diag_payload,sort_keys=True,separators=(',',':')),flush=True)"
        )
        text = text.replace(needle, injected, 1)
    return text


base.corrected.transformed_source = _full_package_prefix_source

if __name__ == "__main__":
    raise SystemExit(base.main())
