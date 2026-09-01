from pathlib import Path


STRICT = Path("backtester/run_production_strict_pit_certification.py")
FULLSTACK = Path("backtester/run_ldrc_nonpit_vs_pit_certified.py")
CHECKPOINT = Path("backtester/production_year_checkpoint_overlay.py")


def _function_block(text: str, name: str, next_marker: str) -> str:
    start = text.index(f"def {name}(")
    end = text.index(next_marker, start)
    return text[start:end]


def test_production_progress_has_one_runtime_owner_increment_per_session() -> None:
    strict = STRICT.read_text(encoding="utf-8")
    wrapper = _function_block(
        strict,
        "_step_with_certification_checkpoint",
        "runner.OverlayAccount.step = _step_with_certification_checkpoint",
    )
    assert "before_progress" in wrapper
    assert 'getattr(base, "_progress_sessions", -1)' in wrapper
    assert "progress_sessions != before_progress + 1" in wrapper
    assert "prod._increment_production_progress" not in wrapper

    fullstack = FULLSTACK.read_text(encoding="utf-8")
    inherited = _function_block(
        fullstack,
        "_emit_progress",
        "base.runner.OverlayAccount.step = _emit_progress",
    )
    assert inherited.count("_increment_production_progress(base)") == 1


def test_checkpoint_progress_count_remains_one_to_one_with_canonical_pointer() -> None:
    checkpoint = CHECKPOINT.read_text(encoding="utf-8")
    assert 'raw["progress"], frozenset({"progress_sessions"})' in checkpoint
    assert "if count != len(expected_dates):" in checkpoint
    assert 'raise RuntimeError("production checkpoint progress count differs from pointer")' in checkpoint
