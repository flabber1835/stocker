"""Target-tab sector weights — the header must render the target book's sector
split (the api's /portfolio sector_weights, latest-non-null lookup). This is
the user-visible verification surface for the W29 'sector cap inert' fix: real
sector names, not one big Unknown."""
import re
from pathlib import Path

JS = (Path(__file__).resolve().parents[2]
      / "services" / "dashboard" / "static" / "dashboard.js").read_text()


def test_target_header_renders_sector_weights():
    m = re.search(r"function renderTargetTable\(\)\s*\{(.*?)\n\}", JS, re.S)
    assert m, "renderTargetTable missing"
    body = m.group(1)
    assert "pr.sector_weights" in body
    # top-N + overflow indicator, sector names escaped
    assert "slice(0, 6)" in body
    assert "' more'" in body.replace('"', "'")
    assert "_esc(String(k)" in body
    assert "target-sectors" in body        # styled/taggable span
