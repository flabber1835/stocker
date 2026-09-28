"""Fenced complete parts; their presence never grants publication authority."""
from __future__ import annotations

import json
from itertools import islice
from contextlib import contextmanager

from sentinel.feed import acquisition_work, authority, progress, rolling_jobs as jobs, store
from sentinel.feed.rolling_contract import canonical_json, digest
from sentinel.feed.tickers_authority import _Fingerprint

SCHEMA = "sentinel.acquisition-part/1"
MAX_SUCCESSORS = 3


class SourceRevision(jobs.JobRefused, authority.VendorPublicationUnstable):
    def __init__(self, component, before, after):
        if component != "*" and not jobs._COMPONENT.fullmatch(component):
            raise ValueError("invalid source component")
        self.component = component
        super().__init__(f"source component {component} changed generation or content; previous={before}; current={after}")


class PartCorrupt(RuntimeError):
    pass


class SourceRecoveryExhausted(jobs.JobRefused):
    pass


def fingerprint(rows):
    result = _Fingerprint()
    for row in rows:
        result.add(canonical_json(row).encode("ascii"))
    return result.digest()


class Parts:
    def __init__(self, conn, lease):
        self.conn, self.lease = conn, lease

    @contextmanager
    def unit(self):
        jobs.heartbeat(self.conn, self.lease, lease_seconds=600)
        remaining = jobs.status(self.conn, self.lease.job_id)["remaining_seconds"]
        self.conn.commit()
        with acquisition_work.budget(seconds=min(500, remaining)):
            yield

    def _manifest(self, part_id):
        row = self.conn.execute("SELECT manifest,reference_payload FROM sentinel_acquisition_parts "
                                "WHERE part_id=%s", (part_id,)).fetchone()
        if row is None:
            return None
        manifest, payload = row
        if digest(manifest) != part_id or manifest.get("schema") != SCHEMA:
            raise PartCorrupt("retained acquisition manifest checksum mismatch: " + part_id)
        if manifest["component"].startswith("SEP."):
            observed = _Fingerprint()
            with store.streaming_cursor(self.conn,
                    "SELECT payload,session,ticker FROM sentinel_acquisition_prices WHERE part_id=%s "
                    "ORDER BY session,ticker", (part_id,), batch=5000, withhold=True) as cur:
                for index, (encoded, day, ticker) in enumerate(cur, 1):
                    row = json.loads(encoded)
                    if row["date"] != str(day) or row["ticker"] != ticker:
                        raise PartCorrupt("retained acquisition price key mismatch: " + part_id)
                    observed.add(canonical_json(row).encode("ascii"))
                    if index % 5000 == 0:
                        jobs.heartbeat(self.conn, self.lease, lease_seconds=600)
                        self.conn.commit()
            valid = observed.rows == manifest["rows"] and observed.digest() == manifest["content_sha256"]
        else:
            valid = payload is not None and digest(payload) == manifest["content_sha256"]
        if not valid:
            raise PartCorrupt("retained acquisition payload checksum mismatch: " + part_id)
        return manifest, payload

    def get(self, component, generation):
        jobs._owned(self.conn, self.lease)
        job = self.lease.job_id
        for depth in range(MAX_SUCCESSORS + 1):
            binding = self.conn.execute("SELECT part_id FROM sentinel_acquisition_bindings "
                "WHERE job_id=%s AND component=%s", (job, component)).fetchone()
            if binding:
                value = self._manifest(binding[0])
                if value:
                    manifest, payload = value
                    if manifest["component"] != component:
                        raise PartCorrupt("retained acquisition binding differs from component")
                    if manifest["generation"] == generation:
                        self._bind(component, binding[0])
                        self.conn.commit()
                        return manifest, payload
                    if depth == 0:
                        raise SourceRevision(component, digest(manifest["generation"]), digest(generation))
            parent = self.conn.execute("SELECT parent_job_id,excluded_component FROM "
                "sentinel_acquisition_successors WHERE child_job_id=%s", (job,)).fetchone()
            if not parent or parent[1] in (component, "*"):
                break
            job = str(parent[0])
        self.conn.commit()
        return None

    def _bind(self, component, part_id):
        jobs._owned(self.conn, self.lease)
        self.conn.execute("INSERT INTO sentinel_acquisition_bindings VALUES(%s,%s,%s) "
                          "ON CONFLICT DO NOTHING", (self.lease.job_id, component, part_id))
        actual = self.conn.execute("SELECT part_id FROM sentinel_acquisition_bindings "
            "WHERE job_id=%s AND component=%s", (self.lease.job_id, component)).fetchone()
        if actual != (part_id,):
            raise PartCorrupt("acquisition binding is immutable: " + component)

    def put(self, component, generation, *, payload=None, prices=None, evidence=None, rows=0):
        jobs._owned(self.conn, self.lease)
        content = fingerprint(prices) if prices is not None else digest(payload)
        manifest = dict(schema=SCHEMA, job_id=self.lease.job_id, component=component, generation=generation,
                        content_sha256=content, rows=rows, evidence=evidence)
        part_id = digest(manifest)
        inserted = self.conn.execute("INSERT INTO sentinel_acquisition_parts(part_id,manifest,reference_payload) "
            "VALUES(%s,%s::jsonb,%s::jsonb) ON CONFLICT DO NOTHING RETURNING part_id",
            (part_id, canonical_json(manifest), canonical_json(payload) if payload is not None else None)).fetchone()
        if inserted and prices is not None:
            iterator = iter(prices)
            with self.conn.cursor() as cur:
                while batch := list(islice(iterator, 5000)):
                    with cur.copy("COPY sentinel_acquisition_prices(part_id,session,ticker,payload) FROM STDIN") as copy:
                        for row in batch:
                            copy.write_row((part_id, row["date"], row["ticker"], canonical_json(row)))
                    jobs.heartbeat(self.conn, self.lease, lease_seconds=600)
        if not inserted:
            self._manifest(part_id)  # A matching name never suffices for reuse.
        self._bind(component, part_id)  # Recheck fence and server time after writes.
        self.conn.commit()
        return manifest, payload


def price_rows(conn, job_id):
    """Preserve the canonical staging representation and global session order."""
    from sentinel.feed.staging_impl import _source_or_compat
    query = ("SELECT p.payload FROM sentinel_acquisition_prices p JOIN sentinel_acquisition_bindings b "
             "USING(part_id) WHERE b.job_id=%s AND b.component LIKE 'SEP.%%' "
             "ORDER BY p.session,p.ticker")
    with store.streaming_cursor(conn, query, (job_id,), batch=5000, withhold=True) as cur:
        previous = None
        for (encoded,) in cur:
            row = json.loads(encoded)
            key = (row["date"], row["ticker"])
            if key == previous:
                raise PartCorrupt("duplicate price key across retained acquisition parts")
            previous = key
            yield {"date": row["date"], "ticker": row["ticker"], **{
                field: _source_or_compat(row.get(field), row.get(field))
                for field in ("open", "close", "closeunadj", "closeadj", "volume")}}


def successor(conn, job_id, component):
    """Only typed revisions enter here. Preserve one absolute deadline and request."""
    current = jobs.status(conn, job_id)
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (int(current["request_sha256"][:15], 16),))
    current = jobs.status(conn, job_id)
    existing = conn.execute("SELECT child_job_id FROM sentinel_acquisition_successors "
                            "WHERE parent_job_id=%s", (job_id,)).fetchone()
    if existing:
        conn.commit()
        return str(existing[0])
    if current["state"] != "REFUSED" or current["reason"] != "SOURCE_GENERATION_CHANGED":
        raise jobs.JobRefused("source successor requires a recorded source-revision refusal")
    ancestor, depth = job_id, 0
    while parent := conn.execute("SELECT parent_job_id FROM sentinel_acquisition_successors "
                                "WHERE child_job_id=%s", (ancestor,)).fetchone():
        ancestor, depth = str(parent[0]), depth + 1
    if depth >= MAX_SUCCESSORS or current["remaining_seconds"] <= 1:
        raise SourceRecoveryExhausted("source revision restart limit or original deadline exhausted; "
            f"component={component}; successors={depth}/{MAX_SUCCESSORS}; "
            f"remaining_seconds={int(current['remaining_seconds'])}")
    # Serialize with retirement while a successor acquires dependency pins.
    conn.execute("LOCK TABLE sentinel_acquisition_parts IN SHARE MODE")
    child = jobs.enqueue(conn, jobs.PreparationRequest.model_validate(current["request"]),
                         budget_seconds=1, absolute_deadline=current["deadline"])
    child_state = jobs.status(conn, child)
    if child_state["deadline"] != current["deadline"]:
        raise jobs.JobRefused("successor cannot adopt a different deadline")
    conn.execute("INSERT INTO sentinel_acquisition_successors VALUES(%s,%s,%s)",
                 (job_id, child, component))
    if conn.execute("SELECT 1 FROM sentinel_operational_snapshot_jobs WHERE job_id=%s", (job_id,)).fetchone():
        conn.execute("INSERT INTO sentinel_operational_snapshot_jobs VALUES(%s) ON CONFLICT DO NOTHING", (child,))
    conn.commit()
    details = {}
    if component != "*":
        details["table"] = component.split(".")[0]
        if "." in component:
            _, lo, hi = component.split(".")
            details.update(date_from=lo, date_to=hi)
    progress.emit("source_replay", "selected", reason="SOURCE_REVISION_RESTART", **details,
                  part=depth + 1, parts=MAX_SUCCESSORS,
                  remaining_seconds=int(current["remaining_seconds"]))
    return child
