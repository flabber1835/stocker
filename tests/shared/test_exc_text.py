"""exc_text — persisted error text must NEVER be empty (the blank
alpaca_sync_runs failures the error_digest surfaced: httpx timeout classes
stringify to '')."""
import pytest

from stock_strategy_shared.tracing import exc_text


def test_normal_exception_keeps_class_and_message():
    assert exc_text(ValueError("boom")) == "ValueError: boom"


def test_empty_str_exception_yields_class_name():
    class ReadTimeout(Exception):
        pass
    assert exc_text(ReadTimeout()) == "ReadTimeout"
    assert exc_text(ReadTimeout("")) == "ReadTimeout"
    assert exc_text(ReadTimeout("   ")) == "ReadTimeout"


def test_truncation():
    out = exc_text(RuntimeError("x" * 5000), limit=100)
    assert len(out) == 100 and out.startswith("RuntimeError: xxx")
