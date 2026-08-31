#!/usr/bin/env python3
"""Compile a certified canonical PIT dataset into a fast research tape.

The tape is a derived, read-only artifact.  Feature construction is strictly
forward-only: each session is processed once in chronological order and every
stored feature uses only the current session and prior state.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np
import pandas as pd

from backtester.canonical_pit_dataset import CanonicalPITDataset


SCHEMA = "backtester.compiled-pit-research/1"
FEATURE_SPEC = {
    "session_order": "ascending canonical observation session",
    "identity_order": "ticker, listing_first_session, security_id",
    "price_domain": "canonical signal_close/raw_close/raw_open/reported_volume",
    "recent_return_sessions": 21,
    "momentum_from_sessions": 126,
    "momentum_skip_recent_sessions": 21,
    "volatility_long_sessions": 126,
    "volatility_excluded_recent_sessions": 21,
    "adv_sessions": 20,
    "held_breadth_return_sessions": 63,
    "continuity_min_valid_returns": 126,
    "causal_contract": "current session plus strictly prior state only; no backfill, centered windows, future normalization, or future metadata",
}
FEATURE_SPEC_HASH = hashlib.sha256(
    json.dumps(FEATURE_SPEC, sort_keys=True, separators=(",", ":")).encode("utf-8")
).hexdigest()
_REQUIRED_ARRAYS = (
    "session_ns", "offsets", "tid", "close", "closeunadj", "open", "volume",
    "dividend_per_share", "split_ratio", "recent", "mom", "r63", "score",
    "adv", "fvol", "day_dv", "continuous", "security_type_code",
)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _compiler_sha256() -> str:
    return _sha256(Path(__file__).resolve())


def _tape_hash(source_dataset_hash: str, compiler_sha256: str, members: dict) -> str:
    payload = {
        "schema": SCHEMA,
        "source_dataset_hash": source_dataset_hash,
        "compiler_sha256": compiler_sha256,
        "feature_spec_hash": FEATURE_SPEC_HASH,
        "members": {name: members[name]["sha256"] for name in sorted(members)},
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _identity_rows(dataset: CanonicalPITDataset) -> tuple[list[tuple[str, str, str]], dict[str, int]]:
    rows: list[tuple[str, str, str]] = []
    for sid, history in dataset._timeline_rows.items():
        first = history[0]
        rows.append((str(first["ticker"]), str(sid), str(first["listing_first_session"])))
    rows.sort(key=lambda row: (row[0], row[2], row[1]))
    return rows, {sid: index for index, (_, sid, _) in enumerate(rows)}


def _security_type_codes(values: pd.Series) -> np.ndarray:
    text = values.fillna("").astype(str).str.lower().to_numpy(object)
    out = np.full(len(text), -1, dtype=np.int8)
    out[text == "common"] = 1
    out[text == "non_common"] = 0
    return out


@dataclass
class _FeatureState:
    n: int

    def __post_init__(self) -> None:
        self.gday = -1
        self.close_ring = np.full((130, self.n), np.nan, np.float32)
        self.r126 = np.zeros((126, self.n), np.float32)
        self.rv126 = np.zeros((126, self.n), bool)
        self.s126 = np.zeros(self.n)
        self.q126 = np.zeros(self.n)
        self.c126 = np.zeros(self.n, np.int16)
        self.r21 = np.zeros((21, self.n), np.float32)
        self.rv21 = np.zeros((21, self.n), bool)
        self.s21 = np.zeros(self.n)
        self.q21 = np.zeros(self.n)
        self.c21 = np.zeros(self.n, np.int16)
        self.dvbuf = np.zeros((20, self.n), np.float32)
        self.dvsum = np.zeros(self.n)

    def step(self, tids: np.ndarray, close: np.ndarray, volume: np.ndarray) -> dict[str, np.ndarray]:
        self.gday += 1
        gday = self.gday
        c = np.asarray(close, dtype=float)
        vol = np.asarray(volume, dtype=float)
        dv = np.nan_to_num(c * vol, nan=0.0, posinf=0.0, neginf=0.0)

        lag21 = self.close_ring[(gday - 21) % 130, tids] if gday >= 21 else np.full(len(tids), np.nan)
        lag63 = self.close_ring[(gday - 63) % 130, tids] if gday >= 63 else np.full(len(tids), np.nan)
        lag126 = self.close_ring[(gday - 126) % 130, tids] if gday >= 126 else np.full(len(tids), np.nan)
        prev = self.close_ring[(gday - 1) % 130, tids] if gday >= 1 else np.full(len(tids), np.nan)

        recent = np.divide(
            c, lag21, out=np.full_like(c, np.nan), where=np.isfinite(lag21) & (lag21 > 0)
        ) - 1.0
        r63 = np.divide(
            c, lag63, out=np.full_like(c, np.nan), where=np.isfinite(lag63) & (lag63 > 0)
        ) - 1.0
        mom = np.divide(
            lag21, lag126, out=np.full_like(c, np.nan),
            where=np.isfinite(lag21) & np.isfinite(lag126) & (lag126 > 0),
        ) - 1.0
        lr = np.log(np.divide(
            c, prev, out=np.full_like(c, np.nan),
            where=np.isfinite(c) & (c > 0) & np.isfinite(prev) & (prev > 0),
        ))

        k = gday % 126
        old = self.r126[k]
        oldv = self.rv126[k]
        self.s126 -= old
        self.q126 -= old * old
        self.c126 -= oldv.astype(np.int16)
        old.fill(0)
        oldv.fill(False)
        finite_lr = np.isfinite(lr)
        old[tids[finite_lr]] = lr[finite_lr].astype(np.float32)
        oldv[tids[finite_lr]] = True
        self.s126[tids[finite_lr]] += lr[finite_lr]
        self.q126[tids[finite_lr]] += lr[finite_lr] * lr[finite_lr]
        self.c126[tids[finite_lr]] += 1

        k2 = gday % 21
        old2 = self.r21[k2]
        oldv2 = self.rv21[k2]
        self.s21 -= old2
        self.q21 -= old2 * old2
        self.c21 -= oldv2.astype(np.int16)
        old2.fill(0)
        oldv2.fill(False)
        old2[tids[finite_lr]] = lr[finite_lr].astype(np.float32)
        oldv2[tids[finite_lr]] = True
        self.s21[tids[finite_lr]] += lr[finite_lr]
        self.q21[tids[finite_lr]] += lr[finite_lr] * lr[finite_lr]
        self.c21[tids[finite_lr]] += 1

        fsum = self.s126[tids] - self.s21[tids]
        fsq = self.q126[tids] - self.q21[tids]
        fcnt = self.c126[tids] - self.c21[tids]
        var = np.divide(
            fsq - fsum * fsum / np.maximum(fcnt, 1),
            np.maximum(fcnt - 1, 1),
            out=np.full(len(tids), np.nan),
            where=fcnt > 1,
        )
        fvol = np.sqrt(np.maximum(var, 0)) * np.sqrt(252)
        score = np.divide(
            np.log1p(mom), fvol, out=np.full(len(tids), np.nan),
            where=np.isfinite(mom) & (mom > -1) & np.isfinite(fvol) & (fvol > 0),
        )

        kd = gday % 20
        self.dvsum -= self.dvbuf[kd]
        self.dvbuf[kd].fill(0)
        self.dvbuf[kd, tids] = dv.astype(np.float32)
        self.dvsum[tids] += dv
        adv = self.dvsum[tids] / 20 if gday >= 19 else np.full(len(tids), np.nan)

        self.close_ring[gday % 130].fill(np.nan)
        self.close_ring[gday % 130, tids] = c.astype(np.float32)
        return {
            "recent": recent,
            "mom": mom,
            "r63": r63,
            "score": score,
            "adv": adv,
            "fvol": fvol,
            "day_dv": dv,
            "continuous": (self.c126[tids] >= 126),
        }


def _session_boundaries(date_ns: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    if len(date_ns) == 0:
        return np.empty(0, dtype=np.int64), np.array([0], dtype=np.int64)
    starts = np.r_[0, np.flatnonzero(date_ns[1:] != date_ns[:-1]) + 1].astype(np.int64)
    offsets = np.r_[starts, len(date_ns)].astype(np.int64)
    return date_ns[starts].astype(np.int64, copy=False), offsets


def build(dataset_root: Path, output: Path) -> dict:
    dataset = CanonicalPITDataset(dataset_root)
    output.mkdir(parents=True, exist_ok=True)
    identity_rows, sid_to_tid = _identity_rows(dataset)
    state = _FeatureState(len(identity_rows))
    members: dict[str, dict] = {}
    total_rows = 0
    total_sessions = 0

    start_year = int(dataset.window["warmup_start"][:4])
    end_year = int(dataset.window["end"][:4])
    for year in range(start_year, end_year + 1):
        frame = dataset.research_observations(year)
        if frame.empty:
            continue
        ids = frame.security_id.astype(str).map(sid_to_tid)
        if ids.isna().any():
            missing = frame.loc[ids.isna(), "security_id"].astype(str).unique().tolist()[:10]
            raise RuntimeError(f"compiled PIT research tape has unmapped security ids: {missing}")
        frame = frame.copy()
        frame["tid"] = ids.astype(np.int32).to_numpy()
        frame["date"] = pd.to_datetime(frame["date"])
        frame.sort_values(["date", "tid"], inplace=True, kind="mergesort")
        frame.reset_index(drop=True, inplace=True)

        date_ns = frame.date.astype("int64").to_numpy(np.int64, copy=False)
        sessions, offsets = _session_boundaries(date_ns)
        rows = len(frame)
        recent = np.full(rows, np.nan)
        mom = np.full(rows, np.nan)
        r63 = np.full(rows, np.nan)
        score = np.full(rows, np.nan)
        adv = np.full(rows, np.nan)
        fvol = np.full(rows, np.nan)
        day_dv = np.full(rows, np.nan)
        continuous = np.zeros(rows, dtype=bool)

        close = frame["close"].to_numpy(float, copy=False)
        closeunadj = frame["closeunadj"].to_numpy(float, copy=False)
        raw_open = frame["canonical_raw_open"].to_numpy(float, copy=False)
        volume = frame["volume"].to_numpy(float, copy=False)
        open_signal = raw_open * close / closeunadj
        tids = frame["tid"].to_numpy(np.int32, copy=False)

        for lo, hi in zip(offsets[:-1], offsets[1:]):
            result = state.step(tids[lo:hi], close[lo:hi], volume[lo:hi])
            recent[lo:hi] = result["recent"]
            mom[lo:hi] = result["mom"]
            r63[lo:hi] = result["r63"]
            score[lo:hi] = result["score"]
            adv[lo:hi] = result["adv"]
            fvol[lo:hi] = result["fvol"]
            day_dv[lo:hi] = result["day_dv"]
            continuous[lo:hi] = result["continuous"]

        path = output / f"research-{year}.npz"
        np.savez_compressed(
            path,
            session_ns=sessions,
            offsets=offsets,
            tid=tids,
            close=close,
            closeunadj=closeunadj,
            open=open_signal,
            volume=volume,
            dividend_per_share=frame["dividend_per_share"].to_numpy(float, copy=False),
            split_ratio=frame["split_ratio"].to_numpy(float, copy=False),
            recent=recent,
            mom=mom,
            r63=r63,
            score=score,
            adv=adv,
            fvol=fvol,
            day_dv=day_dv,
            continuous=continuous,
            security_type_code=_security_type_codes(frame["security_type"]),
        )
        member = {
            "sha256": _sha256(path),
            "bytes": path.stat().st_size,
            "rows": rows,
            "sessions": len(sessions),
        }
        members[path.name] = member
        total_rows += rows
        total_sessions += len(sessions)
        print(
            f"[COMPILED PIT] year={year} rows={rows:,} sessions={len(sessions)} bytes={path.stat().st_size:,}",
            flush=True,
        )

    compiler_sha = _compiler_sha256()
    manifest = {
        "schema": SCHEMA,
        "status": "PASS",
        "source_dataset_hash": dataset.dataset_hash,
        "source_dataset_schema": dataset.manifest.get("schema"),
        "source_window": dataset.window,
        "compiler_sha256": compiler_sha,
        "feature_spec": FEATURE_SPEC,
        "feature_spec_hash": FEATURE_SPEC_HASH,
        "security_count": len(identity_rows),
        "rows": total_rows,
        "sessions": total_sessions,
        "members": dict(sorted(members.items())),
    }
    manifest["tape_hash"] = _tape_hash(dataset.dataset_hash, compiler_sha, members)
    (output / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


class _FastSeries:
    __slots__ = ("_array",)

    def __init__(self, array: np.ndarray):
        self._array = array

    def to_numpy(self, dtype=None, copy: bool = False) -> np.ndarray:
        array = self._array if dtype is None else self._array.astype(dtype, copy=False)
        return array.copy() if copy else array


class _FastGroup:
    __slots__ = tuple(name for name in _REQUIRED_ARRAYS if name not in {"session_ns", "offsets"})

    def __init__(self, arrays: dict[str, np.ndarray], lo: int, hi: int):
        for name in self.__slots__:
            setattr(self, name, _FastSeries(arrays[name][lo:hi]))


class CompiledYear:
    def __init__(self, path: Path, *, end: str | None = None):
        with np.load(path, allow_pickle=False) as loaded:
            missing = set(_REQUIRED_ARRAYS).difference(loaded.files)
            if missing:
                raise RuntimeError(f"compiled PIT year missing arrays: {sorted(missing)}")
            self._arrays = {name: loaded[name] for name in _REQUIRED_ARRAYS}
        session_ns = self._arrays["session_ns"]
        offsets = self._arrays["offsets"]
        keep_sessions = len(session_ns)
        if end is not None and keep_sessions:
            end_ns = pd.Timestamp(end).value
            keep_sessions = int(np.searchsorted(session_ns, end_ns, side="right"))
        self._session_count = keep_sessions
        self._row_count = int(offsets[keep_sessions]) if len(offsets) else 0
        self.quarter_last = self._compute_quarter_last()

    def _compute_quarter_last(self) -> tuple[pd.Timestamp, ...]:
        sessions = [pd.Timestamp(int(v)) for v in self._arrays["session_ns"][: self._session_count]]
        last: dict[tuple[int, int], pd.Timestamp] = {}
        for value in sessions:
            last[(value.year, value.quarter)] = value
        return tuple(last[key] for key in sorted(last))

    def __len__(self) -> int:
        return self._row_count

    def groupby(self, _column: str, sort: bool = True) -> Iterator[tuple[pd.Timestamp, _FastGroup]]:
        if not sort:
            raise RuntimeError("compiled PIT research sessions require chronological order")
        offsets = self._arrays["offsets"]
        sessions = self._arrays["session_ns"]
        for index in range(self._session_count):
            lo = int(offsets[index])
            hi = int(offsets[index + 1])
            yield pd.Timestamp(int(sessions[index])), _FastGroup(self._arrays, lo, hi)


class CompiledPITResearchTape:
    def __init__(
        self,
        root: Path,
        *,
        expected_dataset_hash: str | None = None,
        verify_files: bool = True,
    ):
        self.root = Path(root)
        self.manifest_path = self.root / "manifest.json"
        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        if self.manifest.get("schema") != SCHEMA or self.manifest.get("status") != "PASS":
            raise RuntimeError("compiled PIT research tape is not a PASS v1 artifact")
        if self.manifest.get("feature_spec_hash") != FEATURE_SPEC_HASH:
            raise RuntimeError("compiled PIT feature definition changed")
        if self.manifest.get("compiler_sha256") != _compiler_sha256():
            raise RuntimeError("compiled PIT compiler source does not match this checkout")
        if expected_dataset_hash is not None and self.manifest.get("source_dataset_hash") != expected_dataset_hash:
            raise RuntimeError("compiled PIT source dataset hash mismatch")
        members = self.manifest.get("members") or {}
        expected_tape_hash = _tape_hash(
            str(self.manifest.get("source_dataset_hash")),
            str(self.manifest.get("compiler_sha256")),
            members,
        )
        if expected_tape_hash != self.manifest.get("tape_hash"):
            raise RuntimeError("compiled PIT aggregate tape hash mismatch")
        if verify_files:
            for name, expected in members.items():
                path = self.root / name
                if not path.is_file():
                    raise RuntimeError(f"compiled PIT member missing: {name}")
                if path.stat().st_size != int(expected["bytes"]):
                    raise RuntimeError(f"compiled PIT member size changed: {name}")
                if _sha256(path) != expected["sha256"]:
                    raise RuntimeError(f"compiled PIT member hash changed: {name}")
        self.source_dataset_hash = str(self.manifest["source_dataset_hash"])
        self.tape_hash = str(self.manifest["tape_hash"])

    def year(self, year: int, *, end: str | None = None) -> CompiledYear:
        path = self.root / f"research-{int(year)}.npz"
        if path.name not in (self.manifest.get("members") or {}):
            raise RuntimeError(f"compiled PIT year missing: {year}")
        return CompiledYear(path, end=end)


def verify(root: Path, expected_dataset_hash: str | None = None) -> dict:
    tape = CompiledPITResearchTape(root, expected_dataset_hash=expected_dataset_hash, verify_files=True)
    rows = 0
    sessions = 0
    for name, expected in sorted((tape.manifest.get("members") or {}).items()):
        path = tape.root / name
        with np.load(path, allow_pickle=False) as loaded:
            missing = set(_REQUIRED_ARRAYS).difference(loaded.files)
            if missing:
                raise RuntimeError(f"{name}: missing arrays {sorted(missing)}")
            offsets = loaded["offsets"]
            if int(offsets[-1]) != int(expected["rows"]):
                raise RuntimeError(f"{name}: row count mismatch")
            if len(loaded["session_ns"]) != int(expected["sessions"]):
                raise RuntimeError(f"{name}: session count mismatch")
            for key in _REQUIRED_ARRAYS:
                if key in {"session_ns", "offsets"}:
                    continue
                if len(loaded[key]) != int(expected["rows"]):
                    raise RuntimeError(f"{name}: {key} length mismatch")
            rows += int(expected["rows"])
            sessions += int(expected["sessions"])
    if rows != int(tape.manifest["rows"]) or sessions != int(tape.manifest["sessions"]):
        raise RuntimeError("compiled PIT manifest totals changed")
    return tape.manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    build_p = sub.add_parser("build")
    build_p.add_argument("--dataset", type=Path, required=True)
    build_p.add_argument("--output", type=Path, required=True)
    verify_p = sub.add_parser("verify")
    verify_p.add_argument("--tape", type=Path, required=True)
    verify_p.add_argument("--dataset-hash")
    args = parser.parse_args()
    if args.command == "build":
        manifest = build(args.dataset, args.output)
    else:
        manifest = verify(args.tape, args.dataset_hash)
    print(json.dumps({
        "status": manifest["status"],
        "source_dataset_hash": manifest["source_dataset_hash"],
        "tape_hash": manifest["tape_hash"],
        "rows": manifest["rows"],
        "sessions": manifest["sessions"],
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
