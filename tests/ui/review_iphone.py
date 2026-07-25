#!/usr/bin/env python3
"""iPhone-X layout audit for the Review (weekly evaluator) tab.

The Review tab is where the owner reads the weekly strategy review on a phone:
a verdict chip, recommendation cards, structural-finding cards, the applied
auto-promotions, a markdown narrative, and a collapsible tool transcript. It is
the most TEXT-heavy screen in the dashboard, which makes it the most likely to
overflow a 375px viewport — long dotted config paths, hashes, SQL snippets and
JSON tool arguments are all unbreakable-looking strings.

Layout assertions live in phone_audit.py (shared with the Lab tab). This file
supplies only the Review-specific payloads and checks.

Run standalone:  python tests/ui/review_iphone.py [--headed] [--shots DIR]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from phone_audit import IPHONE_X, TabSpec, run   # noqa: E402


def _ago(minutes: int) -> str:
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes)).isoformat()


# A deliberately HOSTILE report: the long unbreakable strings that a narrow
# viewport actually chokes on — dotted config paths, hashes, a SQL query and a
# JSON tool argument echoed into the transcript.
FULL_REPORT = {
    "run_id": "3f0c2b71-0000-4000-8000-000000000001",
    "status": "success", "as_of_date": "2026-07-25", "iso_year": 2026,
    "iso_week": 30, "manual": False,
    "strategy_id": "momentum_rotation_v2", "config_hash": "cd66f0a19b3e7c42",
    "provider": "anthropic", "model": "claude-opus-4-8", "prompt_hash": "9a1f2c88",
    "input_tokens": 184213, "output_tokens": 9422, "latency_ms": 411_000,
    "started_at": _ago(120), "completed_at": _ago(112),
    "report_markdown": (
        "## Verdict\n\nThe book underperformed SPY by 1.8% over the trailing "
        "four weeks, driven almost entirely by the energy bloc.\n\n"
        "## What worked\n\n- `earnings_surprise` marginal IC +0.06 across 4 of "
        "the last 6 weeks\n- the falling-knife veto avoided two >25% drawdowns\n\n"
        "## What hurt\n\n- cap_blocked candidates outperformed `selected` by "
        "2.4% — construction is rejecting winners the rank found\n\n"
        "## Recommendations\n\nSee the cards above.\n\n"
        "## Structural findings\n\nNo news/sentiment input exists anywhere in "
        "the pipeline; a PEAD-adjacent catalyst factor would need an ingested "
        "news source.\n\n## Watch list\n\nASTS, CPRX, SU\n"),
    "data_gaps": ["shadow_vs_champion: no challenger configured",
                  "score_calibration: only 3 ranking runs old enough"],
    "recommendations": {
        "overall_assessment": "mixed",
        "items": [
            {"config_field": "portfolio_builder.max_positions",
             "config_field_valid": True, "is_edit": True,
             "current_value": "30", "suggested_value": "17",
             "direction": "decrease", "confidence": "medium",
             "observation": "cap_blocked candidates beat selected names for a "
                            "third consecutive week, which implicates "
                            "construction rather than the factor model",
             "expected_effect": "more expected compounded return per name at "
                                "the cost of higher idiosyncratic variance",
             "evidence": ["selection_audit.avg_fwd_return_by_outcome: "
                          "cap_blocked +0.061 vs selected +0.037",
                          "invisible_bench.deferred_watch +0.048 vs selected +0.037"]},
            {"config_field": "none", "config_field_valid": True, "is_edit": False,
             "suggested_value": "", "direction": "investigate", "confidence": "high",
             "observation": "make no further config changes for two weeks — "
                            "three of the last four candidates failed validation",
             "expected_effect": "avoids churn while the ledger accumulates",
             "evidence": ["experiment_lane: 3 of 4 candidates failed the "
                          "two-window promotion gate"]},
            {"config_field": "portfolio_builder.imaginary_knob",
             "config_field_valid": False, "is_edit": True,
             "current_value": "?", "suggested_value": "0.25",
             "direction": "increase", "confidence": "low",
             "observation": "hallucinated field — must render greyed and "
                            "flagged as not actionable",
             "expected_effect": "n/a", "evidence": []},
        ],
        "structural": [
            {"finding": "no news or sentiment input exists anywhere in the "
                        "pipeline; the vetter is price-only since drawdown_only "
                        "mode became the default",
             "category": "missing_data_source", "confidence": "medium",
             "suggested_approach": "ingest a headline/sentiment feed and test a "
                                   "catalyst factor orthogonal to 12-1 momentum",
             "evidence": ["system_architecture.brief KNOWN NON-FEATURES",
                          "regret_top_non_selected: 4 of 6 misses had a fresh "
                          "catalyst no computed factor could see"]},
        ],
        "parse_fallback": False,
    },
    "tool_transcript": [
        {"turn": 1, "tool": "sql_query", "elapsed_ms": 1840, "result_chars": 4211,
         "arguments": '{"query": "SELECT action, AVG(fwd_20d - spy_fwd_20d) AS excess, '
                      'COUNT(*) FROM decision_outcomes GROUP BY action ORDER BY excess DESC"}',
         "result": '{"rows": [{"action": "entry", "excess": 0.0121, "count": 84}, '
                   '{"action": "watch", "excess": 0.0388, "count": 41}]}'},
        {"turn": 2, "tool": "preview_ranking", "elapsed_ms": 6120, "result_chars": 2044,
         "arguments": '{"config_changes": {"portfolio_builder.max_positions": 17}}',
         "result": '{"membership_change_count": 0, "rank_correlation": 1.0}'},
        {"turn": 3, "tool": "queue_strategy_experiment", "elapsed_ms": 220,
         "result_chars": 312,
         "arguments": '{"hypothesis": "concentrating to 17 names raises expected '
                      'compounded return", "config": {"strategy_id": "momentum_rotation_v2"}}',
         "result": "queued full-config candidate 7c1a9f0e2b334d55 (1 field(s) differ "
                   "from active). Runs in the daily experiment lane."},
    ],
}

REPORTS_LIST = {"reports": [
    {"run_id": "3f0c2b71-0000-4000-8000-000000000001", "status": "success",
     "iso_year": 2026, "iso_week": 30, "as_of_date": "2026-07-25", "manual": False,
     "model": "claude-opus-4-8", "input_tokens": 184213, "output_tokens": 9422,
     "started_at": _ago(120), "completed_at": _ago(112), "error_message": None},
    {"run_id": "3f0c2b71-0000-4000-8000-000000000002", "status": "success",
     "iso_year": 2026, "iso_week": 29, "as_of_date": "2026-07-18", "manual": True,
     "model": "claude-opus-4-8", "input_tokens": 170002, "output_tokens": 8100,
     "started_at": _ago(10200), "completed_at": _ago(10190), "error_message": None},
]}

# The auto-promotion audit strip: only status='applied' rows changed the config.
CONFIG_CHANGES = {"changes": [
    {"applied_at": _ago(1400), "status": "applied", "applied_by": "auto_promotion",
     "config_field": "__full_config__", "config_hash_before": "aaaa1111",
     "config_hash_after": "bbbb2222",
     "old_value": {"config_hash": "aaaa1111"},
     "new_value": {"config_hash": "bbbb2222", "promotion_hash": "cafe9001",
                   "hypothesis": "earnings_surprise at 0.12 with momentum 0.42 "
                                 "captures PEAD the 12-1 window misses",
                   "diff_vs_active": {
                       "static_factor_weights.earnings_surprise": {"from": 0.0, "to": 0.12},
                       "static_factor_weights.momentum": {"from": 0.54, "to": 0.42}},
                   "evidence": {"gate": "tune edge +0.0400 >= +0.0100 AND validate "
                                        "edge +0.0200 holds (drawdown within 5%)"}}},
    {"applied_at": _ago(1500), "status": "failed", "applied_by": "auto_promotion",
     "config_field": "__full_config__", "old_value": {}, "new_value": {}},
]}

RUNNING_REPORT = {**FULL_REPORT, "status": "running", "report_markdown": "",
                  "recommendations": {}, "tool_transcript": []}
FAILED_REPORT = {**FULL_REPORT, "status": "failed",
                 "error_message": "llm-gateway 529: anthropic overloaded_error",
                 "report_markdown": "", "recommendations": {}, "tool_transcript": []}

# The degraded path: the model returned prose instead of the JSON contract, so
# the raw text is shown verbatim with no cards at all.
PARSE_FALLBACK_REPORT = {
    **FULL_REPORT,
    "recommendations": {"overall_assessment": "insufficient_data", "items": [],
                        "structural": [], "parse_fallback": True},
    "report_markdown": "The system looks broadly healthy this week. " * 12,
    "data_gaps": ["LLM output was not valid report JSON — raw text shown verbatim"],
}


def audit_recommendation_cards(page, c, label):
    """Review-specific: the cards must actually be there, the hallucinated
    field must be visibly flagged, and long unbreakable strings (hashes, dotted
    paths, SQL in the transcript) must not widen the page."""
    if label not in ("full", "clock-skew"):
        return
    cards = page.evaluate(
        """() => Array.from(document.querySelectorAll('#eval-recs > div'))
             .filter(d => d.textContent.trim()).length""")
    c.check(cards >= 3, f"[{label}] recommendation/finding cards rendered ({cards})")

    txt = page.inner_text("#eval-recs")
    c.check("not actionable" in txt,
            f"[{label}] the unknown config_field is flagged as not actionable")
    c.check("Auto-promoted" in txt,
            f"[{label}] the applied auto-promotion is shown")
    c.check(txt.count("Auto-promoted") == 1,
            f"[{label}] the FAILED apply is not rendered as applied")

    # The narrative is markdown-rendered; its headings must survive on a phone.
    nar = page.inner_text("#eval-narrative")
    c.check("Verdict" in nar and "Structural findings" in nar,
            f"[{label}] narrative markdown rendered with its sections")

    # The tool transcript hides behind <details>: opening it must not blow the
    # layout out — it carries raw SQL and JSON arguments.
    opened = page.evaluate(
        """() => { const d = document.querySelector('#eval-meta details');
             if (!d) return false; d.open = true; return true; }""")
    if opened:
        page.wait_for_timeout(150)
        doc_w, win_w = page.evaluate(
            "() => [Math.max(document.documentElement.scrollWidth,"
            " document.body.scrollWidth), window.innerWidth]")
        c.check(doc_w <= win_w + 1,
                f"[{label}] expanding the tool transcript (raw SQL/JSON) does not "
                f"widen the page (scrollWidth {doc_w} <= {win_w})")
        meta_right = page.evaluate(
            "() => Math.max(...Array.from(document.querySelectorAll('#eval-meta *'))"
            ".map(e => e.getBoundingClientRect().right).concat([0]))")
        c.check(meta_right <= IPHONE_X["width"] + 1,
                f"[{label}] transcript content stays inside the viewport "
                f"(right edge {round(meta_right)})")


SPEC = TabSpec(
    name="review", nav_id="nav-evaluator", screen_id="screen-evaluator",
    ready_selector="#eval-status", header_id="eval-sub",
    body_selector="#screen-evaluator",
    # NB: these are matched against RENDERED text (inner_text applies CSS
    # text-transform), so the section headings appear UPPERCASE. Beware also
    # that a substring can match a different element than you intend —
    # "Structural findings" passed here only because the narrative markdown
    # contains "## Structural findings", masking a wrong heading expectation.
    expects={
        "full": ["MIXED", "week 2026-W30", "portfolio_builder.max_positions",
                 "General advice", "STRUCTURAL FINDINGS", "CONFIG CHANGES APPLIED"],
        "running": ["Review in progress"],
        "failed": ["Review failed", "overloaded_error"],
        "none": ["No evaluator reports yet"],
        "parse-fallback": ["INSUFFICIENT DATA", "broadly healthy"],
        "clock-skew": ["MIXED", "CONFIG CHANGES APPLIED"],
    },
    extra=[audit_recommendation_cards],
    min_body_chars=60,
)

_SKEWED = {**FULL_REPORT, "started_at": _ago(-45), "completed_at": _ago(-45)}

VARIANTS = [
    ("full", {"/api/evaluator/latest": {"report": FULL_REPORT},
              "/api/evaluator/reports": REPORTS_LIST,
              "/api/config/changes": CONFIG_CHANGES}),
    ("running", {"/api/evaluator/latest": {"report": RUNNING_REPORT},
                 "/api/evaluator/reports": REPORTS_LIST,
                 "/api/config/changes": {"changes": []}}),
    ("failed", {"/api/evaluator/latest": {"report": FAILED_REPORT},
                "/api/evaluator/reports": REPORTS_LIST,
                "/api/config/changes": {"changes": []}}),
    ("none", {"/api/evaluator/latest": {"report": None},
              "/api/evaluator/reports": {"reports": []},
              "/api/config/changes": {"changes": []}}),
    ("parse-fallback", {"/api/evaluator/latest": {"report": PARSE_FALLBACK_REPORT},
                        "/api/evaluator/reports": REPORTS_LIST,
                        "/api/config/changes": {"changes": []}}),
    ("clock-skew", {"/api/evaluator/latest": {"report": _SKEWED},
                    "/api/evaluator/reports": REPORTS_LIST,
                    "/api/config/changes": CONFIG_CHANGES}),
]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--shots", type=Path, default=None)
    a = ap.parse_args()
    sys.exit(run(SPEC, VARIANTS, headed=a.headed, shots=a.shots))
