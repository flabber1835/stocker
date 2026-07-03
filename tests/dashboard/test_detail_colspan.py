"""Detail-card colspan must match the host table's real column count.

Root cause of the "text above the card gets truncated on expand" bug: the
screener table has 3 columns (# · TICKER · COMPANY) but _insertDetailRow
defaulted to colSpan=4 (stale from when rows had a CLUSTER cell). Under
table-layout:fixed a colspan LARGER than the column count manufactures a
phantom extra column while the card is open, shrinking COMPANY and visibly
ellipsizing every row's text. These are source-contract checks that keep the
three numbers (thead columns, spacer colspan, detail colspan) in sync.
"""
import os
import re

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
DASH_JS = os.path.join(ROOT, "services", "dashboard", "static", "dashboard.js")
DASH_PY = os.path.join(ROOT, "services", "dashboard", "app", "main.py")


def _read(p):
    with open(p) as f:
        return f.read()


def _screener_thead_cols(html: str) -> int:
    # the screener thead is the one containing id="rh-rank"
    seg = html[html.index('id="rh-rank"'):]
    seg = seg[:seg.index("</thead>")]
    return seg.count("<th") + 1  # rh-rank's own <th was cut off by the index slice


def test_screener_detail_colspan_matches_column_count():
    js = _read(DASH_JS)
    html = _read(DASH_PY)
    cols = _screener_thead_cols(html)
    m = re.search(r"_insertDetailRow\(rowEl, rec, colSpan = (\d+)\)", js)
    assert m, "default colSpan not found"
    assert int(m.group(1)) == cols, (
        f"detail-card default colSpan {m.group(1)} != screener column count {cols} — "
        "a larger colspan creates a phantom column and truncates row text while open"
    )


def test_screener_spacer_colspan_matches_column_count():
    js = _read(DASH_JS)
    html = _read(DASH_PY)
    cols = _screener_thead_cols(html)
    for m in re.finditer(r'rank-spacer"><td colspan="(\d+)"', js):
        assert int(m.group(1)) == cols


def test_target_detail_colspan_matches_target_columns():
    js = _read(DASH_JS)
    html = _read(DASH_PY)
    seg = html[html.index('id="tgh-rank"'):]
    seg = seg[:seg.index("</thead>")]
    target_cols = seg.count("<th") + 1
    calls = re.findall(r"_insertDetailRow\((?:mainRow|rowEl), row\.rec, (\d+)\)", js)
    assert calls, "target-tab detail calls not found"
    for c in calls:
        assert int(c) == target_cols
