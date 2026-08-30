#!/usr/bin/env python3
"""Fail-closed runtime primitives for retained-research causal certification.

The canonical artifact is always validated in full before a test view is
constructed. Prefix and poisoned-future views mutate only the in-memory read
surface presented to the retained replay; they never modify the immutable
canonical package on disk.
"""
from __future__ import annotations

import bisect
from collections import defaultdict
import gzip
import hashlib
import json
import math
import os
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping

import numpy as np
import pandas as pd

from backtester.canonical_pit_dataset import CanonicalPITDataset


TRACE_SCHEMA = "backtester.research-causal-trace/1"
RUNTIME_REPORT_SCHEMA = "backtester.research-causal-runtime-report/1"
POISON_SCHEMA = "backtester.research-future-poison/1"
TERMINAL_ACTIONS = {
    "acquisitionby",
    "mergerto",
    "voluntarydelisting",
    "regulatorydelisting",
    "bankruptcyliquidation",
    "delisted",
}


class CausalAccessError(RuntimeError):
    """Raised on any access or timing operation that can observe the future."""


def _date_text(value: Any) -> str:
    if isinstance(value, str):
        return value[:10]
    return str(pd.Timestamp(value).date())


def canonical_float(value: Any) -> str | None:
    """Return an exact, JSON-safe representation of a numeric value."""
    if value is None or value is pd.NA:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(number):
        return "NaN"
    if math.isinf(number):
        return "+Infinity" if number > 0 else "-Infinity"
    return number.hex()


def canonicalize(value: Any) -> Any:
    """Normalize nested replay state into deterministic JSON values."""
    if value is None or value is pd.NA:
        return None
    if isinstance(value, (pd.Timestamp, np.datetime64)):
        return _date_text(value)
    if isinstance(value, (np.bool_, bool)):
        return bool(value)
    if isinstance(value, (np.integer, int)) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, (np.floating, float)):
        return canonical_float(value)
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, str):
        return value
    if isinstance(value, Mapping):
        return {
            str(key): canonicalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [canonicalize(item) for item in value]
    if isinstance(value, (set, frozenset)):
        items = [canonicalize(item) for item in value]
        return sorted(
            items,
            key=lambda item: json.dumps(item, sort_keys=True, separators=(",", ":")),
        )
    if isinstance(value, np.ndarray):
        return [canonicalize(item) for item in value.tolist()]
    if hasattr(value, "__dict__"):
        return canonicalize(vars(value))
    return str(value)


def canonical_json(value: Any) -> str:
    return json.dumps(
        canonicalize(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _same_float(left: Any, right: Any) -> bool:
    return canonical_float(left) == canonical_float(right)


def _seed_word(seed: int, label: str) -> np.uint64:
    digest = hashlib.sha256(f"{int(seed)}|{label}".encode("utf-8")).digest()
    return np.uint64(int.from_bytes(digest[:8], "big", signed=False))


def _row_hash(frame: pd.DataFrame, seed: int, label: str) -> np.ndarray:
    columns = [
        name
        for name in ("session", "effective_session", "security_id", "ticker")
        if name in frame.columns
    ]
    if not columns:
        payload = pd.Series(np.arange(len(frame), dtype=np.int64), index=frame.index)
    else:
        payload = frame[columns].astype(str)
    hashed = pd.util.hash_pandas_object(payload, index=False).to_numpy(
        dtype=np.uint64,
        copy=False,
    )
    return hashed ^ _seed_word(seed, label)


class CausalSessionGuard:
    """Own the chronological session clock and reject future-dated access."""

    def __init__(self, sessions: Iterable[str], *, mode: str, cutoff: str | None):
        ordered = tuple(str(session) for session in sessions)
        if not ordered:
            raise CausalAccessError("causal runtime has no sessions")
        if tuple(sorted(set(ordered))) != ordered:
            raise CausalAccessError(
                "causal runtime sessions are not strictly ordered and unique"
            )
        self.sessions = ordered
        self.mode = str(mode)
        self.cutoff = None if cutoff is None else str(cutoff)
        self.index_by_session = {
            session: index for index, session in enumerate(ordered)
        }
        self.active_session: str | None = None
        self.active_index = -1
        self.counters: defaultdict[str, int] = defaultdict(int)
        self.last_access: dict[str, str] = {}

    def _violation(self, domain: str, detail: str) -> None:
        self.counters["violations"] += 1
        raise CausalAccessError(
            f"causal access violation domain={domain} active={self.active_session} "
            f"index={self.active_index}: {detail}"
        )

    def begin(self, session: Any, chronological_index: int) -> None:
        current = _date_text(session)
        expected_index = self.active_index + 1
        if int(chronological_index) != expected_index:
            self._violation(
                "session_clock",
                f"chronological index {chronological_index} != expected {expected_index}",
            )
        if expected_index >= len(self.sessions):
            self._violation("session_clock", f"unexpected extra session {current}")
        expected_session = self.sessions[expected_index]
        if current != expected_session:
            self._violation(
                "session_clock",
                f"session {current} != expected canonical session {expected_session}",
            )
        self.active_index = expected_index
        self.active_session = current
        self.counters["sessions_begun"] += 1
        self.last_access["session_clock"] = current

    def _require_active(self, domain: str) -> tuple[str, int]:
        if self.active_session is None or self.active_index < 0:
            self._violation(
                domain,
                "strategy access occurred before a session was active",
            )
        return self.active_session, self.active_index

    def assert_observation_group(
        self,
        frame: pd.DataFrame,
        session: Any,
    ) -> None:
        active, _ = self._require_active("market_observations")
        requested = _date_text(session)
        if requested != active:
            self._violation(
                "market_observations",
                f"observation group requested for {requested}",
            )
        column = "date" if "date" in frame.columns else "session"
        observed = {
            _date_text(value)
            for value in frame[column].dropna().unique().tolist()
        }
        if observed != {active}:
            self._violation(
                "market_observations",
                f"group contains sessions {sorted(observed)}",
            )
        self.counters["observation_groups"] += 1
        self.last_access["market_observations"] = active

    def assert_asof(
        self,
        *,
        domain: str,
        requested_session: Any,
        source_session: Any | None,
        require_current_request: bool = True,
    ) -> None:
        active, _ = self._require_active(domain)
        requested = _date_text(requested_session)
        if require_current_request and requested != active:
            self._violation(
                domain,
                f"request session {requested} is not active session",
            )
        if requested > active:
            self._violation(domain, f"request session {requested} is in the future")
        if source_session is not None:
            source = _date_text(source_session)
            if source > requested or source > active:
                self._violation(
                    domain,
                    f"source session {source} exceeds request {requested}",
                )
            self.last_access[domain] = source
        else:
            self.last_access[domain] = requested
        self.counters[f"{domain}_accesses"] += 1

    def assert_rolling(
        self,
        label: str,
        chronological_index: int,
        source_indices: Iterable[int],
    ) -> None:
        _, active_index = self._require_active("rolling_signals")
        current = int(chronological_index)
        if current != active_index:
            self._violation(
                "rolling_signals",
                f"{label} current index {current} != active {active_index}",
            )
        indices = tuple(
            int(index) for index in source_indices if int(index) >= 0
        )
        if indices and max(indices) > active_index:
            self._violation(
                "rolling_signals",
                f"{label} source index {max(indices)} exceeds active {active_index}",
            )
        self.counters["rolling_assertions"] += 1
        self.last_access["rolling_signals"] = self.active_session or ""

    def assert_benchmark_cache(
        self,
        frame: pd.DataFrame,
        session: Any,
    ) -> None:
        active, _ = self._require_active("benchmark")
        requested = _date_text(session)
        if requested != active:
            self._violation("benchmark", f"benchmark request for {requested}")
        timestamp = pd.Timestamp(active)
        if timestamp not in frame.index:
            self._violation("benchmark", f"benchmark row missing for {active}")
        prefix = frame.loc[:timestamp, "closeadj"].astype(float)
        returns = prefix.pct_change()
        recomputed_r20 = prefix.pct_change(20).iloc[-1]
        recomputed_volacc = (
            returns.rolling(5).std(ddof=1)
            / returns.rolling(20).std(ddof=1)
            - 1.0
        ).iloc[-1]
        observed_r20 = frame.loc[timestamp, "r20"]
        observed_volacc = frame.loc[timestamp, "volacc"]
        if not _same_float(recomputed_r20, observed_r20):
            self._violation(
                "benchmark",
                f"cached r20 differs from prefix recomputation on {active}",
            )
        if not _same_float(recomputed_volacc, observed_volacc):
            self._violation(
                "benchmark",
                f"cached volacc differs from prefix recomputation on {active}",
            )
        self.counters["benchmark_cache_assertions"] += 1
        self.last_access["benchmark"] = active

    def assert_cash(
        self,
        session: Any,
        previous_session: Any | None,
    ) -> None:
        active, _ = self._require_active("cash")
        requested = _date_text(session)
        if requested != active:
            self._violation("cash", f"cash factor request for {requested}")
        if (
            previous_session is not None
            and _date_text(previous_session) >= requested
        ):
            self._violation(
                "cash",
                f"previous cash session {_date_text(previous_session)} "
                f"is not earlier than {requested}",
            )
        self.counters["cash_accesses"] += 1
        self.last_access["cash"] = requested

    def assert_fill_after_signal(
        self,
        *,
        kind: str,
        signal_index: int,
        fill_index: int,
        security_id: str,
    ) -> None:
        self._require_active("execution")
        if int(fill_index) <= int(signal_index):
            self._violation(
                "execution",
                f"{kind} fill for {security_id} index={fill_index} "
                f"not later than close signal index={signal_index}",
            )
        self.counters["next_open_fill_assertions"] += 1
        self.last_access["execution"] = self.active_session or ""

    def assert_entry_basis(
        self,
        *,
        security_id: str,
        adjusted_execution_open: Any,
        review_basis: Any,
    ) -> None:
        self._require_active("entry_basis")
        if not _same_float(adjusted_execution_open, review_basis):
            self._violation(
                "entry_basis",
                f"{security_id} basis={canonical_float(review_basis)} "
                f"execution_open={canonical_float(adjusted_execution_open)}",
            )
        self.counters["entry_basis_assertions"] += 1
        self.last_access["entry_basis"] = self.active_session or ""

    def assert_position_age(
        self,
        *,
        security_id: str,
        entry_index: int,
        current_index: int,
        observed_age: int,
    ) -> None:
        self._require_active("position_age")
        expected = int(current_index) - int(entry_index)
        if int(observed_age) != expected:
            self._violation(
                "position_age",
                f"{security_id} age={observed_age} expected={expected}",
            )
        self.counters["position_age_assertions"] += 1
        self.last_access["position_age"] = self.active_session or ""

    def assert_event(self, *, domain: str, event_session: Any) -> None:
        active, _ = self._require_active(domain)
        effective = _date_text(event_session)
        if effective != active:
            self._violation(
                domain,
                f"event effective {effective} during {active}",
            )
        self.counters[f"{domain}_event_assertions"] += 1
        self.last_access[domain] = effective

    def assert_allocation_application(
        self,
        *,
        signal_index: int,
        application_index: int,
    ) -> None:
        self._require_active("allocation")
        if (
            int(signal_index) >= 0
            and int(application_index) <= int(signal_index)
        ):
            self._violation(
                "allocation",
                f"allocation applied index={application_index} "
                f"from close index={signal_index}",
            )
        self.counters["allocation_timing_assertions"] += 1
        self.last_access["allocation"] = self.active_session or ""

    def snapshot(self) -> dict[str, Any]:
        return {
            "active_session": self.active_session,
            "active_index": self.active_index,
            "counters": dict(sorted(self.counters.items())),
            "last_access": dict(sorted(self.last_access.items())),
        }

    def report(self) -> dict[str, Any]:
        completed = self.active_index == len(self.sessions) - 1
        return {
            "schema": RUNTIME_REPORT_SCHEMA,
            "status": (
                "PASS"
                if completed and int(self.counters.get("violations", 0)) == 0
                else "FAIL"
            ),
            "mode": self.mode,
            "cutoff": self.cutoff,
            "expected_sessions": len(self.sessions),
            "completed_sessions": self.active_index + 1,
            "completed_chronologically": completed,
            **self.snapshot(),
        }


class GuardedSessionMap(Mapping[Any, Any]):
    """A mapping whose strategy-time reads are restricted to the active date."""

    def __init__(
        self,
        guard: CausalSessionGuard,
        domain: str,
        values: Mapping[Any, Any] | None = None,
    ):
        self.guard = guard
        self.domain = str(domain)
        self._values: dict[Any, Any] = dict(values or {})

    def __getitem__(self, key: Any) -> Any:
        self.guard.assert_asof(
            domain=self.domain,
            requested_session=key,
            source_session=key,
            require_current_request=True,
        )
        return self._values[key]

    def get(self, key: Any, default: Any = None) -> Any:
        self.guard.assert_asof(
            domain=self.domain,
            requested_session=key,
            source_session=key,
            require_current_request=True,
        )
        return self._values.get(key, default)

    def __iter__(self) -> Iterator[Any]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def setdefault(self, key: Any, default: Any) -> Any:
        return self._values.setdefault(key, default)


class CausalPITDataset(CanonicalPITDataset):
    """Validated canonical dataset with baseline, prefix, or poisoned read views."""

    def __init__(
        self,
        root: Path,
        *,
        expected_start: str | None = None,
        expected_end: str | None = None,
        require_pass: bool = True,
    ):
        self.mode = os.environ.get(
            "CAUSAL_DATASET_MODE",
            "baseline",
        ).strip().lower()
        if self.mode not in {"baseline", "prefix", "poison"}:
            raise CausalAccessError(
                f"unsupported causal dataset mode: {self.mode!r}"
            )
        cutoff = os.environ.get("CAUSAL_CUTOFF")
        self.cutoff = None if not cutoff else str(cutoff)[:10]
        self.poison_seed = int(
            os.environ.get("CAUSAL_POISON_SEED", "314159")
        )

        # Validate the full immutable package first. A prefix end is a view end,
        # not the manifest's immutable coverage end.
        super().__init__(
            root,
            expected_start=expected_start,
            expected_end=None,
            require_pass=require_pass,
        )
        immutable_end = str(
            (self.manifest.get("window") or {}).get("end")
        )
        if self.mode in {"baseline", "poison"}:
            if expected_end is not None and str(expected_end) != immutable_end:
                raise CausalAccessError(
                    f"full causal view end {expected_end} "
                    f"!= immutable end {immutable_end}"
                )
        else:
            if self.cutoff is None:
                raise CausalAccessError(
                    "prefix mode requires CAUSAL_CUTOFF"
                )
            if expected_end is not None and str(expected_end) != self.cutoff:
                raise CausalAccessError(
                    f"prefix declared end {expected_end} != cutoff {self.cutoff}"
                )
        if self.mode == "poison" and self.cutoff is None:
            raise CausalAccessError("poison mode requires CAUSAL_CUTOFF")

        self._immutable_sessions = tuple(self.sessions)
        if (
            self.cutoff is not None
            and self.cutoff not in self._immutable_sessions
        ):
            raise CausalAccessError(
                f"cutoff is not a canonical session: {self.cutoff}"
            )

        if self.mode == "prefix":
            self.sessions = tuple(
                session
                for session in self._immutable_sessions
                if session <= str(self.cutoff)
            )
            self.session_hashes = {
                session: digest
                for session, digest in self.session_hashes.items()
                if session <= str(self.cutoff)
            }
            self._restrict_timeline(str(self.cutoff))
        elif self.mode == "poison":
            self._poison_timeline(self.cutoff or immutable_end)

        self.guard = CausalSessionGuard(
            self.sessions,
            mode=self.mode,
            cutoff=self.cutoff,
        )
        self._poison_counts: defaultdict[str, int] = defaultdict(int)

    def _replace_timeline(
        self,
        rows_by_sid: Mapping[str, list[dict[str, str]]],
    ) -> None:
        self._timeline_rows = defaultdict(list)
        self._timeline_dates = defaultdict(list)
        for sid, rows in rows_by_sid.items():
            ordered = sorted(
                rows,
                key=lambda row: str(row["effective_session"]),
            )
            if not ordered:
                continue
            self._timeline_rows[str(sid)].extend(ordered)
            self._timeline_dates[str(sid)].extend(
                str(row["effective_session"]) for row in ordered
            )
        self._first_session = {
            sid: rows[0]["effective_session"]
            for sid, rows in self._timeline_rows.items()
        }

    def _restrict_timeline(self, cutoff: str) -> None:
        restricted: dict[str, list[dict[str, str]]] = {}
        for sid, rows in self._timeline_rows.items():
            kept = [
                dict(row)
                for row in rows
                if str(row["effective_session"]) <= cutoff
            ]
            if kept:
                restricted[str(sid)] = kept
        self._replace_timeline(restricted)

    def _poison_timeline(self, cutoff: str) -> None:
        poisoned: dict[str, list[dict[str, str]]] = {}
        changed = 0
        for sid, rows in self._timeline_rows.items():
            target: list[dict[str, str]] = []
            for row in rows:
                item = dict(row)
                effective = str(item["effective_session"])
                if effective > cutoff:
                    word = int.from_bytes(
                        hashlib.sha256(
                            f"{self.poison_seed}|metadata|{sid}|{effective}".encode(
                                "utf-8"
                            )
                        ).digest()[:8],
                        "big",
                    )
                    common = bool(word & 1)
                    item["issuer_id"] = f"POISON_ISSUER:{word:016x}"
                    item["issuer_source"] = "FUTURE_POISON"
                    item["security_type"] = (
                        "common" if common else "non_common"
                    )
                    item["security_type_source"] = "FUTURE_POISON"
                    item["security_type_eligible"] = (
                        "True" if common else "False"
                    )
                    item["sic"] = str(1000 + word % 8999)
                    item["ff12"] = f"POISON_FF12_{word % 12:02d}"
                    item["sector_source"] = "FUTURE_POISON"
                    item["metadata_admitted"] = (
                        "True" if word & 2 else "False"
                    )
                    changed += 1
                target.append(item)
            poisoned[str(sid)] = target
        self._replace_timeline(poisoned)
        self._timeline_poison_count = changed

    def metadata_for(
        self,
        security_id: str,
        session: str,
    ) -> dict[str, str] | None:
        request = str(session)[:10]
        if (
            hasattr(self, "guard")
            and self.guard.active_session is not None
        ):
            sid = str(security_id)
            dates = self._timeline_dates.get(sid, ())
            index = bisect.bisect_right(dates, request) - 1
            source = None if index < 0 else dates[index]
            self.guard.assert_asof(
                domain="metadata",
                requested_session=request,
                source_session=source,
                require_current_request=True,
            )
        if (
            self.mode == "prefix"
            and self.cutoff is not None
            and request > self.cutoff
        ):
            raise CausalAccessError(
                f"prefix metadata request {request} "
                f"exceeds cutoff {self.cutoff}"
            )
        row = super().metadata_for(str(security_id), request)
        if (
            row is not None
            and str(row["effective_session"]) > request
        ):
            raise CausalAccessError(
                "metadata as-of lookup returned a future row"
            )
        return row

    def observations(self, year: int) -> pd.DataFrame:
        frame = super().observations(year)
        frame["session"] = frame["session"].astype(str)
        if self.mode == "prefix":
            frame = frame[
                frame["session"] <= str(self.cutoff)
            ].copy()
        elif self.mode == "poison":
            frame = self._poison_observations(frame)
        return frame

    def _poison_observations(
        self,
        frame: pd.DataFrame,
    ) -> pd.DataFrame:
        mask = frame["session"].astype(str) > str(self.cutoff)
        count = int(mask.sum())
        if not count:
            return frame
        result = frame.copy()
        future = result.loc[mask]
        words = _row_hash(
            future,
            self.poison_seed,
            "observations",
        )
        unit_a = (
            (words % np.uint64(1_000_003)).astype(np.float64)
            / 1_000_003.0
        )
        unit_b = (
            ((words >> np.uint64(21)) % np.uint64(1_000_033)).astype(
                np.float64
            )
            / 1_000_033.0
        )
        unit_c = (
            ((words >> np.uint64(42)) % np.uint64(1_000_037)).astype(
                np.float64
            )
            / 1_000_037.0
        )

        raw_close = pd.to_numeric(
            future["raw_close"],
            errors="coerce",
        ).to_numpy(float)
        raw_close = np.where(np.isfinite(raw_close), raw_close, 1.0)
        raw_open = pd.to_numeric(
            future["raw_open"],
            errors="coerce",
        ).to_numpy(float)
        raw_open = np.where(np.isfinite(raw_open), raw_open, raw_close)
        signal_close = pd.to_numeric(
            future["signal_close"],
            errors="coerce",
        ).to_numpy(float)
        signal_close = np.where(
            np.isfinite(signal_close),
            signal_close,
            raw_close,
        )
        reported_volume = pd.to_numeric(
            future["reported_volume"],
            errors="coerce",
        ).to_numpy(float)
        reported_volume = np.where(
            np.isfinite(reported_volume),
            reported_volume,
            1.0,
        )
        raw_volume = pd.to_numeric(
            future["raw_compatible_volume"],
            errors="coerce",
        ).to_numpy(float)
        raw_volume = np.where(
            np.isfinite(raw_volume),
            raw_volume,
            reported_volume,
        )

        result.loc[mask, "raw_close"] = np.maximum(
            0.01,
            np.abs(raw_close) * (0.20 + 4.80 * unit_a),
        )
        result.loc[mask, "raw_open"] = np.maximum(
            0.01,
            np.abs(raw_open) * (0.25 + 3.75 * unit_b),
        )
        result.loc[mask, "signal_close"] = np.maximum(
            0.01,
            np.abs(signal_close) * (0.30 + 3.20 * unit_c),
        )
        result.loc[mask, "reported_volume"] = np.maximum(
            1.0,
            np.abs(reported_volume) * (0.05 + 8.0 * unit_b),
        )
        result.loc[mask, "raw_compatible_volume"] = np.maximum(
            1.0,
            np.abs(raw_volume) * (0.05 + 8.0 * unit_c),
        )

        original_split = pd.to_numeric(
            future["split_ratio"],
            errors="coerce",
        ).fillna(1.0).to_numpy(float)
        changed_split = np.where(
            np.abs(original_split - 1.0) > 1e-12,
            np.where(original_split >= 1.0, 0.5, 2.0),
            1.0,
        )
        result.loc[mask, "split_ratio"] = changed_split
        original_dividend = pd.to_numeric(
            future["dividend_per_share"],
            errors="coerce",
        ).fillna(0.0).to_numpy(float)
        result.loc[mask, "dividend_per_share"] = np.where(
            original_dividend > 0.0,
            original_dividend * (1.25 + unit_a) + 0.0001,
            0.0,
        )

        common = (words & np.uint64(1)) == 1
        result.loc[mask, "issuer_id"] = [
            f"POISON_ISSUER:{int(word):016x}" for word in words
        ]
        result.loc[mask, "issuer_source"] = "FUTURE_POISON"
        result.loc[mask, "security_type"] = np.where(
            common,
            "common",
            "non_common",
        )
        result.loc[mask, "security_type_source"] = "FUTURE_POISON"
        result.loc[mask, "security_type_eligible"] = common
        result.loc[mask, "sic"] = (
            1000 + (words % np.uint64(8999))
        ).astype(str)
        result.loc[mask, "ff12"] = [
            f"POISON_FF12_{int(word % np.uint64(12)):02d}"
            for word in words
        ]
        result.loc[mask, "sector_source"] = "FUTURE_POISON"
        result.loc[mask, "listing_active"] = (
            words & np.uint64(2)
        ) == 2
        result.loc[mask, "tradeable"] = (
            words & np.uint64(4)
        ) == 4
        result.loc[mask, "metadata_admitted"] = (
            words & np.uint64(8)
        ) == 8
        result.loc[mask, "identity_source"] = "FUTURE_POISON"
        self._poison_counts["observation_rows"] += count
        self._poison_counts["price_rows"] += count
        self._poison_counts["volume_rows"] += count
        self._poison_counts["eligibility_rows"] += count
        self._poison_counts["metadata_observation_rows"] += count
        self._poison_counts["observation_split_rows"] += int(
            np.count_nonzero(np.abs(original_split - 1.0) > 1e-12)
        )
        self._poison_counts["observation_dividend_rows"] += int(
            np.count_nonzero(original_dividend > 0.0)
        )
        return result

    def actions_frame(self) -> pd.DataFrame:
        frame = pd.read_csv(
            self.root / "actions.csv.gz",
            compression="gzip",
            dtype=str,
            keep_default_na=False,
        )
        frame["effective_session"] = frame[
            "effective_session"
        ].astype(str)
        if self.mode == "prefix":
            return frame[
                frame["effective_session"] <= str(self.cutoff)
            ].copy()
        if self.mode != "poison":
            return frame
        mask = frame["effective_session"] > str(self.cutoff)
        if not int(mask.sum()):
            return frame
        result = frame.copy()
        future = result.loc[mask]
        words = _row_hash(future, self.poison_seed, "actions")
        for column in (
            "vendor_value",
            "canonical_value",
            "sep_derived_value",
        ):
            numeric = pd.to_numeric(
                future[column],
                errors="coerce",
            ).to_numpy(float)
            replacement = np.where(
                np.isfinite(numeric),
                np.abs(numeric)
                * (
                    1.1
                    + (words % np.uint64(997)).astype(float) / 997.0
                )
                + 0.0001,
                1.0
                + (words % np.uint64(5)).astype(float) * 0.25,
            )
            result.loc[mask, column] = [
                format(float(value), ".17g") for value in replacement
            ]
        result.loc[mask, "authority"] = "FUTURE_POISON"
        result.loc[mask, "known_by"] = result.loc[
            mask,
            "effective_session",
        ]
        result.loc[mask, "evidence_hash"] = [
            hashlib.sha256(
                f"poison-action|{self.poison_seed}|{int(word)}".encode()
            ).hexdigest()
            for word in words
        ]
        self._poison_counts["action_rows"] += int(mask.sum())
        self._poison_counts["terminal_action_rows"] += int(
            result.loc[mask, "action"]
            .astype(str)
            .str.lower()
            .isin(TERMINAL_ACTIONS)
            .sum()
        )
        return result

    def terminal_frame(self) -> pd.DataFrame:
        frame = pd.read_csv(
            self.root / "terminal-events.csv.gz",
            compression="gzip",
            dtype=str,
            keep_default_na=False,
        )
        frame["effective_session"] = frame[
            "effective_session"
        ].astype(str)
        if self.mode == "prefix":
            return frame[
                frame["effective_session"] <= str(self.cutoff)
            ].copy()
        if self.mode != "poison":
            return frame
        mask = frame["effective_session"] > str(self.cutoff)
        if not int(mask.sum()):
            return frame
        result = frame.copy()
        future = result.loc[mask]
        words = _row_hash(future, self.poison_seed, "terminal")
        for column in (
            "cash_per_share",
            "exchange_ratio",
            "cash_in_lieu_price_per_delivered_share",
        ):
            result.loc[mask, column] = [
                format(
                    0.01
                    + float(word % np.uint64(100_000)) / 1000.0,
                    ".17g",
                )
                for word in words
            ]
        result.loc[mask, "disposition"] = "FUTURE_POISON"
        result.loc[mask, "authority"] = "FUTURE_POISON"
        result.loc[mask, "reference"] = [
            f"FUTURE_POISON:{self.poison_seed}:{int(word):016x}"
            for word in words
        ]
        result.loc[mask, "evidence_hash"] = [
            hashlib.sha256(
                f"poison-terminal|{self.poison_seed}|{int(word)}".encode()
            ).hexdigest()
            for word in words
        ]
        self._poison_counts["terminal_rows"] += int(mask.sum())
        return result

    def benchmark(self) -> tuple[dict[str, float], dict[str, float]]:
        frame = pd.read_csv(
            self.root / "benchmark.csv.gz",
            compression="gzip",
        )
        frame["session"] = frame["session"].astype(str)
        if self.mode == "prefix":
            frame = frame[
                frame["session"] <= str(self.cutoff)
            ].copy()
        elif self.mode == "poison":
            mask = frame["session"] > str(self.cutoff)
            count = int(mask.sum())
            if count:
                future = frame.loc[mask]
                words = _row_hash(
                    future,
                    self.poison_seed,
                    "benchmark",
                )
                factors = (
                    0.80
                    + (words % np.uint64(400_001)).astype(float)
                    / 1_000_000.0
                )
                frame.loc[mask, "close_to_close_factor"] = factors
                prior_rows = frame[
                    frame["session"] <= str(self.cutoff)
                ]
                level = float(prior_rows.iloc[-1]["level"])
                levels: list[float] = []
                for factor in factors:
                    level *= float(factor)
                    levels.append(level)
                frame.loc[mask, "level"] = levels
                self._poison_counts["benchmark_rows"] += count
        levels = {
            str(row.session): float(row.level)
            for row in frame.itertuples(index=False)
        }
        returns = {
            str(row.session): float(row.close_to_close_factor) - 1.0
            for row in frame.itertuples(index=False)
        }
        return levels, returns

    def cash_factors(self) -> dict[str, tuple[float, float]]:
        frame = pd.read_csv(
            self.root / "cash.csv.gz",
            compression="gzip",
        )
        frame["session"] = frame["session"].astype(str)
        if self.mode == "prefix":
            frame = frame[
                frame["session"] <= str(self.cutoff)
            ].copy()
        elif self.mode == "poison":
            mask = frame["session"] > str(self.cutoff)
            count = int(mask.sum())
            if count:
                future = frame.loc[mask]
                words = _row_hash(
                    future,
                    self.poison_seed,
                    "cash",
                )
                gap = (
                    0.998
                    + (words % np.uint64(4_001)).astype(float)
                    / 1_000_000.0
                )
                intra = (
                    0.998
                    + (
                        (words >> np.uint64(17))
                        % np.uint64(4_001)
                    ).astype(float)
                    / 1_000_000.0
                )
                frame.loc[mask, "gap_factor"] = gap
                frame.loc[mask, "intraday_factor"] = intra
                frame.loc[mask, "close_to_close_factor"] = gap * intra
                frame.loc[mask, "source"] = "FUTURE_POISON"
                self._poison_counts["cash_rows"] += count
        return {
            str(row.session): (
                float(row.gap_factor),
                float(row.intraday_factor),
            )
            for row in frame.itertuples(index=False)
        }

    def poison_manifest(self) -> dict[str, Any]:
        timeline_count = int(
            getattr(self, "_timeline_poison_count", 0)
        )
        counts = dict(sorted(self._poison_counts.items()))
        if timeline_count:
            counts["metadata_timeline_rows"] = timeline_count
        payload = {
            "schema": POISON_SCHEMA,
            "mode": self.mode,
            "cutoff": self.cutoff,
            "seed": self.poison_seed,
            "dataset_hash": self.dataset_hash,
            "changed_rows": counts,
        }
        payload["manifest_sha256"] = sha256_json(payload)
        return payload


class CausalTrace:
    """Write canonical per-session trace bytes and a runtime guard report."""

    def __init__(
        self,
        path: Path,
        guard: CausalSessionGuard,
        dataset: CausalPITDataset,
    ):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.guard = guard
        self.dataset = dataset
        self._raw = self.path.open("wb")
        self._gzip = gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=self._raw,
            compresslevel=6,
            mtime=0,
        )
        self._digest = hashlib.sha256()
        self.rows = 0
        self.closed = False

    def emit(self, record: Mapping[str, Any]) -> None:
        if self.closed:
            raise CausalAccessError("causal trace already closed")
        active = self.guard.active_session
        if active is None:
            raise CausalAccessError(
                "trace emission occurred outside an active session"
            )
        if _date_text(record.get("date")) != active:
            raise CausalAccessError(
                f"trace date {_date_text(record.get('date'))} "
                f"!= active {active}"
            )
        envelope = {
            "schema": TRACE_SCHEMA,
            "dataset_hash": self.dataset.dataset_hash,
            "record": dict(record),
            "guard": self.guard.snapshot(),
        }
        line = canonical_json(envelope).encode("utf-8") + b"\n"
        self._gzip.write(line)
        self._digest.update(line)
        self.rows += 1

    def close(self) -> dict[str, Any]:
        if self.closed:
            raise CausalAccessError("causal trace closed more than once")
        self._gzip.close()
        self._raw.close()
        self.closed = True
        report = self.guard.report()
        report.update(
            {
                "dataset_hash": self.dataset.dataset_hash,
                "dataset_id": self.dataset.manifest.get("dataset_id"),
                "trace_path": self.path.name,
                "trace_rows": self.rows,
                "trace_sha256": self._digest.hexdigest(),
                "poison": self.dataset.poison_manifest(),
            }
        )
        report_path = Path(
            os.environ.get(
                "CAUSAL_GUARD_REPORT_PATH",
                str(
                    self.path.with_name(
                        "runtime-guard-report.json"
                    )
                ),
            )
        )
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(
            json.dumps(report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return report
