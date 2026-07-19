"""Tooling-gap channel — the evaluator must be able (and invited) to tell the
owner when a tool, data access, or budget constrained a review, including tools
that exist but are disabled (it can't miss what it was never told about)."""
import app.agent as agent
import app.tools as tools
from app.report import REPORT_SCHEMA, SYSTEM_PROMPT


def test_schema_accepts_tooling_gap_category():
    cats = (REPORT_SCHEMA["properties"]["structural_findings"]["items"]
            ["properties"]["category"]["enum"])
    assert "tooling_gap" in cats


def test_system_prompt_invites_tooling_gap_findings():
    assert "tooling_gap" in SYSTEM_PROMPT
    # affirmative both ways: report a real constraint, never invent one
    assert "do not invent one" in SYSTEM_PROMPT


def test_disabled_web_search_is_named_in_system_prompt(monkeypatch):
    monkeypatch.setattr(tools, "TAVILY_API_KEY", "")
    system = agent.build_system_prompt()
    assert "web_search EXISTS but is UNAVAILABLE" in system
    assert "tooling_gap" in system


def test_available_web_search_gets_no_unavailable_note(monkeypatch):
    monkeypatch.setattr(tools, "TAVILY_API_KEY", "tvly-test")
    system = agent.build_system_prompt()
    assert "UNAVAILABLE" not in system
