"""Review tab tool audit — the UI must show which evaluator tools ran, how
many times each, and expose per-call detail on demand (tool_transcript was
persisted + returned by the API but never rendered)."""
import re
from pathlib import Path

JS = (Path(__file__).resolve().parents[2]
      / "services" / "dashboard" / "static" / "dashboard.js").read_text()


def test_transcript_rendered_in_report_meta():
    m = re.search(r"function _renderEvalReport\(rep\)\s*\{(.*?)\n\}", JS, re.S)
    assert m, "_renderEvalReport missing"
    body = m.group(1)
    assert "rep.tool_transcript" in body
    # per-tool counts + total
    assert "counts[c.tool]" in body
    assert "tt.length + ' calls" in body.replace('"', "'")
    # per-call expandable detail (no handlers needed — <details>)
    assert "<details" in body and "show calls" in body
    assert "c.elapsed_ms" in body and "c.arguments" in body
    # budget exhaustion surfaced
    assert "turn budget reached" in body
    # tolerant of jsonb arriving as a string
    assert "JSON.parse(tt)" in body
    # everything user-controlled is escaped
    for var in ("c.tool", "c.turn", "c.elapsed_ms", "c.result_chars"):
        assert f"_esc({var})" in body, f"{var} must be escaped"
