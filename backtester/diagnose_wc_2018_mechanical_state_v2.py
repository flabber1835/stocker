#!/usr/bin/env python3
"""Compatibility runner for the zero-budget 2018 Wealth Core mechanical diagnostic.

The original diagnostic was written against pre-correction retained-replay source
seams. Strategy 9 now preserves two corrected semantics before this diagnostic
instruments the generated replay:

1. age-119 review basis is the split-adjusted execution-session OPEN (``opsig``),
   not the fill-session signal CLOSE (``clsig``);
2. the broad independent-security replay expresses issuer identity through
   ``issuer_key(..., ds)`` rather than the older direct ``issuer[...]`` lookup.

This wrapper adapts ONLY the diagnostic's exact source-matching templates to those
current seams. The replacement text is adapted in the same way, so the generated
replay retains the current Strategy 9 economics byte-for-byte at those seams.
No strategy decision, threshold, timing rule, or portfolio state is changed.
"""
from __future__ import annotations

from backtester import diagnose_wc_2018_mechanical_state as diag


_ORIGINAL_REPLACE_ONCE = diag.replace_once


def _current_seam_replace(text: str, old: str, new: str, label: str) -> str:
    if label == "fill diagnostic":
        legacy = "s.entry_sig=float(clsig[tid]) if finite(clsig[tid]) else np.nan"
        current = (
            "s.entry_sig=float(opsig[tid]) if finite(opsig[tid]) "
            "and opsig[tid]>0 else np.nan"
        )
        if legacy not in old or legacy not in new:
            raise RuntimeError("fill diagnostic compatibility template drifted")
        old = old.replace(legacy, current)
        new = new.replace(legacy, current)

    elif label == "admission pressure diagnostic":
        # The broad Strategy 9 lineage deliberately made every security its own
        # issuer by defining issuer_key() to SID:<security>. Keep that exact
        # current semantic while adapting the old diagnostic template.
        substitutions = (
            ("issuer[s.tid]", "issuer_key(s.tid,ds)"),
            ("issuer[s.pending_tid]", "issuer_key(s.pending_tid,ds)"),
            ("issuer[tid]", "issuer_key(tid,ds)"),
        )
        for legacy, current in substitutions:
            old = old.replace(legacy, current)
            new = new.replace(legacy, current)

    return _ORIGINAL_REPLACE_ONCE(text, old, new, label)


def main() -> int:
    diag.replace_once = _current_seam_replace
    return diag.main()


if __name__ == "__main__":
    raise SystemExit(main())
