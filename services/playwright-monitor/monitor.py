"""
Playwright status monitor for the Stocker dashboard.

Connects to the live dashboard, triggers a manual pipeline run, then records
every status transition — label text, pipeline-bar state, progress bar — until
the chain completes or 90 minutes elapse.  Screenshots are saved for each
transition.  A JSON event log is written to /artifacts/monitor_run.json.

Usage (inside the Docker container):
    python monitor.py [--url http://dashboard:8000] [--timeout-mins 90]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

ARTIFACTS = Path(os.getenv("ARTIFACTS_DIR", "/artifacts"))
ARTIFACTS.mkdir(parents=True, exist_ok=True)


def _ts() -> str:
    return datetime.utcnow().strftime("%H:%M:%S.%f")[:-3]


def _snapshot(page) -> dict[str, Any]:
    """Read the current visible state of the status bar and pipeline bar."""
    try:
        sb_text  = page.locator("#sb-text").inner_text(timeout=2000).strip()
    except Exception:
        sb_text  = "?"
    try:
        sb_sub   = page.locator("#sb-sub").inner_text(timeout=2000).strip()
    except Exception:
        sb_sub   = ""

    try:
        pb_label = page.locator("#pb-label").inner_text(timeout=2000).strip()
    except Exception:
        pb_label = "?"
    try:
        pb_dot_cls = page.locator("#pb-dot").get_attribute("class", timeout=2000) or ""
    except Exception:
        pb_dot_cls = ""
    try:
        pb_pct   = page.locator("#pb-pct").inner_text(timeout=2000).strip()
    except Exception:
        pb_pct   = ""
    try:
        prog_visible = page.locator("#pb-prog-wrap").is_visible(timeout=2000)
    except Exception:
        prog_visible = False
    try:
        btn_disabled = page.locator("#run-btn").is_disabled(timeout=2000)
    except Exception:
        btn_disabled = False

    return {
        "sb_text":      sb_text,
        "sb_sub":       sb_sub,
        "pb_label":     pb_label,
        "pb_dot_class": pb_dot_cls,
        "pb_pct":       pb_pct,
        "prog_visible": prog_visible,
        "btn_disabled": btn_disabled,
    }


def _sig(snap: dict) -> str:
    """Compact key that changes only when something meaningful changes."""
    return f"{snap['sb_text']}|{snap['pb_label']}|{snap['pb_dot_class']}|{snap['pb_pct']}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default=os.getenv("DASHBOARD_URL", "http://dashboard:8000"))
    ap.add_argument("--timeout-mins", type=int, default=int(os.getenv("MONITOR_TIMEOUT_MINS", "90")))
    ap.add_argument("--poll-secs", type=float, default=float(os.getenv("POLL_SECS", "2.0")))
    ap.add_argument("--headless", action=argparse.BooleanOptionalAction, default=True)
    args = ap.parse_args()

    deadline = time.time() + args.timeout_mins * 60
    events: list[dict] = []
    screenshot_idx = 0

    def save_screenshot(page, label: str) -> str:
        nonlocal screenshot_idx
        screenshot_idx += 1
        name = f"{screenshot_idx:04d}_{label.replace(' ', '_').replace('/', '-')[:40]}.png"
        path = ARTIFACTS / name
        try:
            page.screenshot(path=str(path), full_page=False)
        except Exception:
            pass
        return name

    def record(page, snap: dict, event: str, extra: str = ""):
        ts = _ts()
        fname = save_screenshot(page, event)
        entry = {
            "ts":    ts,
            "event": event,
            "extra": extra,
            **snap,
            "screenshot": fname,
        }
        events.append(entry)
        line = f"[{ts}] {event:30s}  sb={snap['sb_text']!r}  pb={snap['pb_label']!r}  pct={snap['pb_pct']!r}"
        if extra:
            line += f"  ({extra})"
        print(line, flush=True)

    from playwright.sync_api import sync_playwright

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=args.headless)
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 900},
            # Record a video for post-hoc review
            record_video_dir=str(ARTIFACTS),
            record_video_size={"width": 1280, "height": 900},
        )
        page = ctx.new_page()

        # ── Wait for dashboard to be up ───────────────────────────────────
        print(f"[{_ts()}] Connecting to {args.url} …", flush=True)
        for attempt in range(60):
            try:
                page.goto(args.url, timeout=5000, wait_until="domcontentloaded")
                break
            except Exception as e:
                if attempt == 59:
                    print(f"Dashboard not reachable after 60 attempts: {e}")
                    sys.exit(1)
                time.sleep(5)

        print(f"[{_ts()}] Dashboard loaded — waiting for initial render …", flush=True)
        page.wait_for_timeout(4000)  # let the boot sequence finish

        snap = _snapshot(page)
        record(page, snap, "initial_state")

        # ── Click Run ─────────────────────────────────────────────────────
        run_btn = page.locator("#run-btn")
        if run_btn.count() == 0:
            print("ERROR: #run-btn not found on page")
            sys.exit(1)

        if run_btn.is_disabled():
            print(f"[{_ts()}] Run button is disabled — waiting up to 60 s …", flush=True)
            run_btn.wait_for(state="enabled", timeout=60000)

        print(f"[{_ts()}] Clicking Run button …", flush=True)
        run_btn.click()
        page.wait_for_timeout(1500)

        snap = _snapshot(page)
        record(page, snap, "after_run_click")

        # ── Monitor loop ──────────────────────────────────────────────────
        prev_sig = _sig(snap)
        terminal_statuses = {"READY", "PIPELINE FAILED", "NO DATA", "IDLE"}
        consecutive_terminal = 0
        TERMINAL_CONFIRM = 3   # require 3 consecutive stable terminal readings

        print(f"[{_ts()}] Monitoring for up to {args.timeout_mins} min …", flush=True)

        while time.time() < deadline:
            time.sleep(args.poll_secs)
            try:
                snap = _snapshot(page)
            except Exception as e:
                print(f"[{_ts()}] snapshot error: {e}", flush=True)
                continue

            sig = _sig(snap)
            if sig != prev_sig:
                # Triage: is this a backwards jump?
                extra = ""
                prev_sb = events[-1]["sb_text"] if events else ""
                curr_sb = snap["sb_text"]
                # Known forward order
                _order = [
                    "IDLE", "QUEUED", "FETCHING DATA", "CALCULATING FACTORS",
                    "RANKING STOCKS", "EVALUATING SIGNALS", "VETTING", "LLM ANALYSIS",
                    "BUILDING PORTFOLIO", "READY", "PIPELINE RUNNING",
                ]
                def _rank(s: str) -> int:
                    for i, v in enumerate(_order):
                        if v in s:
                            return i
                    return -1

                prev_r = _rank(prev_sb)
                curr_r = _rank(curr_sb)
                if prev_r > 0 and curr_r >= 0 and curr_r < prev_r:
                    extra = f"⚠️  BACKWARDS JUMP from {prev_sb!r} to {curr_sb!r}"
                    print(f"\n{'='*70}\n{extra}\n{'='*70}\n", flush=True)

                record(page, snap, "transition", extra)
                prev_sig = sig

            # Check for terminal state
            sb = snap["sb_text"]
            reached_terminal = any(t in sb for t in terminal_statuses)
            btn_re_enabled = not snap["btn_disabled"]
            if reached_terminal and btn_re_enabled:
                consecutive_terminal += 1
                if consecutive_terminal >= TERMINAL_CONFIRM:
                    snap = _snapshot(page)
                    record(page, snap, "terminal_confirmed")
                    break
            else:
                consecutive_terminal = 0

        # ── Final screenshot ──────────────────────────────────────────────
        snap = _snapshot(page)
        record(page, snap, "final_state")

        ctx.close()
        browser.close()

    # ── Write JSON report ─────────────────────────────────────────────────
    report_path = ARTIFACTS / "monitor_run.json"
    report = {
        "url":         args.url,
        "started_utc": events[0]["ts"] if events else "?",
        "ended_utc":   events[-1]["ts"] if events else "?",
        "events":      events,
        "backwards_jumps": [e for e in events if "BACKWARDS" in e.get("extra", "")],
    }
    report_path.write_text(json.dumps(report, indent=2))
    print(f"\n[{_ts()}] Report written to {report_path}", flush=True)
    print(f"[{_ts()}] Total events: {len(events)}", flush=True)

    jumps = report["backwards_jumps"]
    if jumps:
        print(f"\n⚠️  {len(jumps)} BACKWARDS JUMP(S) DETECTED:", flush=True)
        for j in jumps:
            print(f"  [{j['ts']}] {j['extra']}", flush=True)
        sys.exit(2)
    else:
        print(f"\n✅ No backwards status jumps detected.", flush=True)
        sys.exit(0)


if __name__ == "__main__":
    main()
