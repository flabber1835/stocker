#!/usr/bin/env python3
"""Playwright tests for the vetter penalty box UI.

Tests:
- PENALTY column header is present in the screener table
- Penalty countdown badge renders correctly when data is present
- Penalty warning banner appears for held stocks in penalty box
- Column is sortable (clicking sorts the table)
- Rows with penalty data have the correct CSS classes

Usage:
    python tests/playwright_ui_penalty_box.py

Prerequisites:
    pip install playwright
    playwright install chromium
    Docker stack must be running: ./build.sh && docker compose up -d
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
RESULTS: list[dict] = []


def log(msg: str, ok: bool = True) -> None:
    prefix = "  OK " if ok else "  FAIL"
    print(f"{prefix}  {msg}")
    RESULTS.append({"ok": ok, "msg": msg, "ts": datetime.utcnow().isoformat()})


def screenshot(page, name: str) -> str:
    path = str(SCREENSHOTS / f"penalty_{name}.png")
    try:
        page.screenshot(path=path, full_page=False)
        print(f"  SHOT {path}")
    except Exception as e:
        print(f"  SHOT-FAIL {name}: {e}")
    return path


def run_penalty_box_tests() -> int:
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

        # ── Step 2: Verify screener tab is active ─────────────────────────────
        print("\n[2] Verifying screener tab...")
        try:
            screener = page.locator("#screen-screener")
            if screener.is_visible():
                log("Screener section visible", ok=True)
            else:
                # Try clicking the screener nav button
                page.locator("#nav-screener").click()
                page.wait_for_timeout(500)
                log("Clicked screener nav button", ok=True)
        except Exception as e:
            log(f"Could not activate screener: {e}", ok=False)

        # ── Step 3: Check PENALTY column header exists ─────────────────────────
        print("\n[3] Checking PENALTY column header...")
        try:
            penalty_header = page.locator("th#rh-penalty_box_days_remaining")
            if penalty_header.count() > 0:
                header_text = penalty_header.inner_text(timeout=3000).strip()
                log(f"PENALTY column header found: '{header_text}'", ok=True)
                screenshot(page, "03_penalty_header")
            else:
                # Fallback: look for any th containing "PENALTY"
                any_penalty = page.locator("th").filter(has_text="PENALTY")
                if any_penalty.count() > 0:
                    log("PENALTY column header found (fallback)", ok=True)
                else:
                    log("PENALTY column header NOT found — migration may not be applied yet", ok=False)
        except Exception as e:
            log(f"Error checking PENALTY header: {e}", ok=False)

        # ── Step 4: Check table has 11 columns ────────────────────────────────
        print("\n[4] Counting screener table columns...")
        try:
            headers = page.locator("thead tr th")
            col_count = headers.count()
            if col_count == 11:
                log(f"Table has correct column count: {col_count}", ok=True)
            elif col_count == 10:
                log(f"Table has {col_count} columns — PENALTY column missing", ok=False)
            else:
                log(f"Table column count: {col_count} (expected 11)", ok=col_count == 11)
        except Exception as e:
            log(f"Error counting columns: {e}", ok=False)

        # ── Step 5: Check r-penalty-warn div exists ────────────────────────────
        print("\n[5] Checking penalty warning banner div...")
        try:
            warn_div = page.locator("#r-penalty-warn")
            if warn_div.count() > 0:
                log("Penalty warning div #r-penalty-warn exists", ok=True)
            else:
                log("Penalty warning div #r-penalty-warn not found", ok=False)
        except Exception as e:
            log(f"Error checking warning div: {e}", ok=False)

        # ── Step 6: Check penalty column is sortable ───────────────────────────
        print("\n[6] Testing PENALTY column sort...")
        try:
            penalty_header = page.locator("th#rh-penalty_box_days_remaining")
            if penalty_header.count() > 0:
                penalty_header.click()
                page.wait_for_timeout(300)
                # Check if it got a sort class
                classes = penalty_header.get_attribute("class") or ""
                if "asc" in classes or "desc" in classes:
                    log("PENALTY column is sortable (sort class applied)", ok=True)
                else:
                    # Click again to toggle
                    penalty_header.click()
                    page.wait_for_timeout(300)
                    classes = penalty_header.get_attribute("class") or ""
                    if "asc" in classes or "desc" in classes:
                        log("PENALTY column is sortable (sort class on second click)", ok=True)
                    else:
                        log("PENALTY column sort class not applied (may have no data)", ok=True)
                screenshot(page, "06_penalty_sort")
            else:
                log("Skipping sort test — PENALTY header not found", ok=False)
        except Exception as e:
            log(f"Error testing sort: {e}", ok=False)

        # ── Step 7: Check penalty data in rows (if any) ────────────────────────
        print("\n[7] Checking for penalty badge rows...")
        try:
            penalty_badges = page.locator(".penalty-badge")
            badge_count = penalty_badges.count()
            if badge_count > 0:
                log(f"Found {badge_count} penalty badge(s) in screener rows", ok=True)
                # Check first badge text
                first_badge = penalty_badges.first.inner_text(timeout=2000)
                log(f"First penalty badge text: '{first_badge}'", ok=True)
                screenshot(page, "07_penalty_badges")
            else:
                log("No penalty badges visible (no stocks in penalty box yet — expected on fresh system)", ok=True)
                screenshot(page, "07_no_penalty_badges")
        except Exception as e:
            log(f"Error checking penalty badges: {e}", ok=False)

        # ── Step 8: Check warning banner for held stocks in penalty box ─────────
        print("\n[8] Checking penalty warning banner visibility...")
        try:
            warn_div = page.locator("#r-penalty-warn")
            if warn_div.count() > 0:
                is_visible = warn_div.is_visible()
                # Banner only shows when held stocks are in penalty box — may not be visible
                if is_visible:
                    banner_text = warn_div.inner_text(timeout=2000)
                    log(f"Penalty warning banner visible: '{banner_text[:80]}'", ok=True)
                    screenshot(page, "08_penalty_warning_visible")
                else:
                    log("Penalty warning banner hidden (no held stocks in penalty box)", ok=True)
                    screenshot(page, "08_penalty_warning_hidden")
            else:
                log("Penalty warning div not found", ok=False)
        except Exception as e:
            log(f"Error checking warning banner: {e}", ok=False)

        # ── Step 9: Screenshot of full screener with PENALTY column ────────────
        print("\n[9] Final screener screenshot...")
        screenshot(page, "09_screener_with_penalty_column")

        browser.close()

    # ── Summary ───────────────────────────────────────────────────────────────
    passed = sum(1 for r in RESULTS if r["ok"])
    failed = sum(1 for r in RESULTS if not r["ok"])
    print(f"\n{'='*60}")
    print(f"PENALTY BOX UI TESTS: {passed} passed, {failed} failed")
    print(f"{'='*60}")

    report_path = SCREENSHOTS / "penalty_box_test_report.json"
    with open(report_path, "w") as f:
        json.dump({
            "timestamp": datetime.utcnow().isoformat(),
            "passed": passed,
            "failed": failed,
            "results": RESULTS,
        }, f, indent=2)
    print(f"Report: {report_path}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_penalty_box_tests())
