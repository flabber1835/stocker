"""
Playwright script: click Run on the dashboard, capture every status bar
transition until the pipeline reaches READY or FAILED (or times out).
"""
import asyncio
import time
from pathlib import Path
from playwright.async_api import async_playwright

DASH = "http://localhost:8004"
SHOTS = Path("/home/user/stocker/screenshots")
SHOTS.mkdir(exist_ok=True)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=["--no-sandbox"])
        page = await browser.new_page(viewport={"width": 1400, "height": 900})

        # ── Load dashboard ────────────────────────────────────────────────────
        print("→ Loading dashboard...")
        await page.goto(DASH, wait_until="networkidle")
        await page.screenshot(path=str(SHOTS / "00_initial.png"))
        print("  ✓ Saved 00_initial.png")

        # Read initial status bar
        sb = await page.locator("#sb-text").text_content()
        print(f"  Initial status: {sb!r}")

        # ── Find and click the Run button ─────────────────────────────────────
        run_btn = page.locator("#run-btn")
        await run_btn.wait_for(state="visible", timeout=10_000)
        is_disabled = await run_btn.is_disabled()
        print(f"  Run button visible, disabled={is_disabled}")

        await page.screenshot(path=str(SHOTS / "01_before_click.png"))
        print("  ✓ Saved 01_before_click.png")

        await run_btn.click()
        print("  ✓ Clicked Run")

        # ── Poll status bar, capture every transition ─────────────────────────
        prev_label = None
        shot_idx = 2
        deadline = time.time() + 600  # 10-minute timeout

        while time.time() < deadline:
            await asyncio.sleep(2)

            sb_text = (await page.locator("#sb-text").text_content() or "").strip()
            sb_sub  = (await page.locator("#sb-sub").text_content()  or "").strip()
            pb_label = (await page.locator("#pb-label").text_content() or "").strip()

            label = sb_text
            if sb_sub:
                label += f" / {sb_sub}"

            if label != prev_label:
                fname = f"{shot_idx:02d}_{sb_text.replace(' ', '_')[:40]}.png"
                await page.screenshot(path=str(SHOTS / fname))
                print(f"  [{shot_idx:02d}] status={sb_text!r}  sub={sb_sub!r}  pb={pb_label!r}  → {fname}")
                shot_idx += 1
                prev_label = label

            if sb_text in ("READY", "PIPELINE FAILED", "NO DATA"):
                print(f"\n  ✓ Terminal state reached: {sb_text!r}")
                break

        await page.screenshot(path=str(SHOTS / f"{shot_idx:02d}_final.png"))
        print(f"  ✓ Saved final screenshot")
        await browser.close()


asyncio.run(main())
