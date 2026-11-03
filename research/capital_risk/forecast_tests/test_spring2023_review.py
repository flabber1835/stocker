"""Source-bound continuation adapter tests, without running financial code."""
import ast
from pathlib import Path

import pytest

import system_campaign_spring2023_review as review


def test_original_source_function_remains_unchanged_and_only_two_sites_move():
    raw = Path(review.original.__file__).read_bytes()
    before = ast.parse(raw)
    function = review.compile_review(raw, review.sha(raw))
    assert function.__name__ == 'review'
    assert function.__globals__ is not review.original.review.__globals__
    assert Path(review.original.__file__).read_bytes() == raw
    assert 'SPRING2023' not in ast.unparse(before)
    # The AST substitutions are intentionally exact: an incompatible future
    # original reviewer must refuse rather than be silently generalized.
    changed = raw.replace(b"parent['source_cursor']<NATIVE", b"parent['source_cursor']<=NATIVE")
    assert changed != raw
    with pytest.raises(ValueError, match='EXACT_TWO_REVIEW_CONTINUATION_SITES'):
        review.compile_review(changed, review.sha(changed))


def test_changed_adopted_reviewer_bytes_refuse_before_compilation():
    raw = Path(review.original.__file__).read_bytes()
    with pytest.raises(ValueError, match='EXACT_ADOPTED_ORIGINAL_CERTIFICATE_REVIEWER'):
        review.compile_review(raw + b'\n', review.sha(raw))


def test_actual_reviewer_source_guard_removal_falsifier():
    raw = Path(review.original.__file__).read_bytes()
    tree = ast.parse(Path(review.__file__).read_bytes())
    fn, = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'compile_review']
    guard, = [n for n in fn.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
              and any(isinstance(a, ast.Constant) and a.value == 'SPRING2023_EXACT_ADOPTED_ORIGINAL_CERTIFICATE_REVIEWER'
                      for a in n.value.args)]
    fn.body.remove(guard)
    namespace = dict(vars(review))
    exec(compile(ast.fix_missing_locations(ast.Module(body=[fn], type_ignores=[])),
                 '<actual-adopted-reviewer-source-guard-removed>', 'exec'), namespace)
    with pytest.raises(ValueError):
        review.compile_review(raw + b'\n', review.sha(raw))
    assert callable(namespace['compile_review'](raw + b'\n', review.sha(raw)))
