#!/usr/bin/env python3
"""Strategy-path PIT closure telemetry for the frozen Research Champion.

This module is audit-only. It observes already-computed replay state and writes
deterministic evidence needed to close the PIT corpus without altering decisions.
"""
from __future__ import annotations

import atexit
import csv
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path


PROFILE = "strategy9-e3-research-champion-v1"
PROFILE_SHA256 = "1101e99ae9ca327278d79d5334556ca01bbc167e2cb3410ab4902b89550e5c26"
RUNTIME_MAIN_SHA = "887f479b15ad861313da666ad698034d3847121c"
REQUIRED_LOOKBACK_SESSIONS = 126


def _finite_positive(value) -> bool:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(x) and x > 0.0


def _sid(sid_array, tid: int) -> str:
    return str(sid_array[int(tid)])


def _ticker(tick_array, tid: int) -> str:
    return str(tick_array[int(tid)])


def _set_hash(values) -> str:
    blob = "\n".join(sorted(str(x) for x in values)).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def production_leadership_return(strict_function, *, audit, **kwargs):
    """Use exact terminal evidence when available; otherwise preserve Production's
    zero-contribution convention for an unobserved next close.

    The zero contribution is audit-visible and remains a certification work item
    whenever the missing observation is attached to a terminal event without
    complete authenticated consideration.
    """
    try:
        result = strict_function(**kwargs)
        terminal = kwargs.get("terminal")
        if terminal is not None:
            audit.note_terminal_touch(
                str(kwargs.get("session") or ""),
                str(kwargs.get("security_id") or ""),
                terminal,
                reason="TERMINAL_LEADERSHIP_RETURN",
            )
        return result
    except Exception as exc:
        current = kwargs.get("current_signal")
        prior = kwargs.get("prior_signal")
        terminal = kwargs.get("terminal")
        if _finite_positive(prior) and not _finite_positive(current):
            sid = str(kwargs.get("security_id") or "")
            session = str(kwargs.get("session") or "")
            if terminal is None:
                audit.note_event(
                    "MISSING_LEADERSHIP_ZERO_CONTRIBUTION",
                    session,
                    sid,
                    detail={"source_error": type(exc).__name__},
                )
                return 0.0, "MISSING_SIGNAL_ZERO_CONTRIBUTION"
            audit.note_terminal_touch(
                session,
                sid,
                terminal,
                reason="TERMINAL_LEADERSHIP_REQUIRES_CLOSURE",
            )
            audit.note_event(
                "TERMINAL_LEADERSHIP_ZERO_CONTRIBUTION",
                session,
                sid,
                detail={"source_error": type(exc).__name__},
            )
            return 0.0, "UNRESOLVED_TERMINAL_ZERO_CONTRIBUTION"
        raise


class PathAudit:
    """Collect session-level path closure evidence and a compact security worklist."""

    def __init__(self, output):
        self.output = Path(output)
        self.output.mkdir(parents=True, exist_ok=True)
        self.records: dict[str, dict] = {}
        self.event_counts = Counter()
        self.session_count = 0
        self.first_session = None
        self.last_session = None
        self._closed = False
        self._session_handle = gzip.open(
            self.output / "strategy-path-session-ledger.jsonl.gz",
            "wt",
            encoding="utf-8",
            compresslevel=1,
        )
        self._event_handle = gzip.open(
            self.output / "strategy-path-events.jsonl.gz",
            "wt",
            encoding="utf-8",
            compresslevel=1,
        )
        atexit.register(self.close)

    def _record(self, security_id: str, ticker: str, session: str) -> dict:
        rec = self.records.get(security_id)
        if rec is None:
            rec = {
                "security_id": security_id,
                "ticker": ticker,
                "first_touch_session": session,
                "last_touch_session": session,
                "base_candidate_sessions": 0,
                "known_common_base_sessions": 0,
                "known_non_common_base_sessions": 0,
                "unknown_type_base_sessions": 0,
                "eligible_sessions": 0,
                "momentum_pool_sessions": 0,
                "durable_ranked_sessions": 0,
                "recent_leadership_sessions": 0,
                "pending_sessions": 0,
                "held_sessions": 0,
                "terminal_sessions": 0,
                "incomplete_terminal_sessions": 0,
                "best_durable_rank": None,
                "required_for_strategy_certificate": False,
                "potential_displacer": False,
                "authority_requirements": set(),
                "touch_reasons": set(),
            }
            self.records[security_id] = rec
        rec["ticker"] = ticker or rec["ticker"]
        rec["last_touch_session"] = session
        return rec

    def note_event(self, kind: str, session: str, security_id: str = "", *, detail=None):
        self.event_counts[kind] += 1
        row = {
            "kind": str(kind),
            "session": str(session),
            "security_id": str(security_id),
            "detail": detail or {},
        }
        self._event_handle.write(json.dumps(row, sort_keys=True, allow_nan=False) + "\n")
        if security_id:
            rec = self.records.get(str(security_id))
            if rec is not None:
                rec["touch_reasons"].add(str(kind))

    def note_terminal_touch(self, session: str, security_id: str, event, *, reason: str):
        security_id = str(security_id)
        session = str(session)
        rec = self._record(security_id, "", session)
        rec["terminal_sessions"] += 1
        rec["required_for_strategy_certificate"] = True
        rec["authority_requirements"].add("terminal")
        rec["touch_reasons"].add(str(reason))
        disposition = str((event or {}).get("disposition") or "")
        if disposition != "EXACT_EVIDENCE":
            rec["incomplete_terminal_sessions"] += 1
            rec["touch_reasons"].add("INCOMPLETE_TERMINAL")
        self.note_event(
            str(reason),
            session,
            security_id,
            detail={
                "disposition": disposition,
                "kind": str((event or {}).get("kind") or ""),
            },
        )

    @staticmethod
    def _classification(metadata_fn, tid: int, session: str) -> str:
        row = metadata_fn(int(tid), session)
        if row is None:
            return "unknown"
        value = str(row.get("security_type") or "")
        if value == "common":
            return "common"
        if value == "non_common":
            return "non_common"
        return "unknown"

    def observe_session(
        self,
        *,
        session,
        tids,
        sid,
        tick,
        metadata_fn,
        base_elig,
        elig,
        pool,
        durable,
        recsel,
        book,
        terminal_events,
    ):
        session = str(session)
        self.session_count += 1
        self.first_session = self.first_session or session
        self.last_session = session

        base_common = []
        base_non_common = []
        base_unknown = []
        eligible_ids = []
        pool_ids = []
        durable_ids = []
        recent_ids = []
        pending_ids = []
        held_ids = []
        terminal_ids = []

        # Candidate envelope begins before security-type classification. Every
        # unknown base candidate is retained because admitting it as common can
        # change top-decile population, cutoff geometry, leadership, or admission.
        for j, tid0 in enumerate(tids):
            if not bool(base_elig[j]):
                continue
            tid = int(tid0)
            security_id = _sid(sid, tid)
            ticker = _ticker(tick, tid)
            cls = self._classification(metadata_fn, tid, session)
            rec = self._record(security_id, ticker, session)
            rec["base_candidate_sessions"] += 1
            rec["required_for_strategy_certificate"] = True
            rec["authority_requirements"].update({"identity", "security_type", "price_volume"})
            rec["touch_reasons"].add("BASE_CANDIDATE")
            if cls == "common":
                rec["known_common_base_sessions"] += 1
                base_common.append(security_id)
            elif cls == "non_common":
                rec["known_non_common_base_sessions"] += 1
                base_non_common.append(security_id)
            else:
                rec["unknown_type_base_sessions"] += 1
                rec["potential_displacer"] = True
                rec["required_for_strategy_certificate"] = True
                rec["touch_reasons"].add("UNKNOWN_TYPE_POTENTIAL_DISPLACER")
                base_unknown.append(security_id)

        # The vectors above are numpy arrays in the generated replay. Iterate by
        # index to avoid importing numpy into this audit module.
        for j, tid0 in enumerate(tids):
            if not bool(elig[j]):
                continue
            tid = int(tid0)
            security_id = _sid(sid, tid)
            ticker = _ticker(tick, tid)
            rec = self._record(security_id, ticker, session)
            rec["eligible_sessions"] += 1
            rec["required_for_strategy_certificate"] = True
            rec["authority_requirements"].update({"identity", "security_type", "price_volume", "corporate_actions"})
            rec["touch_reasons"].add("ELIGIBLE_RANKING_INPUT")
            eligible_ids.append(security_id)

        for tid0 in pool:
            tid = int(tid0)
            security_id = _sid(sid, tid)
            rec = self._record(security_id, _ticker(tick, tid), session)
            rec["momentum_pool_sessions"] += 1
            rec["required_for_strategy_certificate"] = True
            rec["touch_reasons"].add("ESTABLISHED_LEADERSHIP_POOL")
            pool_ids.append(security_id)

        for rank, tid0 in enumerate(durable, start=1):
            tid = int(tid0)
            security_id = _sid(sid, tid)
            rec = self._record(security_id, _ticker(tick, tid), session)
            rec["durable_ranked_sessions"] += 1
            rec["required_for_strategy_certificate"] = True
            rec["touch_reasons"].add("DURABLE_RANK")
            best = rec["best_durable_rank"]
            rec["best_durable_rank"] = rank if best is None else min(int(best), rank)
            durable_ids.append(security_id)

        for tid0 in recsel:
            tid = int(tid0)
            security_id = _sid(sid, tid)
            rec = self._record(security_id, _ticker(tick, tid), session)
            rec["recent_leadership_sessions"] += 1
            rec["required_for_strategy_certificate"] = True
            rec["touch_reasons"].add("RECENT_LEADERSHIP")
            recent_ids.append(security_id)

        for slot in book.slots:
            if slot.reserved():
                tid = int(slot.pending_tid)
                security_id = _sid(sid, tid)
                rec = self._record(security_id, _ticker(tick, tid), session)
                rec["pending_sessions"] += 1
                rec["required_for_strategy_certificate"] = True
                rec["authority_requirements"].update({"identity", "security_type", "price_volume", "corporate_actions", "execution_open"})
                rec["touch_reasons"].add("PENDING_ORDER")
                pending_ids.append(security_id)
            if slot.held():
                tid = int(slot.tid)
                security_id = _sid(sid, tid)
                rec = self._record(security_id, _ticker(tick, tid), session)
                rec["held_sessions"] += 1
                rec["required_for_strategy_certificate"] = True
                rec["authority_requirements"].update({"identity", "security_type", "price_volume", "corporate_actions", "terminal"})
                rec["touch_reasons"].add("HELD_POSITION")
                held_ids.append(security_id)

        live_set = set(
            base_common + base_non_common + base_unknown + eligible_ids + pool_ids
            + durable_ids + recent_ids + pending_ids + held_ids
        )
        for security_id, event in sorted((terminal_events or {}).items()):
            security_id = str(security_id)
            if security_id not in live_set:
                continue
            self.note_terminal_touch(
                session, security_id, event, reason="TERMINAL_EVENT_ON_STRATEGY_PATH"
            )
            terminal_ids.append(security_id)

        payload = {
            "session": session,
            "base_candidate_known_common": sorted(base_common),
            "base_candidate_known_non_common": sorted(base_non_common),
            "base_candidate_unknown": sorted(base_unknown),
            "eligible": sorted(set(eligible_ids)),
            "established_pool": sorted(set(pool_ids)),
            "durable_ranked": durable_ids,
            "recent_leadership": sorted(set(recent_ids)),
            "pending": sorted(set(pending_ids)),
            "held": sorted(set(held_ids)),
            "terminal_events": sorted(set(terminal_ids)),
        }
        payload["set_sha256"] = {
            key: _set_hash(value)
            for key, value in payload.items()
            if key != "session" and isinstance(value, list)
        }
        self._session_handle.write(json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n")

    def _rows(self):
        for security_id in sorted(self.records):
            rec = self.records[security_id]
            yield {
                "security_id": rec["security_id"],
                "ticker": rec["ticker"],
                "first_touch_session": rec["first_touch_session"],
                "last_touch_session": rec["last_touch_session"],
                "required_lookback_sessions": REQUIRED_LOOKBACK_SESSIONS,
                "base_candidate_sessions": rec["base_candidate_sessions"],
                "known_common_base_sessions": rec["known_common_base_sessions"],
                "known_non_common_base_sessions": rec["known_non_common_base_sessions"],
                "unknown_type_base_sessions": rec["unknown_type_base_sessions"],
                "eligible_sessions": rec["eligible_sessions"],
                "momentum_pool_sessions": rec["momentum_pool_sessions"],
                "durable_ranked_sessions": rec["durable_ranked_sessions"],
                "recent_leadership_sessions": rec["recent_leadership_sessions"],
                "pending_sessions": rec["pending_sessions"],
                "held_sessions": rec["held_sessions"],
                "terminal_sessions": rec["terminal_sessions"],
                "incomplete_terminal_sessions": rec["incomplete_terminal_sessions"],
                "best_durable_rank": "" if rec["best_durable_rank"] is None else rec["best_durable_rank"],
                "potential_displacer": bool(rec["potential_displacer"]),
                "required_for_strategy_certificate": bool(rec["required_for_strategy_certificate"]),
                "authority_requirements": ";".join(sorted(rec["authority_requirements"])),
                "touch_reasons": ";".join(sorted(rec["touch_reasons"])),
            }

    def close(self):
        if self._closed:
            return
        self._closed = True
        self._session_handle.flush()
        self._event_handle.flush()
        self._session_handle.close()
        self._event_handle.close()

        rows = list(self._rows())
        fieldnames = list(rows[0].keys()) if rows else [
            "security_id", "ticker", "first_touch_session", "last_touch_session",
            "required_lookback_sessions", "base_candidate_sessions",
            "known_common_base_sessions", "known_non_common_base_sessions",
            "unknown_type_base_sessions", "eligible_sessions",
            "momentum_pool_sessions", "durable_ranked_sessions",
            "recent_leadership_sessions", "pending_sessions", "held_sessions",
            "terminal_sessions", "incomplete_terminal_sessions", "best_durable_rank",
            "potential_displacer", "required_for_strategy_certificate",
            "authority_requirements", "touch_reasons",
        ]
        worklist = self.output / "strategy-path-worklist.csv"
        with worklist.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)

        envelope = [
            row for row in rows
            if row["required_for_strategy_certificate"] or row["potential_displacer"]
        ]
        envelope_path = self.output / "candidate-envelope-worklist.csv"
        with envelope_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(envelope)

        counts = Counter()
        for row in rows:
            if row["base_candidate_sessions"]:
                counts["securities_touching_base_candidate"] += 1
            if row["unknown_type_base_sessions"]:
                counts["unknown_type_potential_displacers"] += 1
            if row["eligible_sessions"]:
                counts["eligible_ranking_inputs"] += 1
            if row["durable_ranked_sessions"]:
                counts["durable_ranked"] += 1
            if row["recent_leadership_sessions"]:
                counts["recent_leadership"] += 1
            if row["pending_sessions"]:
                counts["pending"] += 1
            if row["held_sessions"]:
                counts["held"] += 1
            if row["incomplete_terminal_sessions"]:
                counts["incomplete_terminal"] += 1
            if row["required_for_strategy_certificate"]:
                counts["required_for_strategy_certificate"] += 1

        manifest = {
            "schema": "backtester.research-champion-strategy-path-closure/1",
            "profile": PROFILE,
            "profile_sha256": PROFILE_SHA256,
            "runtime_main_sha": RUNTIME_MAIN_SHA,
            "first_session": self.first_session,
            "last_session": self.last_session,
            "session_count": self.session_count,
            "required_lookback_sessions": REQUIRED_LOOKBACK_SESSIONS,
            "counts": dict(sorted(counts.items())),
            "event_counts": dict(sorted(self.event_counts.items())),
            "candidate_envelope_contract": {
                "base_boundary": "all rows passing price/volume/history/signal prerequisites before security-type classification",
                "unknown_policy": "every unknown-type base candidate is a potential displacer and requires PIT resolution",
                "ranking_inputs": "every actually eligible security is retained because it contributes to cross-sectional rank geometry",
                "economic_path": "leadership, pending, held, and terminal touches are always retained",
                "certification_scope": "exact frozen Research Champion only; not a generic broad-universe certificate",
            },
            "files": {},
        }
        for path in (
            self.output / "strategy-path-session-ledger.jsonl.gz",
            self.output / "strategy-path-events.jsonl.gz",
            worklist,
            envelope_path,
        ):
            manifest["files"][path.name] = {
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "bytes": path.stat().st_size,
            }
        manifest_path = self.output / "strategy-path-manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


__all__ = [
    "PathAudit",
    "production_leadership_return",
    "PROFILE",
    "PROFILE_SHA256",
    "RUNTIME_MAIN_SHA",
    "REQUIRED_LOOKBACK_SESSIONS",
]
