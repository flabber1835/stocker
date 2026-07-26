"""The packet is an index, not the database — the model must be able to LOOK.

An audit found seven "missing evidence" gaps in the packet. Several were not
gaps: the data was recorded and never surfaced (the builder persists
portfolio_estimated_vol / avg_pairwise_correlation / risk_estimate_degraded and
_current_book selects three columns from that row). The model could not know
that, because sql_query advertised a hand-maintained PARTIAL column list whose
partiality read as completeness: "alpaca_orders (status, notional, filled_at)"
gives no hint that submitted_at or filled_qty exist.

Widening the packet instead would trade one failure for another — the last
review was 572k input tokens, and a decisive number diluted among a hundred
others is one the model does not act on.
"""
import pytest

from app.tools import sql_guard, tool_definitions

DISCOVERY = ("SELECT table_name, column_name, data_type FROM "
             "information_schema.columns WHERE table_schema='public' "
             "ORDER BY table_name, ordinal_position")


def _sql_tool() -> dict:
    return next(t for t in tool_definitions() if t["name"] == "sql_query")


# ── the capability actually works ────────────────────────────────────────────

class TestDiscoveryIsPermitted:
    def test_the_advertised_recipe_passes_the_guard(self):
        """Advertising a query the guard rejects would be worse than saying
        nothing — the model burns a turn and concludes discovery is blocked."""
        assert sql_guard(DISCOVERY) is None

    def test_a_scoped_discovery_passes_too(self):
        assert sql_guard(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_schema='public' AND table_name IN ('alpaca_orders')") is None

    def test_discovery_does_not_weaken_the_write_guard(self):
        """The point is READ access to metadata, not a loophole."""
        assert sql_guard("INSERT INTO rankings VALUES (1)") is not None
        assert sql_guard("SELECT 1; DROP TABLE rankings") is not None
        assert sql_guard("SELECT pg_read_file('/etc/passwd')") is not None


# ── the model is told it can, and how ────────────────────────────────────────

class TestToolDescription:
    def test_it_names_the_discovery_mechanism(self):
        d = _sql_tool()["description"]
        assert "information_schema.columns" in d
        assert "DISCOVERABLE" in d or "discoverable" in d

    def test_it_warns_against_inferring_absence_from_the_packet(self):
        """THE failure mode: 'the packet does not show it' read as 'it was never
        recorded', producing a structural finding about a column that exists."""
        d = _sql_tool()["description"].lower()
        assert "do not guess" in d
        assert "packet" in d

    def test_the_tables_the_audit_needed_are_reachable(self):
        """Each was absent from the old list, and each backs one of the audit's
        'missing evidence' items."""
        d = _sql_tool()["description"]
        for table in ("decision_outcomes", "shadow_runs", "regime_snapshots",
                      "execution_steps", "config_changes", "evaluator_hypotheses",
                      "earnings", "target_history", "ingest_runs",
                      "pipeline_runs", "scheduler_runs"):
            assert table in d, f"{table} is still invisible to the evaluator"

    def test_it_no_longer_advertises_a_partial_column_list(self):
        """A partial list reads as complete. The old text said 'alpaca_orders
        (status,notional,filled_at)', so submitted_at and filled_qty — the whole
        of execution-latency evidence — looked nonexistent."""
        d = _sql_tool()["description"]
        assert "(status,notional,filled_at)" not in d
        assert "alpaca_orders" in d          # still indexed, just not mis-described


class TestSystemPrompt:
    def test_the_prompt_states_the_packet_is_not_the_database(self):
        from app.report import SYSTEM_PROMPT
        p = SYSTEM_PROMPT
        assert "PACKET IS NOT THE DATABASE" in p

    def test_a_structural_finding_must_be_preceded_by_a_query(self):
        """'We do not measure X' when X is a column is a wasted week — and the
        loop's whole value is that its findings are worth acting on."""
        from app.report import SYSTEM_PROMPT
        p = SYSTEM_PROMPT.lower()
        assert "structural finding" in p
        assert "came back empty" in p


@pytest.mark.parametrize("table", ["portfolio_runs", "alpaca_orders"])
def test_the_specific_write_only_columns_are_named_as_examples(table):
    """Naming two concrete cases beats an abstract instruction: these are the
    exact columns the audit reported as missing evidence."""
    d = _sql_tool()["description"]
    assert "portfolio_estimated_vol" in d and "avg_pairwise_correlation" in d
    assert "submitted_at" in d and "filled_qty" in d
