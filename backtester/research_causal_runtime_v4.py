#!/usr/bin/env python3
"""Final causal runtime: guarded split cache and schema-safe terminal poison."""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Mapping

import pandas as pd

from backtester import research_causal_runtime as base
from backtester.research_causal_runtime_v2 import *  # noqa: F401,F403
from backtester.research_causal_runtime_v2 import CausalPITDataset as V2Dataset


class GuardedDateSet(set):
    def __contains__(self, value):
        base.reject_future(value, "split-date cache")
        return super().__contains__(value)


def guarded_split_dates(values: Mapping) -> dict:
    return {key: GuardedDateSet(items) for key, items in values.items()}


class CausalPITDataset(V2Dataset):
    def terminal_frame(self) -> pd.DataFrame:
        frame = pd.read_csv(
            self.root / "terminal-events.csv.gz",
            compression="gzip",
            dtype=str,
            keep_default_na=False,
        )
        date_column = (
            "effective_session" if "effective_session" in frame.columns else "session"
        )
        if date_column not in frame.columns:
            raise RuntimeError("terminal event table has no causal date column")
        if self.variant == "prefix":
            frame = frame[frame[date_column].astype(str) <= str(self.cutoff)].copy()
        elif self.variant == "poison":
            mask = frame[date_column].astype(str) > str(self.cutoff)
            numeric_candidates = (
                "cash_per_share",
                "exchange_ratio",
                "stock_ratio",
                "share_ratio",
                "cash_in_lieu_price_per_delivered_share",
                "cash_in_lieu_price",
                "settlement_value",
                "canonical_value",
            )
            for index in frame.index[mask]:
                security = (
                    frame.at[index, "security_id"]
                    if "security_id" in frame.columns
                    else frame.at[index, "ticker"]
                )
                seed = f"terminal|{security}|{frame.at[index, date_column]}"
                if "disposition" in frame.columns:
                    frame.at[index, "disposition"] = "FUTURE_POISON"
                if "settlement_kind" in frame.columns:
                    frame.at[index, "settlement_kind"] = "FUTURE_POISON_CASH"
                for field in numeric_candidates:
                    if field not in frame.columns or not frame.at[index, field]:
                        continue
                    try:
                        frame.at[index, field] = format(
                            max(
                                float(frame.at[index, field])
                                * base._poison_factor(seed + "|" + field),
                                1.0e-9,
                            ),
                            ".17g",
                        )
                    except ValueError:
                        continue
                if "authority" in frame.columns:
                    frame.at[index, "authority"] = "FUTURE_POISON"
                if "source" in frame.columns:
                    frame.at[index, "source"] = "FUTURE_POISON"
                evidence = hashlib.sha256(seed.encode("utf-8")).hexdigest()
                for field in ("evidence_hash", "source_hash", "provenance_hash"):
                    if field in frame.columns:
                        frame.at[index, field] = evidence
            self._poison_counts["terminal_events"] += int(mask.sum())
        return frame

    def runtime_manifest(self) -> dict[str, object]:
        terminal = self.terminal_frame()
        date_column = (
            "effective_session" if "effective_session" in terminal.columns else "session"
        )
        terminal_after = (
            0
            if not self.cutoff
            else int((terminal[date_column].astype(str) > str(self.cutoff)).sum())
        )
        return {
            "schema": "backtester.research-causal-runtime/1",
            "status": "PASS",
            "variant": self.variant,
            "cutoff": self.cutoff,
            "dataset_hash": self.dataset_hash,
            "full_window": dict(self.window),
            "visible_session_count": len(self.sessions),
            "full_session_count": len(self.full_sessions),
            "poison_counts": dict(sorted(self._poison_counts.items())),
            "terminal_rows_visible": int(len(terminal)),
            "terminal_rows_after_cutoff": terminal_after,
            "terminal_date_column": date_column,
            "terminal_terms_economically_consumed_by_retained_research": False,
            "terminal_action_signals_consumed": True,
        }
