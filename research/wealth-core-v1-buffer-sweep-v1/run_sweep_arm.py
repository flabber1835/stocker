#!/usr/bin/env python3
from pathlib import Path

TEMPLATE = Path(__file__).with_name("run_sweep_arm.template")
text = TEMPLATE.read_text()
if text.count("\u201c") != 3 or "\u201d" in text:
    raise RuntimeError("unexpected template typography")
text = text.replace("\u201c", '"')
code = compile(text, str(TEMPLATE), "exec")
namespace = {"__name__": "__main__", "__file__": str(TEMPLATE)}
exec(code, namespace)
