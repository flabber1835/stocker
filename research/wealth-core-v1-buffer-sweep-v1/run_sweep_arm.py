#!/usr/bin/env python3
from pathlib import Path

TEMPLATE = Path(__file__).with_name("run_sweep_arm.template")
text = TEMPLATE.read_text()
if text.count("\u201c") != 3 or "\u201d" in text:
    raise RuntimeError("unexpected template typography")
text = text.replace("\u201c", '"')

old = '''    src = one(
        src,
        "s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1; s.pending_intended_capital=0.",
        "_pending_meta.pop(id(s),None); s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1; s.pending_intended_capital=0.",
        "pending metadata cleanup",
    )
'''
new = '''    _pending_reset = "s.pending_tid=-1; s.pending_shares=0.; s.pending_signal_day=-1; s.pending_intended_capital=0."
    _pending_reset_count = src.count(_pending_reset)
    if _pending_reset_count != 3:
        raise RuntimeError(f"pending metadata cleanup seam mismatch: {_pending_reset_count}")
    src = src.replace(_pending_reset, "_pending_meta.pop(id(s),None); " + _pending_reset)
'''
if text.count(old) != 1:
    raise RuntimeError("pending-reset wrapper patch seam mismatch")
text = text.replace(old, new, 1)

code = compile(text, str(TEMPLATE), "exec")
namespace = {"__name__": "__main__", "__file__": str(TEMPLATE)}
exec(code, namespace)
