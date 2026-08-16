"""`_ensure_schema` must not let one bad statement revert the others.

THE INCIDENT THIS ENCODES. `ALTER TABLE bt_universe ADD COLUMN ...` was written
about sixty lines ABOVE `CREATE TABLE bt_universe`, so on a fresh database it
failed. The whole file ran in one transaction, so that single failure rolled back
every other statement — including an unrelated `ALTER TABLE bt_prices ADD COLUMN
close_unadjusted` — and the caller collapsed the exception into one WARN. The
service then reported HEALTHY with the column missing, and the first visible
symptom was an HTTP 500 from a coverage endpoint three deploy steps later.

Two independent defects, so two independent guards: the ORDERING is checked
against the file, and the ISOLATION is checked against the code.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
INIT_SQL = ROOT / "services" / "bt-data" / "sql" / "init_bt.sql"
MAIN_PY = ROOT / "services" / "bt-data" / "app" / "main.py"

SQL = INIT_SQL.read_text()
STATEMENTS = [s.strip() for s in SQL.split(";\n") if s.strip()]


def _strip_comments(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines()
                     if not ln.strip().startswith("--"))


class TestEveryAlterFollowsItsCreate:
    """A fresh database applies this file top to bottom. An ALTER above its
    CREATE is a guaranteed failure there and invisible on an existing one — so
    it survives every manual test on a machine that already has the table."""

    def positions(self, table: str) -> tuple[int | None, list[int]]:
        create = re.compile(rf"CREATE TABLE IF NOT EXISTS {table}\b")
        alter = re.compile(rf"ALTER TABLE {table}\b")
        create_at, alters = None, []
        for i, stmt in enumerate(STATEMENTS):
            body = _strip_comments(stmt)
            if create_at is None and create.search(body):
                create_at = i
            if alter.search(body):
                alters.append(i)
        return create_at, alters

    @pytest.mark.parametrize("table", sorted({
        m.group(1) for m in re.finditer(r"ALTER TABLE (\w+)",
                                        _strip_comments(SQL))}))
    def test_alter_comes_after_create(self, table):
        create_at, alters = self.positions(table)
        assert create_at is not None, (
            f"ALTER TABLE {table} with no CREATE TABLE IF NOT EXISTS {table} in "
            f"the same file — a fresh database has nothing to alter")
        for a in alters:
            assert a > create_at, (
                f"ALTER TABLE {table} at statement {a} precedes its CREATE at "
                f"{create_at}. Fine on an existing database, guaranteed to fail "
                f"on a fresh one — and before the per-statement fix that failure "
                f"rolled back the whole file.")

    def test_the_wealth_core_columns_are_present_and_ordered(self):
        create_at, alters = self.positions("bt_universe")
        adding = [i for i in alters
                  if "category" in _strip_comments(STATEMENTS[i])]
        assert adding, "the bt_universe category/permaticker ALTER is gone"
        assert all(i > create_at for i in adding)
        statement = "\n".join(STATEMENTS[i] for i in adding)
        assert "decision_metadata_complete BOOLEAN NOT NULL" in statement
        assert "DEFAULT FALSE" in statement

    def test_close_unadjusted_is_added_idempotently(self):
        body = _strip_comments(SQL)
        assert "ADD COLUMN IF NOT EXISTS close_unadjusted" in body, (
            "the as-traded price column must be added with IF NOT EXISTS so an "
            "existing bt-postgres picks it up on startup")


class TestOneBadStatementCannotRevertTheOthers:

    def ensure_schema_fn(self):
        tree = ast.parse(MAIN_PY.read_text())
        return next(n for n in ast.walk(tree)
                    if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and n.name == "_ensure_schema")

    def test_the_transaction_is_opened_INSIDE_the_statement_loop(self):
        """The structural property, checked structurally.

        `async with engine.begin()` outside the loop is one transaction for the
        whole file; inside, each statement stands alone. The difference is
        invisible until a statement fails, and then it is the difference between
        one missing column and every missing column.
        """
        fn = self.ensure_schema_fn()
        loops = [n for n in ast.walk(fn) if isinstance(n, (ast.For, ast.AsyncFor))]
        assert loops, "_ensure_schema no longer loops over statements"
        withs_in_loops = [w for loop in loops for w in ast.walk(loop)
                          if isinstance(w, (ast.With, ast.AsyncWith))]
        assert withs_in_loops, (
            "no transaction is opened inside the loop — the file is running in "
            "a single transaction again, so one failing statement reverts every "
            "other one")

    def test_a_failure_does_not_abort_the_remaining_statements(self):
        """There must be a try/except INSIDE the loop, or the first failure ends
        the run and every later statement is skipped rather than reverted —
        different mechanism, same missing columns."""
        fn = self.ensure_schema_fn()
        loops = [n for n in ast.walk(fn) if isinstance(n, (ast.For, ast.AsyncFor))]
        handlers = [h for loop in loops for h in ast.walk(loop)
                    if isinstance(h, ast.Try)]
        assert handlers, "no per-statement error handling inside the loop"

    def test_failures_are_returned_rather_than_collapsed(self):
        """A single aggregate WARN made a bootstrap that had stopped applying
        half the file look identical to one that worked."""
        fn = self.ensure_schema_fn()
        returns = [n for n in ast.walk(fn) if isinstance(n, ast.Return)]
        assert returns, "_ensure_schema reports nothing back to its caller"

    def test_the_caller_logs_each_failure_individually(self):
        src = _strip_comments(MAIN_PY.read_text())
        block = src[src.index("failures = await _ensure_schema()"):]
        block = block[:800]
        assert "for f in failures" in block, (
            "the caller must print each failed statement; one aggregate line "
            "cannot say WHICH columns are missing")
