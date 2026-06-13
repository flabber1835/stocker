"""
Playwright UI test for the redesigned TARGET tab.

The target tab is a table of the held∪target union, each row enriched with the
screener's rank + trend arrow + click-through detail:

    #  ·  TICKER  ·  HELD  ·  TARGET  ·  TRADE

'watch' (a capacity-deferred target entry) IS shown — Target ✓ / Holdings ✗ /
trade 'Watch'. This test serves the real target-table markup + the REAL
dashboard.js, mocks the /api/delta/latest and /api/rankings/with-overlays shapes,
runs the real loadTargetPortfolio(), and asserts:
  - held-or-target tickers appear, including 'watch' as a deferred target
  - HELD / TARGET ✓ marks match the delta action taxonomy
  - TRADE labels are correct
  - rank trend arrows render (up / down)
  - a held orphan ranked beyond the screener top-N still appears (fallback row)
  - column sort (blue triangle) reorders rows
  - clicking a row expands the detail card

Run:  python tests/dashboard/test_target_tab_playwright.py
(standalone; prints PASS/FAIL and exits non-zero on any failure.)
"""
from __future__ import annotations

import glob
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", "/opt/pw-browsers")
from playwright.sync_api import sync_playwright  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DASHBOARD_JS = ROOT / "services" / "dashboard" / "static" / "dashboard.js"


def _chrome_path() -> str | None:
    hits = glob.glob("/opt/pw-browsers/chromium-*/chrome-linux/chrome")
    return hits[0] if hits else None


def _intent(ticker, action, rank, **extra):
    base = {
        "id": "i-" + ticker, "intent_id": "i-" + ticker, "ticker": ticker,
        "action": action, "rank": rank, "composite_score": 0.75,
        "confirmation_days_met": 1, "current_weight": 0.03, "actual_weight": 0.03,
        "weight_drift": None, "reason": action, "order_status": None,
        "order_error_message": None, "order_deferred_until": None, "rejected_at": None,
        "vetter_excluded": False, "vetter_confidence": "low", "vetter_risk_type": "none",
        "vetter_reason": "", "vetter_crashed": False,
        "vetter_positive_catalyst": False, "vetter_positive_reason": "",
    }
    base.update(extra)
    return base


def _delta_payload():
    intents = [
        _intent("AAA", "hold", 1, in_target=True),   # held + target  → Hold (TARGET✓)
        _intent("BBB", "entry", 2, in_target=True),  # target only    → Buy
        _intent("CCC", "exit", 3, in_target=False),  # held only      → Sell
        _intent("DDD", "buy_add", 4, in_target=True),    # held + target  → Add
        _intent("EEE", "sell_trim", 5, in_target=True),  # held + target  → Trim
        _intent("FFF", "at_risk", 6, in_target=False),   # held only      → At risk
        _intent("GGG", "watch", 7, in_target=True),  # target only (capacity-deferred) → Watch
        _intent("HHH", "exit", 142, in_target=False),    # held, ranked beyond top-N → fallback
        # Data-gap HOLD: held, action='hold', but NOT a builder-target member
        # (weight 0, never selected). Must show HELD✓ but TARGET✗ — it must NOT
        # inflate the Target count (regression for the "38 vs 30 ticks" bug).
        _intent("DGAP", "hold", 9999, in_target=False, current_weight=0.0),
    ]
    return {"run": {"run_id": "t1", "run_date": "2026-06-06"}, "intents": intents}


def _rank_row(ticker, rank, prior_rank=None, rank_slope=None):
    return {
        "ticker": ticker, "rank": rank, "name": ticker + " Corp",
        "prior_rank": prior_rank, "rank_slope": rank_slope,
        "composite_score": 0.75, "percentile": 0.9, "cluster_id": None,
        "market_cap": 5e9,
        "factor_scores": {"momentum": 0.6, "quality": 0.5, "value": 0.4,
                          "growth": 0.5, "low_volatility": 0.5, "liquidity": 0.6},
        "held": False, "vetter_excluded": False,
    }


def _rankings_payload():
    # AAA improving (prior 3 → now 1 = up arrow); CCC worsening (prior 1 → now 3 = down).
    # HHH deliberately ABSENT → exercises the fallback row from the intent alone.
    return {"rankings": [
        _rank_row("AAA", 1, prior_rank=3),
        _rank_row("BBB", 2),
        _rank_row("CCC", 3, prior_rank=1),
        _rank_row("DDD", 4),
        _rank_row("EEE", 5),
        _rank_row("FFF", 6),
        _rank_row("GGG", 7),
    ]}


def _page() -> str:
    # Markup the boot path + target render touch (mirrors services/dashboard/app/main.py).
    return """<!doctype html><html><head><meta charset="utf-8"></head><body>
      <span id="sb-regime" class="regime-pill">—</span>
      <div id="sb-text"></div><div id="sb-sub" style="display:none"></div>
      <span id="ds-date"></span><span id="ds-pending"></span>
      <span id="ds-inflight"></span><span id="ds-done"></span>
      <div id="trader-toolbar"></div>
      <input id="select-all-trades" type="checkbox">
      <button id="btn-approve-sel"></button><span id="sel-count"></span>
      <span id="nav-trade-badge"></span>
      <table><tbody id="r-body"></tbody></table>
      <table><tbody id="trader-body"></tbody></table>
      <table id="holdings-status-table"><tbody id="holdings-status-body"></tbody></table>
      <table><tbody id="live-body"></tbody></table>
      <table><tbody id="orders-body"></tbody></table>
      <span id="target-sub"></span>
      <table>
        <thead><tr>
          <th onclick="sortTarget('rank')" id="tgh-rank">#</th>
          <th onclick="sortTarget('ticker')" id="tgh-ticker">TICKER</th>
          <th onclick="sortTarget('held')" id="tgh-held">HELD</th>
          <th onclick="sortTarget('in_target')" id="tgh-target">TARGET</th>
          <th onclick="sortTarget('trade')" id="tgh-trade">TRADE</th>
        </tr></thead>
        <tbody id="target-body"></tbody>
      </table>
    </body></html>"""


def _cell_text(page, ticker, td_index):
    # text_content (not inner_text) — no visibility wait needed in the CSS-less test page.
    return (page.locator(f"#tgt-row-{ticker} td").nth(td_index).text_content() or "").strip()


def _run() -> dict:
    chrome = _chrome_path()
    if chrome is None:
        return {"fatal": "no Chromium binary under /opt/pw-browsers"}
    js = DASHBOARD_JS.read_text()
    delta, rankings = _delta_payload(), _rankings_payload()
    errors: list[str] = []
    res: dict = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=chrome, headless=True,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
        )
        page = browser.new_page()
        page.on("pageerror", lambda exc: errors.append("pageerror: " + str(exc)))

        def route_api(route):
            url = route.request.url
            if "/api/delta/latest" in url:
                route.fulfill(status=200, content_type="application/json", body=json.dumps(delta))
            elif "/api/rankings/with-overlays" in url:
                route.fulfill(status=200, content_type="application/json", body=json.dumps(rankings))
            elif "/api/regime" in url:
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps({"regime": "bull_calm", "spy_price": 500}))
            else:
                route.fulfill(status=200, content_type="application/json",
                              body=json.dumps({"rankings": [], "intents": [], "run": {}}))
        page.route("**/api/**", route_api)

        page.set_content(_page())
        page.add_script_tag(content=js)
        page.wait_for_timeout(300)
        page.set_default_timeout(4000)

        # Populate the two real data sources exactly as loadDelta/loadRankings would
        # (deltaData raw intents; rankData via the real _mapRankRow), then run the
        # REAL target build+render. (We set data directly rather than via
        # loadTargetPortfolio() so the test doesn't depend on unrelated trader markup.)
        page.evaluate(
            "(d) => { deltaData = d.delta.intents;"
            "         rankData = d.rank.rankings.map(_mapRankRow);"
            "         buildTargetRows(); renderTargetTable(); }",
            {"delta": delta, "rank": rankings},
        )
        page.wait_for_timeout(200)
        res["target_html_len"] = len(page.locator("#target-body").inner_html())

        res["row_tickers"] = page.eval_on_selector_all(
            "#target-body tr.rank-row",
            "els => els.map(e => e.id.replace('tgt-row-',''))",
        )
        # Marks: HELD = td[2], TARGET = td[3], TRADE = td[4].
        res["AAA_held"]   = page.locator("#tgt-row-AAA td").nth(2).locator(".tgt-x").count()
        res["AAA_target"] = page.locator("#tgt-row-AAA td").nth(3).locator(".tgt-x").count()
        res["BBB_held"]   = page.locator("#tgt-row-BBB td").nth(2).locator(".tgt-x").count()
        res["BBB_target"] = page.locator("#tgt-row-BBB td").nth(3).locator(".tgt-x").count()
        res["CCC_held"]   = page.locator("#tgt-row-CCC td").nth(2).locator(".tgt-x").count()
        res["CCC_target"] = page.locator("#tgt-row-CCC td").nth(3).locator(".tgt-x").count()
        res["GGG_held"]   = page.locator("#tgt-row-GGG td").nth(2).locator(".tgt-x").count()
        res["GGG_target"] = page.locator("#tgt-row-GGG td").nth(3).locator(".tgt-x").count()
        res["DGAP_held"]   = page.locator("#tgt-row-DGAP td").nth(2).locator(".tgt-x").count()
        res["DGAP_target"] = page.locator("#tgt-row-DGAP td").nth(3).locator(".tgt-x").count()
        res["AAA_trade"] = _cell_text(page, "AAA", 4)
        res["BBB_trade"] = _cell_text(page, "BBB", 4)
        res["CCC_trade"] = _cell_text(page, "CCC", 4)
        res["FFF_trade"] = _cell_text(page, "FFF", 4)
        res["GGG_trade"] = _cell_text(page, "GGG", 4)
        res["HHH_rank"]  = _cell_text(page, "HHH", 0)
        res["AAA_arrow_up"] = page.locator("#tgt-row-AAA .rank-up").count()
        res["CCC_arrow_dn"] = page.locator("#tgt-row-CCC .rank-dn").count()

        # Sort by ticker descending (click twice) → first row should be HHH.
        page.evaluate("() => sortTarget('ticker')")  # asc
        page.evaluate("() => sortTarget('ticker')")  # desc
        page.wait_for_timeout(100)
        res["first_after_desc"] = page.eval_on_selector_all(
            "#target-body tr.rank-row", "els => els[0].id.replace('tgt-row-','')")

        # Click a row → detail card expands.
        page.eval_on_selector("#tgt-row-AAA", "el => el.click()")
        page.wait_for_timeout(100)
        res["detail_present"] = page.locator("#detail-row-AAA").count()
        res["detail_has_ticker"] = ("AAA" in (page.locator("#detail-row-AAA").text_content() or "")) if res["detail_present"] else False

        browser.close()
    res["errors"] = errors
    return res


def main() -> int:
    r = _run()
    if r.get("fatal"):
        print("FATAL:", r["fatal"]); return 1
    ok = True

    def check(cond, msg):
        nonlocal ok
        print(("  ok " if cond else "FAIL ") + msg)
        if not cond:
            ok = False

    print("=== TARGET tab playwright ===")
    print("rows:", r["row_tickers"])
    check(set(r["row_tickers"]) == {"AAA", "BBB", "CCC", "DDD", "EEE", "FFF", "GGG", "HHH", "DGAP"},
          "held∪target rows incl. watch GGG (deferred target), orphan HHH, data-gap DGAP")
    check(r["DGAP_held"] == 1 and r["DGAP_target"] == 0,
          "DGAP (data-gap hold, in_target=False) → HELD✓ TARGET· (does NOT inflate target)")
    check(r["GGG_held"] == 0 and r["GGG_target"] == 1, "GGG (watch) → HELD· TARGET✓ (deferred)")
    check(r["GGG_trade"] == "Watch", f"GGG trade label = Watch (got {r.get('GGG_trade')!r})")
    check(r["AAA_held"] == 1 and r["AAA_target"] == 1, "AAA (hold) → HELD✓ TARGET✓")
    check(r["BBB_held"] == 0 and r["BBB_target"] == 1, "BBB (entry) → HELD· TARGET✓")
    check(r["CCC_held"] == 1 and r["CCC_target"] == 0, "CCC (exit) → HELD✓ TARGET·")
    check(r["AAA_trade"] == "Hold", f"AAA trade label = Hold (got {r['AAA_trade']!r})")
    check(r["BBB_trade"] == "Buy",  f"BBB trade label = Buy (got {r['BBB_trade']!r})")
    check(r["CCC_trade"] == "Sell", f"CCC trade label = Sell (got {r['CCC_trade']!r})")
    check(r["FFF_trade"] == "At risk", f"FFF trade label = At risk (got {r['FFF_trade']!r})")
    check(r["AAA_arrow_up"] == 1, "AAA shows an up arrow (prior 3 → now 1)")
    check(r["CCC_arrow_dn"] == 1, "CCC shows a down arrow (prior 1 → now 3)")
    check(r["HHH_rank"].startswith("142"), f"HHH fallback row shows intent rank 142 (got {r['HHH_rank']!r})")
    check(r["first_after_desc"] == "HHH", f"ticker desc sort → HHH first (got {r['first_after_desc']!r})")
    check(r["detail_present"] == 1 and r["detail_has_ticker"], "row click expands the detail card")
    check(not r["errors"], f"no JS page errors ({r['errors']})")

    print("\n=== RESULT:", "PASS ===" if ok else "FAIL ===")
    return 0 if ok else 1


import pytest  # noqa: E402


@pytest.mark.skipif(_chrome_path() is None, reason="no Chromium binary")
def test_target_tab_marks_and_data_gap_hold():
    """Regression: a data-gap HOLD (in_target=False) shows HELD✓ but TARGET·, so the
    Target column reflects the real builder target (not inflated by held-not-target
    names) — the '38 vs 30 ticks' bug. Also re-checks the held/target taxonomy."""
    r = _run()
    assert not r.get("fatal"), r["fatal"]
    assert not r["errors"], r["errors"]
    assert r["DGAP_held"] == 1 and r["DGAP_target"] == 0, "data-gap hold must not tick TARGET"
    assert r["AAA_held"] == 1 and r["AAA_target"] == 1, "in-target hold ticks TARGET"
    assert r["CCC_held"] == 1 and r["CCC_target"] == 0, "exit/orphan does not tick TARGET"
    assert r["GGG_held"] == 0 and r["GGG_target"] == 1, "watch (deferred target) ticks TARGET"


if __name__ == "__main__":
    sys.exit(main())
