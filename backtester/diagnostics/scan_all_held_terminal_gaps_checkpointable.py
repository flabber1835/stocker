#!/usr/bin/env python3
"""Checkpoint-capable comprehensive held-terminal-gap scanner.

The production SessionState chronology is transported by backtester.checkpoint_runner.
Scanner-only evidence (captured gap episodes and overlay diagnostic invalidity) is
carried inside the checkpoint's hashed experiment extension and restored before
resume validation. The scanner uses the same v3 causal terminal terms and frozen
primary-source split adjudications as the final replay.

This remains a diagnostic scan. OverlayAccount NAV is not a backtest result after
an unresolved-open allocation collision.
"""
from __future__ import annotations

import copy
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from backtester import checkpoint_runner  # noqa: E402


def _jsonable(value):
    if dataclasses.is_dataclass(value):
        return dataclasses.asdict(value)
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raw = getattr(value, "__dict__", None)
    return _jsonable(raw) if raw is not None else repr(value)


def _arg_value(flag: str):
    args = sys.argv[1:]
    for i, value in enumerate(args):
        if value == flag and i + 1 < len(args):
            return args[i + 1]
        prefix = flag + "="
        if value.startswith(prefix):
            return value[len(prefix):]
    return None


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> int:
    lab = Path(os.environ.get("BACKTESTER_LAB_ROOT", ".")).resolve()
    main_root = Path(os.environ.get("BACKTESTER_MAIN_ROOT", "main-src")).resolve()
    output = Path(os.environ.get(
        "BACKTESTER_TERMINAL_GAP_OUTPUT",
        "backtester-results/all-held-terminal-gaps.json",
    )).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    sys.path.insert(0, str(lab))
    sys.path.insert(0, str(main_root / "shared"))
    sys.path.insert(0, str(main_root))

    from backtester import run_sector_ad_causal_terminal_splits_v3 as v3

    v2 = v3.v2
    runner = v3.runner
    runner.EXPERIMENT_ID = "2026-08-28-held-terminal-gap-scan-checkpointed-v3"
    runner.MEASUREMENT_WINDOWS = {}

    import sentinel.core.production as production

    real_advance = production.advance_state
    advance_cache = {"session": None, "result": None, "a_calls": 0, "collapsed": 0}

    def a_only_advance(state, published, *args, **kwargs):
        session = str(published.session)
        if advance_cache["session"] == session:
            advance_cache["collapsed"] += 1
            return copy.deepcopy(advance_cache["result"])
        result = real_advance(state, published, *args, **kwargs)
        advance_cache["session"] = session
        advance_cache["result"] = copy.deepcopy(result)
        advance_cache["a_calls"] += 1
        return result

    production.advance_state = a_only_advance

    gap_events: list[dict] = []
    gap_index: dict[tuple[str, str], int] = {}
    session_gap_indices: list[int] = []
    captured = {"state": None, "session": None}
    invalid_overlay_from: str | None = None
    prior_a_calls = 0
    prior_collapsed = 0

    resume_text = _arg_value("--resume-checkpoint")
    if resume_text:
        payload = checkpoint_runner._load_checkpoint(Path(resume_text).resolve())
        ext = (payload.get("extra_identity") or {}).get("scanner_state") or {}
        rows = ext.get("gap_events") or []
        if not isinstance(rows, list):
            raise RuntimeError("checkpoint scanner gap_events is not a list")
        gap_events.extend(copy.deepcopy(rows))
        for index, row in enumerate(gap_events):
            key = (str(row.get("security_id") or ""), str(row.get("entry_date") or ""))
            if not key[0] or key in gap_index:
                raise RuntimeError("checkpoint scanner gap episode keys are invalid/duplicated")
            gap_index[key] = index
        invalid_overlay_from = ext.get("invalid_overlay_from")
        prior_a_calls = int(ext.get("a_production_transitions") or 0)
        prior_collapsed = int(ext.get("collapsed_second_arm_transitions") or 0)

    real_wc = runner.wealth_equities

    def capture_wc(state):
        captured["state"] = state
        session = str(state.last_processed_session)
        captured["session"] = session
        session_gap_indices.clear()

        wc = dict(((state.last_evidence or {}).get("wealth_core") or {}))
        unresolved = [str(x) for x in (wc.get("open_unresolved_security_ids") or ())]
        if unresolved:
            episodes = dict((state.wealth_core or {}).get("episodes") or {})
            by_sid = {}
            for slot_id, episode in sorted(episodes.items(), key=lambda item: str(item[0])):
                sid = str((episode or {}).get("security_id", ""))
                if sid in unresolved:
                    by_sid[sid] = {"slot_id": str(slot_id), "episode": _jsonable(episode)}

            for sid in sorted(unresolved):
                held = by_sid.get(sid)
                episode = dict((held or {}).get("episode") or {})
                key = (sid, str(episode.get("entry_date") or ""))
                index = gap_index.get(key)
                if index is None:
                    index = len(gap_events)
                    gap_index[key] = index
                    gap_events.append({
                        "security_id": sid,
                        "ticker": str(episode.get("ticker") or ""),
                        "entry_date": episode.get("entry_date"),
                        "slot_id": (held or {}).get("slot_id"),
                        "shares": episode.get("current_shares"),
                        "first_unresolved_session": session,
                        "last_unresolved_session": session,
                        "unresolved_session_count": 1,
                        "allocation_transition_collision_sessions": [],
                        "first_wealth_core_evidence": wc,
                        "first_episode": episode,
                        "terminal_pending_terms": _jsonable(
                            (state.wealth_core or {}).get("terminal_pending_terms") or {}),
                        "unresolved_terminals": _jsonable(
                            (state.wealth_core or {}).get("unresolved_terminals") or {}),
                    })
                    print(
                        f"[GAP] first unresolved held terminal sid={sid} "
                        f"ticker={gap_events[index]['ticker']} session={session}",
                        flush=True,
                    )
                else:
                    row = gap_events[index]
                    row["last_unresolved_session"] = session
                    row["unresolved_session_count"] = int(row["unresolved_session_count"]) + 1
                session_gap_indices.append(index)

        return real_wc(state)

    runner.wealth_equities = capture_wc

    real_step = runner.OverlayAccount.step

    def scanner_step(account, core_open, core_close, prior_core_close,
                     bil_gap, bil_intraday, next_target):
        nonlocal invalid_overlay_from
        collision = (
            core_open is None
            and account.initialized
            and prior_core_close is not None
            and abs(account.pending - account.effective) > 1e-15
        )
        if collision:
            session = str(captured.get("session") or "")
            if str(account.name) == "A":
                for index in session_gap_indices:
                    gap_events[index]["allocation_transition_collision_sessions"].append(session)
                if invalid_overlay_from is None:
                    invalid_overlay_from = session
                print(
                    f"[GAP] allocation-transition collision session={session} "
                    f"gap_count={len(session_gap_indices)}",
                    flush=True,
                )

            core_c2c = core_close / prior_core_close
            bil_c2c = bil_gap * bil_intraday
            account.nav *= account.effective * core_c2c + (1.0 - account.effective) * bil_c2c
            account.effective = account.pending
            account.pending = next_target
            return account.nav

        return real_step(
            account, core_open, core_close, prior_core_close,
            bil_gap, bil_intraday, next_target)

    runner.OverlayAccount.step = scanner_step

    def scanner_extension() -> dict:
        return {
            "terminal_terms_json_sha256": _sha(v2.TERMS_PATH),
            "terminal_terms_checksum_sha256": _sha(v2.TERMS_CHECKSUM_PATH),
            "split_overrides_json_sha256": _sha(v3.SPLIT_DATA),
            "split_overrides_checksum_sha256": _sha(v3.SPLIT_SUMS),
            "scanner_state": {
                "gap_events": gap_events,
                "invalid_overlay_from": invalid_overlay_from,
                "a_production_transitions": prior_a_calls + int(advance_cache["a_calls"]),
                "collapsed_second_arm_transitions": prior_collapsed + int(advance_cache["collapsed"]),
            },
        }

    runner.CHECKPOINT_EXTRA_IDENTITY = scanner_extension

    # The scanner's output is terminal-gap evidence. Split defects have their
    # own full-corpus certification workflow and must not suppress this evidence.
    # Reuse the bounded-audit transport switch locally and move its full-end
    # guard beyond the corpus only in this diagnostic process.
    checkpoint_runner.FULL_END_SESSION = "9999-12-31"
    os.environ["BACKTESTER_EQUIV_IGNORE_FINAL_SPLIT_AUDIT"] = "1"
    print(
        "[GAP] final unresolved-split verdict delegated to separate full-corpus split audit",
        flush=True,
    )

    stopped = _arg_value("--stop-after-session") is not None
    print("[GAP] checkpoint-capable A-only held-terminal-gap traversal started", flush=True)
    runner_error = None
    rc = 0
    try:
        rc = int(checkpoint_runner.run(runner))
    except Exception as exc:
        runner_error = repr(exc)
        rc = 1
        print(f"[GAP] runner error after captured evidence: {runner_error}", flush=True)
    finally:
        production.advance_state = real_advance
        if v3._real_split_decide is not None:
            v3.split_module.SplitStreamReconciler.decide = v3._real_split_decide
            v3._real_split_decide = None

    if stopped:
        return rc

    total_a_calls = prior_a_calls + int(advance_cache["a_calls"])
    total_collapsed = prior_collapsed + int(advance_cache["collapsed"])
    payload = {
        "schema": "backtester.held-terminal-gap-scan/2",
        "status": "PASS" if rc == 0 else "RUNNER_ERROR",
        "runner_error": runner_error,
        "strategy_main_sha": os.environ.get("BACKTESTER_MAIN_SHA"),
        "backtester_sha": os.environ.get("BACKTESTER_BRANCH_SHA"),
        "fresh_chronological_replay": True,
        "checkpoint_resume_capable": True,
        "v3_split_adjudications_active": True,
        "diagnostic_only": True,
        "session_economics_approximated": False,
        "overlay_nav_authoritative": invalid_overlay_from is None,
        "overlay_nav_invalid_from": invalid_overlay_from,
        "a_production_transitions": total_a_calls,
        "collapsed_second_arm_transitions": total_collapsed,
        "distinct_held_terminal_gap_count": len(gap_events),
        "allocation_transition_collision_count": sum(
            len(row["allocation_transition_collision_sessions"]) for row in gap_events),
        "gaps": gap_events,
    }
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        f"[GAP] completed rc={rc} distinct_gaps={len(gap_events)} "
        f"A_transitions={total_a_calls}",
        flush=True,
    )
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
