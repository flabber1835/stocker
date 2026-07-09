"""Guard: the evaluator's vendored rank.py must stay BYTE-IDENTICAL to the
pipeline's. preview_ranking re-ranks with this copy; drift would make the
preview lie about what the production ranker would do."""
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]


def test_vendored_rank_is_byte_identical_to_pipeline():
    src = (_ROOT / "services/pipeline/app/rank.py").read_bytes()
    vend = (_ROOT / "services/evaluator/app/_vendor/rank.py").read_bytes()
    assert src == vend, ("services/evaluator/app/_vendor/rank.py has drifted from "
                         "services/pipeline/app/rank.py — re-copy verbatim")
