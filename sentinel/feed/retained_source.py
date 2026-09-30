"""Acquire missing components once; retain validated input across worker claims."""
from datetime import date

from sentinel.feed import action_source, authority, progress, session_envelope, sharadar
from sentinel.feed.acquisition_parts import Parts, SourceRevision
from sentinel.feed.rolling_contract import digest
from sentinel.feed.rolling_source import SharadarSource, component, generation, json_value, ordered
from sentinel.feed.source_authority.dates import SepUpdateEnvelope, _canonical_key


class RetainedSource(SharadarSource):
    def __init__(self, window, conn, lease, *, corrections=None):
        super().__init__(window, corrections=corrections)
        self.parts = Parts(conn, lease)

    def _part(self, name, gen, acquire, checkpoint, *, part=None, parts=None):
        details = {"table": name.split(".")[0]}
        if "." in name:
            _, lo, hi = name.split(".")
            details.update(date_from=lo, date_to=hi)
        if part:
            details.update(part=part, parts=parts)
        with self.parts.unit():
            progress.emit("source_replay", "started", reason="VERIFY_RETAINED_PART", **details)
            retained = self.parts.get(name, gen)
            if retained is None:
                progress.emit("source_download", "started", reason="ACQUIRE_MISSING_PART", **details)
                payload, prices, evidence, count = acquire()
                progress.emit("source_replay", "working", reason="STAGING_NEW_PART", rows=count, **details)
                retained = self.parts.put(name, gen, payload=payload, prices=prices,
                                          evidence=evidence, rows=count)
                reason = "PART_COMMITTED"
            else:
                reason = "RETAINED_PART_REUSED"
            manifest, payload = retained
            if manifest["evidence"] is not None:
                self.evidence.append(manifest["evidence"])
            checkpoint(name, gen, manifest["content_sha256"], manifest["rows"], 0)
            progress.emit("source_replay", "completed", reason=reason, rows=manifest["rows"], **details)
            return payload

    def _export(self, snapshot, required):
        try:
            rows, _ = self._download(snapshot, required)
        except authority.VendorPublicationUnstable as exc:
            raise SourceRevision(component(snapshot), digest(generation(snapshot)), "REOBSERVE_REQUIRED") from exc
        # _part adds provenance for both new and retained paths exactly once.
        return rows, self.evidence.pop()

    def references(self, checkpoint):
        def actions():
            rows, proof = self._export(self.snapshots[0], action_source.SOURCE_FIELDS)
            for row in rows:
                day = str(row.get("date") or "")
                if date.fromisoformat(day).isoformat() != day or not "1900-01-01" <= day <= str(self.window.end):
                    raise ValueError("ACTIONS observation outside requested reference interval")
            payload = [value for _, value, _ in action_source.distinct_rows(rows)]
            return payload, None, proof, len(rows)
        self.actions = self._part(component(self.snapshots[0]), generation(self.snapshots[0]), actions, checkpoint)

        def tickers():
            exported, proof = self._export(self.snapshots[1], ("table", "permaticker", "ticker"))
            values = self._tickers_json(exported)
            # Only keys are needed to corroborate completeness after a restart.
            keys = [{k: row.get(k) for k in ("table", "permaticker", "ticker")} for row in exported]
            keys = ordered(keys)
            return {"tickers": values, "keys": keys}, None, proof, len(values)
        metadata = self._part("TICKERS", generation(self.snapshots[1]), tickers, checkpoint)
        self.tickers, self._ticker_keys = metadata["tickers"], metadata["keys"]

        def sfp():
            values = self._sfp()
            return values, None, None, len(values)
        self.sfp = self._part("SFP", {"table": "SFP", "window": self.window.model_dump(mode="json")}, sfp, checkpoint)

    def acquire_prices(self, checkpoint, pulse):
        for index, snapshot in enumerate(self.snapshots[2:], 1):
            def acquire():
                rows, proof = self._export(snapshot, (
                    "ticker", "date", "open", "close", "closeunadj", "volume", "lastupdated"))
                checked = session_envelope.validate_rows(rows, source="SEP",
                    date_from=snapshot.params["date.gte"], date_to=snapshot.params["date.lte"],
                    operation="rolling_comparison")
                envelope = SepUpdateEnvelope.through(snapshot.refreshed.date())
                for row_index, row in enumerate(checked, 1):
                    ticker, day = _canonical_key(sharadar.SEP, row)
                    envelope.validate(row.get("lastupdated"), ticker=ticker, session=day)
                    # Replace consumed rows in the bounded export buffer instead
                    # of retaining a second full partition of dictionaries.
                    rows[row_index - 1] = json_value({**row, "ticker": ticker, "date": day})
                    if row_index % 5000 == 0:
                        pulse()
                return None, rows, proof, len(rows)
            self._part(component(snapshot), generation(snapshot), acquire, checkpoint,
                       part=index, parts=len(self.snapshots) - 2)

    def corroborate(self):
        # Preserve the original overridable corroboration seam used by the
        # production qualification harness and source mutation tests.
        return super().corroborate()

    def preflight(self):
        try:
            return super().preflight()
        except authority.VendorPublicationUnstable as exc:
            raise SourceRevision("*", "SEP_REFRESH", "INCONSISTENT_PARTITIONS") from exc
