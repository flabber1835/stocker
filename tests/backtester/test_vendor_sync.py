"""Guard: the backtester's vendored math (app/_vendor) must stay BYTE-IDENTICAL to
its source-of-truth in the pipeline / portfolio-builder. Config-replay (G1) re-ranks
and re-selects with these copies; if a copy drifts, the evaluator tool silently
scores configs with different math than production runs. This fails CI on any drift.
"""
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]

_PAIRS = [
    ("services/pipeline/app/rank.py",              "services/backtester/app/_vendor/rank.py"),
    ("services/pipeline/app/regime.py",            "services/backtester/app/_vendor/regime.py"),
    ("services/portfolio-builder/app/select.py",   "services/backtester/app/_vendor/select.py"),
]


def test_vendored_math_is_byte_identical_to_source():
    mismatches = []
    for src, vend in _PAIRS:
        s = (_ROOT / src).read_bytes()
        v = (_ROOT / vend).read_bytes()
        if s != v:
            mismatches.append(f"{vend} has drifted from {src} — re-copy verbatim")
    assert not mismatches, "\n".join(mismatches)
