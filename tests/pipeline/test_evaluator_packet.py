"""Phase-1 evaluator packet: the pure cross-sectional IC helper."""
import pandas as pd

from app.evaluator_packet import _spearman_ic


def test_ic_perfect_positive():
    s = pd.Series({f"T{i}": i for i in range(15)})
    f = pd.Series({f"T{i}": i * 0.01 for i in range(15)})
    ic, n = _spearman_ic(s, f)
    assert n == 15 and ic == 1.0


def test_ic_perfect_negative():
    s = pd.Series({f"T{i}": i for i in range(15)})
    f = pd.Series({f"T{i}": -i for i in range(15)})
    ic, n = _spearman_ic(s, f)
    assert ic == -1.0


def test_ic_too_few_obs_returns_none():
    s = pd.Series({f"T{i}": i for i in range(5)})
    f = pd.Series({f"T{i}": i for i in range(5)})
    ic, n = _spearman_ic(s, f)
    assert ic is None and n == 5


def test_ic_drops_nan_pairs():
    s = pd.Series({f"T{i}": i for i in range(15)})
    f = pd.Series({f"T{i}": (None if i % 2 else i) for i in range(15)})  # half NaN
    ic, n = _spearman_ic(s, f)
    assert n < 15 and (ic is None or ic == 1.0)  # surviving pairs still monotone
