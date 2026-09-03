#!/usr/bin/env python3
"""Strict-prior adapter for admitted historical-metadata V2 evidence.

The V2 reconstruction package is keyed to the canonical security episodes that
were audited during reconstruction.  This adapter therefore never creates,
merges, or renumbers security identities.  It may only replace issuer,
security-type, and SIC observations when the guarded V2 timeline contains
evidence whose ``usable_after`` date is strictly earlier than the simulated
session.
"""
from __future__ import annotations

import bisect
import csv
import gzip
import hashlib
import json
from pathlib import Path
from typing import Mapping


TIMELINE_SCHEMA = "backtester.historical-metadata-reconstruction-v2.guarded-timeline/1"
CAUSAL_RULE = "filed/usable_after < decision_session"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_gzip_csv(path: Path) -> list[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        return [dict(row) for row in csv.DictReader(handle)]


def _canonical_cik(value: object) -> str:
    text = str(value or "").strip()
    if not text.isdigit():
        return ""
    number = int(text)
    return str(number) if number > 0 else ""


def _canonical_sic(value: object) -> str:
    text = "".join(ch for ch in str(value or "") if ch.isdigit())
    if not text:
        return ""
    number = int(text)
    return str(number) if 0 < number <= 9999 else ""


class HistoricalMetadataV2Authority:
    """Read-only, strict-prior metadata authority over one verified V2 package."""

    def __init__(self, package_root: Path):
        self.root = Path(package_root)
        self.timeline_root = self.root / "timeline"
        coverage_path = self.timeline_root / "timeline_coverage.json"
        if not coverage_path.is_file():
            raise RuntimeError("historical metadata V2 package lacks timeline coverage")
        self.coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
        if self.coverage.get("schema") != TIMELINE_SCHEMA:
            raise RuntimeError("unexpected historical metadata V2 timeline schema")
        if self.coverage.get("status") != "PASS":
            raise RuntimeError(
                "historical metadata V2 timeline is not conflict-free: "
                f"{self.coverage.get('status')!r}"
            )
        if self.coverage.get("causal_rule") != CAUSAL_RULE:
            raise RuntimeError("historical metadata V2 causal rule changed")
        if (
            self.coverage.get("ticker_alias_policy")
            != "disabled_without_independent_historical_alias_proof"
        ):
            raise RuntimeError("historical metadata V2 ticker-alias policy changed")
        admission = str(self.coverage.get("admission_status") or "")
        if admission not in {"READY", "REVIEW_REQUIRED"}:
            raise RuntimeError(
                f"unexpected historical metadata V2 admission status: {admission!r}"
            )

        self.identity_dates, self.identity_rows = self._load_series(
            "identity_events.csv.gz", value_field="cik"
        )
        self.type_dates, self.type_rows = self._load_series(
            "security_type_events.csv.gz", value_field="classification"
        )
        self.sic_dates, self.sic_rows = self._load_series(
            "sic_events.csv.gz", value_field="sic"
        )
        self.stats = {
            "issuer_observations_overridden": 0,
            "security_type_unknown_observations_resolved": 0,
            "security_type_known_observations_replaced": 0,
            "sic_observations_overridden": 0,
        }

    def _load_series(
        self, name: str, *, value_field: str
    ) -> tuple[dict[str, tuple[str, ...]], dict[str, tuple[dict[str, str], ...]]]:
        path = self.timeline_root / name
        if not path.is_file():
            raise RuntimeError(f"historical metadata V2 package lacks {name}")
        grouped: dict[str, dict[str, dict[str, str]]] = {}
        for raw in _read_gzip_csv(path):
            sid = str(raw.get("security_id") or "").strip()
            ticker = str(raw.get("ticker") or "").strip().upper()
            usable_after = str(raw.get("usable_after") or "")[:10]
            value = str(raw.get(value_field) or "").strip()
            if not sid or not ticker or len(usable_after) != 10 or not value:
                raise RuntimeError(f"invalid historical metadata V2 {name} row: {raw}")
            if value_field == "cik" and not _canonical_cik(value):
                raise RuntimeError(f"invalid historical metadata V2 CIK: {value!r}")
            if value_field == "classification" and value not in {"common", "non_common"}:
                raise RuntimeError(
                    f"invalid historical metadata V2 security classification: {value!r}"
                )
            if value_field == "sic" and not _canonical_sic(value):
                raise RuntimeError(f"invalid historical metadata V2 SIC: {value!r}")
            by_date = grouped.setdefault(sid, {})
            existing = by_date.get(usable_after)
            normalized = dict(raw)
            normalized["ticker"] = ticker
            normalized["usable_after"] = usable_after
            if existing is not None:
                if (
                    str(existing.get(value_field)) != value
                    or str(existing.get("ticker")) != ticker
                ):
                    raise RuntimeError(
                        "historical metadata V2 contains conflicting same-date "
                        f"{value_field} evidence for {sid} on {usable_after}"
                    )
                continue
            by_date[usable_after] = normalized

        dates: dict[str, tuple[str, ...]] = {}
        rows: dict[str, tuple[dict[str, str], ...]] = {}
        for sid, by_date in grouped.items():
            ordered_dates = tuple(sorted(by_date))
            dates[sid] = ordered_dates
            rows[sid] = tuple(by_date[value] for value in ordered_dates)
        return dates, rows

    @staticmethod
    def _strict_prior(
        dates: Mapping[str, tuple[str, ...]],
        rows: Mapping[str, tuple[dict[str, str], ...]],
        security_id: str,
        session: str,
    ) -> dict[str, str] | None:
        sid = str(security_id)
        axis = dates.get(sid, ())
        index = bisect.bisect_left(axis, str(session)) - 1
        return None if index < 0 else dict(rows[sid][index])

    @staticmethod
    def _require_ticker(row: Mapping[str, str], ticker: str, label: str) -> None:
        observed = str(row.get("ticker") or "").upper()
        if observed != str(ticker).upper():
            raise RuntimeError(
                f"historical metadata V2 {label} ticker mismatch: "
                f"{observed!r} != {ticker!r}"
            )

    @staticmethod
    def _undo_legacy_type_counter(type_authority, source: str) -> None:
        counter = {
            "SEC_POSITIVE_STRICT_PRIOR_CIK_MATCH": "auto_common",
            "MANUAL_EXACT_SESSION_COMMON": "manual_common",
            "MANUAL_EXACT_SESSION_NON_COMMON": "manual_non_common",
        }.get(str(source))
        if counter is None:
            if str(source).startswith(("NO_STRICT_PRIOR_", "SEC_POSITIVE_STRICT_PRIOR_CIK_MISMATCH")):
                counter = "unknown"
            else:
                raise RuntimeError(
                    f"cannot account for legacy security-type source {source!r}"
                )
        value = getattr(type_authority, counter, None)
        if not isinstance(value, int) or value <= 0:
            raise RuntimeError(
                f"legacy security-type counter {counter} cannot be reversed"
            )
        setattr(type_authority, counter, value - 1)

    def apply(
        self,
        *,
        security_id: str,
        ticker: str,
        session: str,
        legacy: Mapping[str, str],
        type_authority,
        ff12_for_sic,
    ) -> dict[str, str]:
        """Overlay only evidence that was usable strictly before ``session``."""
        result = dict(legacy)
        sid = str(security_id)
        session = str(session)

        identity = self._strict_prior(
            self.identity_dates, self.identity_rows, sid, session
        )
        if identity is not None:
            self._require_ticker(identity, ticker, "identity")
            cik = _canonical_cik(identity.get("cik"))
            if not cik:
                raise RuntimeError("historical metadata V2 identity has invalid CIK")
            issuer_id = f"SEC_CIK:{cik}"
            if result.get("issuer_id") != issuer_id:
                self.stats["issuer_observations_overridden"] += 1
            result["issuer_id"] = issuer_id
            result["issuer_source"] = "SEC_V2_GUARDED_STRICT_PRIOR_CIK"

        security_type = self._strict_prior(
            self.type_dates, self.type_rows, sid, session
        )
        if security_type is not None:
            self._require_ticker(security_type, ticker, "security type")
            classification = str(security_type["classification"])
            prior_classification = str(result.get("security_type") or "unknown")
            prior_source = str(result.get("security_type_source") or "")
            if (
                prior_classification != classification
                or not prior_source.startswith("SEC_V2_")
            ):
                self._undo_legacy_type_counter(type_authority, prior_source)
                if prior_classification == "unknown":
                    self.stats["security_type_unknown_observations_resolved"] += 1
                else:
                    self.stats["security_type_known_observations_replaced"] += 1
            result["security_type"] = classification
            result["security_type_source"] = (
                "SEC_V2_GUARDED_STRICT_PRIOR_SECURITY_TITLE"
            )
            eligible = classification == "common"
            result["security_type_eligible"] = "1" if eligible else "0"
            result["metadata_admitted"] = "1" if eligible else "0"

        sic = self._strict_prior(self.sic_dates, self.sic_rows, sid, session)
        if sic is not None:
            self._require_ticker(sic, ticker, "SIC")
            sic_value = _canonical_sic(sic.get("sic"))
            if not sic_value:
                raise RuntimeError("historical metadata V2 SIC is invalid")
            if str(result.get("sic") or "") != sic_value:
                self.stats["sic_observations_overridden"] += 1
            result["sic"] = sic_value
            result["ff12"] = ff12_for_sic(int(sic_value))
            result["sector_source"] = (
                "SEC_V2_GUARDED_STRICT_PRIOR_SIC_FROZEN_FF12"
            )

        return result

    def provenance(self) -> dict:
        members = {}
        for name in (
            "timeline/timeline_coverage.json",
            "timeline/identity_events.csv.gz",
            "timeline/security_type_events.csv.gz",
            "timeline/sic_events.csv.gz",
            "timeline/unresolved_episodes.csv.gz",
            "timeline/ambiguous_identity_events.csv.gz",
            "timeline/security_type_conflicts.csv.gz",
            "evidence_manifest.json",
            "source_lock.json",
            "SHA256SUMS.txt",
        ):
            path = self.root / name
            if path.is_file():
                members[name] = {
                    "sha256": sha256_file(path),
                    "bytes": path.stat().st_size,
                }
        return {
            "schema": "backtester.canonical-pit-historical-metadata-v2-overlay/1",
            "status": "PASS",
            "timeline_status": self.coverage["status"],
            "admission_status": self.coverage["admission_status"],
            "causal_rule": CAUSAL_RULE,
            "security_identity_policy": (
                "preserve canonical security_id; metadata overlay cannot split, "
                "merge, or renumber episodes"
            ),
            "stats": dict(self.stats),
            "members": dict(sorted(members.items())),
        }
