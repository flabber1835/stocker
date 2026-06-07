"""Guard: every factor in rank.FACTORS must be threaded through the factor_scores
persistence layer (table INSERT, ranker SELECT, and the in-memory row/df builders).

Regression for the issuance-factor gap: the factor math (factors.py) and the
ranker's FACTORS list both knew about `issuance`, but pipeline/main.py persisted
only the six classic factors — so issuance was computed, dropped on write, read
back NULL, and its config weight renormalized away (inert for every ticker). A
factor that the ranker can weight but the DB never stores is silently dead; this
test fails the moment a new FACTORS entry isn't wired into both SQL statements.
"""
import re
from pathlib import Path

from app.rank import FACTORS

MAIN = (Path(__file__).resolve().parents[2]
        / "services" / "pipeline" / "app" / "main.py").read_text()


def _factor_scores_insert() -> str:
    # The INSERT INTO factor_scores (...) VALUES (...) statement (column list).
    m = re.search(r"INSERT INTO factor_scores.*?VALUES", MAIN, re.S)
    assert m, "could not locate the factor_scores INSERT in main.py"
    return m.group(0)


def _factor_scores_select() -> str:
    # The ranker's read: "SELECT <cols> FROM factor_scores WHERE run_id = :run_id".
    # The column list and FROM are separate concatenated string literals, so grab
    # from the nearest preceding SELECT up to the factor_scores FROM clause.
    idx = MAIN.find("FROM factor_scores WHERE run_id")
    assert idx != -1, "could not locate the factor_scores SELECT in main.py"
    start = MAIN.rfind("SELECT", 0, idx)
    return MAIN[start:idx + len("FROM factor_scores")]


def test_every_factor_is_persisted_in_insert():
    insert = _factor_scores_insert()
    missing = [f for f in FACTORS if f not in insert]
    assert not missing, f"factors missing from factor_scores INSERT (will be dropped on write): {missing}"


def test_every_factor_is_read_back_in_select():
    select = _factor_scores_select()
    missing = [f for f in FACTORS if f not in select]
    assert not missing, f"factors missing from factor_scores SELECT (ranker never sees them): {missing}"


def test_issuance_specifically_threaded():
    # Pin the specific factor whose absence motivated this guard.
    assert "issuance" in FACTORS
    assert "issuance" in _factor_scores_insert()
    assert "issuance" in _factor_scores_select()
