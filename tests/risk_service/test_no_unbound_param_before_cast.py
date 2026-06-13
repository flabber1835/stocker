import pathlib
import re

# Regression guard for the risk-service daily-loss outage (root-caused 2026-06-13).
#
# SQLAlchemy `text()` does NOT bind a `:param` that is immediately followed by `::`
# — it treats the colon as part of a PostgreSQL `::cast`. So `:trading_day::date`
# shipped the literal `:trading_day` to the driver → asyncpg PostgresSyntaxError
# ("syntax error at or near \":\"") on every /check, which the fail-closed handler
# turned into `control_unavailable` (blocking ALL trades). The query has been
# rewritten to a text comparison (`to_char(...) = :trading_day`). This test fails
# if the `:param::cast` pattern is ever reintroduced anywhere in a service.
_ROOT = pathlib.Path(__file__).resolve().parents[2]
_PAT = re.compile(r":[A-Za-z_]\w*::")


def test_no_named_bindparam_immediately_before_cast():
    offenders = []
    for path in (_ROOT / "services").rglob("app/*.py"):
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if _PAT.search(line):
                offenders.append(f"{path.relative_to(_ROOT)}:{lineno}: {line.strip()}")
    assert not offenders, (
        "Named bind-param immediately before a '::' cast won't bind in SQLAlchemy "
        "text() (ships ':name' literally → asyncpg syntax error). Use "
        "CAST(:name AS type) with a typed value, or a text comparison:\n"
        + "\n".join(offenders)
    )
