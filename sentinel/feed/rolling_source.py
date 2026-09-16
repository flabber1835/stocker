"""Direct, bounded Sharadar transport for comparison snapshots, not a seed."""
from __future__ import annotations

from decimal import Decimal
from datetime import date

from sentinel.feed import (
    action_source, authority, calendar, coherence, session_envelope, sharadar,
    snapshot_export, tickers_authority,
)
from sentinel.feed.operational_source import _months
from sentinel.feed.rolling_contract import canonical_json, digest
from sentinel.feed.source_authority import validated_source_rows
from sentinel.feed.source_authority.dates import SepUpdateEnvelope, _canonical_key


def json_value(value):
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {str(k): json_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_value(v) for v in value]
    return value


def ordered(rows):
    return sorted((json_value(dict(row)) for row in rows), key=canonical_json)


def generation(snapshot):
    # Capture time and signed URL are not generation or economic identities.
    return {"table": snapshot.table, "params": dict(snapshot.params),
            "refreshed": snapshot.refreshed.isoformat()}


def component(snapshot):
    return snapshot.table + ("." + snapshot.params["date.gte"] + "."
                             + snapshot.params["date.lte"] if snapshot.params else "")


class SharadarSource:
    """One attempt; transports remain patchable at their existing module seams."""

    def __init__(self, window):
        self.window = window
        self.snapshots = []
        self.evidence = []
        self.tickers = self.actions = self.sfp = None

    def preflight(self):
        if str(self.window.end) > calendar.latest_closed_session():
            raise ValueError("rolling target must be a closed XNYS session")
        requests = [(sharadar.ACTIONS, {"date.gte": "1900-01-01",
                                       "date.lte": str(self.window.end)}),
                    (sharadar.TICKERS, {})]
        requests.extend((sharadar.SEP, sharadar.date_params(lo, hi))
                        for lo, hi in _months(str(self.window.start), str(self.window.end)))
        self.snapshots = [snapshot_export.probe_snapshot(table, params=params)
                          for table, params in requests]
        if len({s.refreshed for s in self.snapshots if s.table == sharadar.SEP}) != 1:
            raise authority.VendorPublicationUnstable("SEP partitions crossed a table refresh")

    def _download(self, snapshot, required):
        rows, proof = snapshot_export.download_snapshot(snapshot, required=set(required))
        if not rows:
            raise ValueError("complete source component is empty: " + snapshot.table)
        if (proof["last_refreshed_time"] != snapshot.refreshed.isoformat()
                or proof["window"] != dict(snapshot.params)):
            raise authority.VendorPublicationUnstable("download differs from selected generation")
        self.evidence.append({**generation(snapshot), "file_sha256": proof["file_sha256"],
                              "rows": len(rows)})
        return rows, proof

    def _tickers_json(self, exported):
        rows = list(tickers_authority.validate(sharadar.fetch_table(sharadar.TICKERS)))
        coherence.assert_tickers_metadata(rows)
        keys = {(str(r.get("permaticker") or "").strip(),
                 str(r.get("ticker") or "").strip().upper()) for r in exported
                if str(r.get("table") or "").upper() == "SEP"}
        if not keys:
            raise ValueError("TICKERS export has no SEP identities")
        snapshot_export.assert_complete_ticker_keys(rows, keys)
        return ordered(rows)

    def references(self, checkpoint):
        actions, proof = self._download(self.snapshots[0], action_source.SOURCE_FIELDS)
        for row in actions:
            day = str(row.get("date") or "")
            if date.fromisoformat(day).isoformat() != day or not "1900-01-01" <= day <= str(self.window.end):
                raise ValueError("ACTIONS observation outside requested reference interval")
        self.actions = [payload for _, payload, _ in action_source.distinct_rows(actions)]
        checkpoint(component(self.snapshots[0]), generation(self.snapshots[0]),
                   proof["file_sha256"], len(actions), 0)
        exported, proof = self._download(self.snapshots[1], ("table", "permaticker", "ticker"))
        self.tickers = self._tickers_json(exported)
        self._ticker_keys = exported
        checkpoint("TICKERS", generation(self.snapshots[1]),
                   digest({"csv": proof["file_sha256"], "json": self.tickers}),
                   len(self.tickers), 0)
        self.sfp = self._sfp()
        checkpoint("SFP", {"table": "SFP", "window": self.window.model_dump(mode="json")},
                   digest(self.sfp), len(self.sfp), 0)

    def _sfp(self):
        params = {**sharadar.date_params(str(self.window.start), str(self.window.end)),
                  "ticker": "SPY,BIL"}
        rows = session_envelope.validate_rows(
            sharadar.fetch_table(sharadar.SFP, params), source="SFP",
            date_from=str(self.window.start), date_to=str(self.window.end),
            operation="rolling_comparison")
        return ordered(validated_source_rows(sharadar.SFP, rows))

    def prices(self, checkpoint, pulse):
        for snapshot in self.snapshots[2:]:
            rows, proof = self._download(snapshot, (
                "ticker", "date", "open", "close", "closeunadj", "volume", "lastupdated"))
            checked = session_envelope.validate_rows(
                rows, source="SEP", date_from=snapshot.params["date.gte"],
                date_to=snapshot.params["date.lte"], operation="rolling_comparison")
            envelope = SepUpdateEnvelope.through(snapshot.refreshed.date())
            for index, row in enumerate(checked, 1):
                ticker, day = _canonical_key(sharadar.SEP, row)
                envelope.validate(row.get("lastupdated"), ticker=ticker, session=day)
                if index % 5000 == 0:
                    pulse()
                yield {**row, "ticker": ticker, "date": day}
            checkpoint(component(snapshot), generation(snapshot), proof["file_sha256"], len(rows), 0)

    def corroborate(self):
        for captured in self.snapshots:
            checked = snapshot_export.probe_snapshot(captured.table, params=captured.params)
            if checked.refreshed != captured.refreshed:
                raise authority.VendorPublicationUnstable("source refresh changed during preparation")
        if self._tickers_json(self._ticker_keys) != self.tickers:
            raise authority.VendorPublicationUnstable("TICKERS changed during preparation")
        if self._sfp() != self.sfp:
            raise authority.VendorPublicationUnstable("SPY/BIL changed during preparation")

    def reference_payload(self):
        return {"schema": "sentinel.rolling-sharadar-references/1",
                "tickers": self.tickers, "actions": self.actions}

    def source_payload(self):
        return {"schema": "sentinel.rolling-sharadar-source/1",
                "consistency": "EXPORT_REFRESH_BRACKET_AND_REFERENCE_REOBSERVATION",
                "components": self.evidence, "sfp_sha256": digest(self.sfp)}
