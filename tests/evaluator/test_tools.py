"""Phase-2 evaluator tools — the safety guards each tool enforces regardless of
what the LLM asks for: SQL read-only pre-check, repo path traversal/credential
blocking, candidate-config validation, and the per-review backtest budget."""
import os

import pytest

from app.tools import (
    BacktestBudget,
    apply_config_changes,
    resolve_repo_path,
    sql_guard,
    tool_definitions,
)


# ── sql_guard ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("q", [
    "SELECT * FROM rankings LIMIT 5",
    "  select ticker, rank from rankings where rank <= 10",
    "WITH x AS (SELECT 1 AS a) SELECT * FROM x",
    "SELECT count(*) FROM daily_prices;",          # trailing semicolon tolerated
])
def test_sql_guard_accepts_selects(q):
    assert sql_guard(q) is None


@pytest.mark.parametrize("q,why", [
    ("DELETE FROM rankings", "not a select"),
    ("UPDATE alpaca_orders SET status='x'", "not a select"),
    ("DROP TABLE rankings", "not a select"),
    ("INSERT INTO rankings VALUES (1)", "not a select"),
    ("SELECT 1; DELETE FROM rankings", "multi-statement"),
    ("SELECT set_config('x','y',false)", "set keyword"),
    ("", "empty"),
    ("EXPLAIN ANALYZE SELECT 1", "not select/with prefix"),
])
def test_sql_guard_rejects_writes_and_multistatement(q, why):
    assert sql_guard(q) is not None, why


def test_sql_guard_word_boundaries_do_not_overreach():
    # Column/word substrings that CONTAIN forbidden keywords must not trip it.
    assert sql_guard("SELECT created_at, executed_qty, offset_col FROM alpaca_orders") is None


# ── resolve_repo_path ─────────────────────────────────────────────────────────

def test_repo_path_traversal_rejected(tmp_path):
    root = tmp_path / "repo"
    (root / "docs").mkdir(parents=True)
    (root / "docs" / "a.md").write_text("hi")
    ok, err = resolve_repo_path("docs/a.md", root=str(root))
    assert err is None and ok.endswith("a.md")
    for bad in ("../secrets", "docs/../../etc/passwd", "/etc/passwd"):
        p, e = resolve_repo_path(bad, root=str(root))
        # absolute /etc/passwd is joined under root then realpath'd; only accept
        # results INSIDE the root
        if e is None:
            assert p.startswith(str(root)), bad
        else:
            assert "escapes" in e


def test_repo_path_blocks_credential_shaped_files(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    for name in (".env", ".env.example", "server.key", "tls.pem", "my_secret.txt"):
        (root / name).write_text("x")
        _, err = resolve_repo_path(name, root=str(root))
        assert err is not None, name


def test_repo_path_symlink_escape_rejected(tmp_path):
    root = tmp_path / "repo"
    outside = tmp_path / "outside"
    root.mkdir(); outside.mkdir()
    (outside / "leak.txt").write_text("secret")
    os.symlink(outside / "leak.txt", root / "link.txt")
    _, err = resolve_repo_path("link.txt", root=str(root))
    assert err is not None and "escapes" in err   # realpath resolves past the link


# ── apply_config_changes ──────────────────────────────────────────────────────

def _valid_base() -> dict:
    import yaml
    here = os.path.join(os.path.dirname(__file__), "..", "..",
                        "strategies", "quality_core_v1.yaml")
    return yaml.safe_load(open(here))


def test_apply_changes_valid_diff_produces_config():
    base = _valid_base()
    out, err = apply_config_changes(base, {"portfolio_builder.max_positions": 25})
    assert err is None
    assert out["portfolio_builder"]["max_positions"] == 25


def test_apply_changes_invalid_value_returns_schema_error_and_runs_nothing():
    base = _valid_base()
    out, err = apply_config_changes(base, {"portfolio_builder.max_position_weight": 5.0})
    assert out is None and err is not None and "INVALID" in err


def test_apply_changes_unknown_field_rejected_by_schema():
    base = _valid_base()
    out, err = apply_config_changes(base, {"portfolio_builder.not_a_real_knob": 1})
    assert out is None and err is not None


def test_apply_changes_bad_weight_sum_rejected():
    base = _valid_base()
    out, err = apply_config_changes(base, {"static_factor_weights.momentum": 0.99})
    assert out is None and err is not None   # weights no longer sum to 1.0


def test_apply_changes_empty_diff_is_baseline_replay():
    base = _valid_base()
    out, err = apply_config_changes(base, {})
    assert err is None and out["strategy_id"] == base["strategy_id"]


# ── budget ────────────────────────────────────────────────────────────────────

def test_backtest_budget_caps():
    b = BacktestBudget(limit=2)
    assert b.take() and b.take()
    assert not b.take()
    assert b.used == 2


# ── tool definitions ──────────────────────────────────────────────────────────

def test_tool_definitions_shape_and_websearch_gating(monkeypatch):
    import app.tools as t
    monkeypatch.setattr(t, "TAVILY_API_KEY", "")
    names = {d["name"] for d in t.tool_definitions()}
    assert names == {"run_backtest", "sql_query", "read_file"}
    monkeypatch.setattr(t, "TAVILY_API_KEY", "tvly-x")
    names = {d["name"] for d in t.tool_definitions()}
    assert "web_search" in names
    for d in t.tool_definitions():   # gateway ToolDef contract
        assert d["name"] and d["description"] and d["parameters"]["type"] == "object"
