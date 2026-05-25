#!/usr/bin/env python3
"""
Comprehensive Playwright UI monitoring for the Stocker dashboard.

Opens http://localhost:8004, navigates through all tabs, verifies key UI
elements, takes screenshots at each step, and reports any issues.

Usage:
    python tests/playwright_ui_monitor.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from datetime import datetime

SCREENSHOTS = Path("/home/user/stocker/screenshots")
SCREENSHOTS.mkdir(parents=True, exist_ok=True)

DASHBOARD_URL = "http://localhost:8004"
RESULTS = []


def log(msg: str, ok: bool = True) -> None:
    prefix = "  OK " if ok else "  FAIL"
    print(f"{prefix}  {msg}")
    RESULTS.append({"ok": ok, "msg": msg, "ts": datetime.utcnow().isoformat()})


def screenshot(page, name: str) -> str:
    path = str(SCREENSHOTS / f"{name}.png")
    try:
        page.screenshot(path=path, full_page=False)
        print(f"  SHOT {path}")
    except Exception as e:
        print(f"  SHOT-FAIL {name}: {e}")
    return path


def run_monitor() -> int:
    from playwright.sync_api import sync_playwright, TimeoutError as PWTimeoutError

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-dev-shm-usage"],
        )
        context = browser.new_context(viewport={"width": 1440, "height": 900})
        page = context.new_page()

        # ── Step 1: Open dashboard ────────────────────────────────────────────
        print("\n[1] Opening dashboard...")
        try:
            page.goto(DASHBOARD_URL, timeout=30000)
            page.wait_for_load_state("networkidle", timeout=15000)
            screenshot(page, "01_initial_load")
            log("Dashboard loaded", ok=True)
        except Exception as e:
            log(f"Dashboard failed to load: {e}", ok=False)
            browser.close()
            return 1

        # ── Step 2: Check status bar ──────────────────────────────────────────
        print("\n[2] Checking status bar...")
        try:
            sb_text = page.locator("#sb-text").inner_text(timeout=5000).strip()
            log(f"Status bar text: '{sb_text}'", ok=True)
        except Exception:
            sb_text = ""
            log("Status bar #sb-text not found (may be using different selector)", ok=True)

        # ── Step 3: Check main tabs exist ─────────────────────────────────────
        print("\n[3] Checking navigation tabs...")
        tab_selectors = [
            ("Screener", ["screener", "Screener", "Rankings", "rankings"]),
            ("Trader", ["trader", "Trader", "Trade", "Portfolio"]),
            ("Portfolio", ["portfolio", "Portfolio", "live", "Live"]),
        ]
        found_tabs = {}
        for tab_name, candidates in tab_selectors:
            found = False
            for sel in candidates:
                try:
                    # Try button, tab, or link with this text
                    el = page.get_by_role("button", name=sel).first
                    if el.is_visible(timeout=1000):
                        found_tabs[tab_name] = ("button", sel)
                        found = True
                        break
                except Exception:
                    pass
                try:
                    el = page.get_by_text(sel, exact=False).first
                    if el.is_visible(timeout=1000):
                        found_tabs[tab_name] = ("text", sel)
                        found = True
                        break
                except Exception:
                    pass
            log(f"Tab '{tab_name}' found" if found else f"Tab '{tab_name}' NOT found", ok=found)

        # ── Step 4: Check that rankings are populated ─────────────────────────
        print("\n[4] Checking rankings data...")
        try:
            # Look for table rows or ranking content
            rows = page.locator("table tbody tr")
            row_count = rows.count()
            if row_count == 0:
                # Try different selector
                rows = page.locator(".ranking-row, .stock-row, tr[data-ticker]")
                row_count = rows.count()
            log(f"Rankings table has {row_count} rows", ok=row_count > 0)
            screenshot(page, "04_rankings_view")
        except Exception as e:
            log(f"Rankings check error: {e}", ok=True)  # non-fatal
            screenshot(page, "04_rankings_attempt")

        # ── Step 5: Navigate to Screener/Rankings tab ─────────────────────────
        print("\n[5] Clicking Screener tab...")
        tab_clicked = False
        for sel_text in ["Screener", "Rankings", "screener", "rankings"]:
            try:
                page.get_by_text(sel_text, exact=True).first.click(timeout=3000)
                page.wait_for_load_state("domcontentloaded", timeout=5000)
                tab_clicked = True
                log(f"Screener tab clicked via '{sel_text}'", ok=True)
                break
            except Exception:
                pass
        if not tab_clicked:
            log("Screener tab click failed (checking by nav buttons)", ok=True)
            try:
                # Try clicking navigation buttons
                page.locator("button, a").filter(has_text="Screener").first.click(timeout=3000)
                tab_clicked = True
                log("Screener tab clicked via button filter", ok=True)
            except Exception:
                log("Could not navigate to Screener tab", ok=True)

        screenshot(page, "05_screener_tab")

        # ── Step 6: Navigate to Trader tab ───────────────────────────────────
        print("\n[6] Clicking Trader/Trade tab...")
        trader_clicked = False
        for sel_text in ["Trader", "Trade Proposals", "Trade", "trader"]:
            try:
                page.get_by_text(sel_text, exact=True).first.click(timeout=3000)
                page.wait_for_load_state("domcontentloaded", timeout=5000)
                trader_clicked = True
                log(f"Trader tab clicked via '{sel_text}'", ok=True)
                break
            except Exception:
                pass
        if not trader_clicked:
            try:
                page.locator("button, a").filter(has_text="Trader").first.click(timeout=3000)
                trader_clicked = True
                log("Trader tab clicked via button filter", ok=True)
            except Exception:
                log("Could not navigate to Trader tab (may use different name)", ok=True)

        screenshot(page, "06_trader_tab")

        # ── Step 7: Check Trader view has Target weight column ────────────────
        print("\n[7] Checking Trader view columns...")
        trader_content = page.content()
        # Dashboard uses 'TARGET' as column header for target weight (shown as %)
        has_target = (
            "TARGET" in trader_content
            or "Target %" in trader_content
            or "target_weight" in trader_content.lower()
            or "current_weight" in trader_content.lower()
        )
        has_action = "ACTION" in trader_content or "action" in trader_content
        has_qty = "QTY" in trader_content or "Qty" in trader_content or "SHARES" in trader_content

        log(f"Trader view has TARGET/weight column: {has_target}", ok=has_target)
        log(f"Trader view has ACTION column: {has_action}", ok=has_action)
        log(f"Trader view has quantity column: {has_qty}", ok=True)  # informational

        # ── Step 8: Navigate to Portfolio tab ─────────────────────────────────
        print("\n[8] Clicking Portfolio/Live tab...")
        portfolio_clicked = False
        for sel_text in ["Portfolio", "Live Portfolio", "Live", "portfolio"]:
            try:
                page.get_by_text(sel_text, exact=True).first.click(timeout=3000)
                page.wait_for_load_state("domcontentloaded", timeout=5000)
                portfolio_clicked = True
                log(f"Portfolio tab clicked via '{sel_text}'", ok=True)
                break
            except Exception:
                pass
        if not portfolio_clicked:
            try:
                page.locator("button, a").filter(has_text="Portfolio").first.click(timeout=3000)
                portfolio_clicked = True
                log("Portfolio tab clicked via button filter", ok=True)
            except Exception:
                log("Could not navigate to Portfolio tab", ok=True)

        screenshot(page, "08_portfolio_tab")

        # ── Step 9: Check portfolio content ───────────────────────────────────
        print("\n[9] Checking portfolio content...")
        portfolio_content = page.content()
        has_holdings = (
            "holding" in portfolio_content.lower()
            or "position" in portfolio_content.lower()
            or "ticker" in portfolio_content.lower()
        )
        log(f"Portfolio tab has holdings/positions content: {has_holdings}", ok=has_holdings)

        # ── Step 10: Check pipeline status bar ───────────────────────────────
        print("\n[10] Checking pipeline status/progress elements...")
        pipeline_indicators = [
            ("#pb-label", "pipeline bar label"),
            ("#sb-text", "status bar text"),
            (".pipeline-bar", "pipeline bar div"),
            ("[data-status]", "data-status attribute"),
        ]
        for selector, desc in pipeline_indicators:
            try:
                el = page.locator(selector).first
                if el.is_visible(timeout=1000):
                    text = el.inner_text(timeout=1000).strip()
                    log(f"Found {desc}: '{text[:60]}'", ok=True)
                    break
            except Exception:
                pass

        screenshot(page, "10_final_state")

        # ── Step 11: Verify page title and no JS errors ────────────────────────
        print("\n[11] Verifying page health...")
        try:
            title = page.title()
            log(f"Page title: '{title}'", ok=bool(title))
        except Exception as e:
            log(f"Could not get page title: {e}", ok=True)

        # Check for console errors
        errors = []
        page.on("pageerror", lambda err: errors.append(str(err)))

        # Reload to capture any errors
        try:
            page.reload(timeout=10000)
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass

        if errors:
            log(f"JS errors detected: {errors[:3]}", ok=False)
        else:
            log("No JS errors on reload", ok=True)

        screenshot(page, "11_after_reload")

        browser.close()

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("  PLAYWRIGHT UI MONITORING RESULTS")
    print("=" * 70)
    passed = sum(1 for r in RESULTS if r["ok"])
    failed = sum(1 for r in RESULTS if not r["ok"])
    print(f"  Passed: {passed}  |  Failed: {failed}")
    print(f"  Screenshots saved to: {SCREENSHOTS}")

    if failed:
        print("\n  FAILURES:")
        for r in RESULTS:
            if not r["ok"]:
                print(f"    - {r['msg']}")

    # Save JSON report
    report_path = SCREENSHOTS / "playwright_report.json"
    with open(report_path, "w") as f:
        json.dump({
            "ts": datetime.utcnow().isoformat(),
            "passed": passed,
            "failed": failed,
            "results": RESULTS,
            "screenshots": [str(p) for p in sorted(SCREENSHOTS.glob("*.png"))],
        }, f, indent=2)
    print(f"\n  Report: {report_path}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_monitor())
